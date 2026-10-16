"""One fail-closed public projection for history and SSE.

The context is server-owned database access, never an input supplied by a model.
Publication is unavailable until a persisted release gate and actual bytes exist.
"""
import hashlib
import json
import sqlite3
from dataclasses import dataclass

from app.contracts.events import InternalEventRecord, PublicEvent
from app.storage.blobs import BlobStore, read_artifact

ERRORS = {
    "PROVIDER_UNAVAILABLE": ("模型连接暂不可用，请检查连接。", "reconnect"),
    "BUDGET_EXHAUSTED": ("任务预算已用完，请调整预算后重试。", "provide_input"),
    "VALIDATION_FAILED": ("结果未通过检查，请补充材料或重试。", "retry"),
    "LANGUAGE_GATE_MISSING": ("当前任务所需的语言处理尚未就绪。", "none"),
}
PROMPTS = {"missing_input": "请补充任务需要的材料。", "ambiguous_goal": "请明确任务目标和验收要求。"}

@dataclass(frozen=True)
class ProjectionContext:
    connection: sqlite3.Connection
    event_id: str
    store: BlobStore


def project_event(event: dict, *, context: ProjectionContext | None = None) -> dict | None:
    try:
        value = InternalEventRecord.model_validate(event)
        if context is None:
            return None
        connection = context.connection
        row = connection.execute("SELECT * FROM outbox_events WHERE event_id=?", (context.event_id,)).fetchone()
        if row is None or (row['task_id'], row['attempt_id'], row['sequence'], row['kind']) != (value.task_id, value.attempt_id, value.sequence, value.kind):
            return None
        if json.loads(row['internal_payload_json']) != value.payload:
            return None
        task = connection.execute("SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?", (value.task_id,value.attempt_id)).fetchone()
        turn = connection.execute("SELECT * FROM turns WHERE id=? AND conversation_id=? AND task_id=?", (row['turn_id'],row['conversation_id'],value.task_id)).fetchone()
        if task is None or turn is None or row['contract_version'] != task['contract_version']:
            return None
        envelope = dict(schema_version='1.0', event_id=row['event_id'], conversation_id=row['conversation_id'], turn_id=row['turn_id'], task_id=value.task_id, attempt_id=value.attempt_id, sequence=row['conversation_sequence'])
        kind = value.kind
        if kind == 'message.accepted':
            payload = dict(message_id=turn['id'],text=turn['user_text'],language=turn['language'])
        elif kind == 'response.pending':
            payload = dict(status='pending')
        elif kind == 'request.failed':
            code = value.payload.get('error_code')
            if code not in ERRORS:
                code = 'PROVIDER_UNAVAILABLE'
            text, action = ERRORS[code]
            payload = dict(error_code=code,text=text,language='zh-CN',action=action)
        elif kind == 'input.required':
            if 'clarification_release_id' in value.payload:
                from app.translation.clarification import validate_publication
                payload=validate_publication(connection,context.store,row['event_id'],historical=True)
                return PublicEvent.model_validate({**envelope,'kind':kind,'payload':payload}).model_dump(mode='json')
            code = value.payload.get('prompt_code')
            if code not in PROMPTS:
                return None
            payload = dict(prompt_id=row['event_id'],text=PROMPTS[code],language='zh-CN')
        elif kind == 'request.cancelled':
            if not task['cancel_requested']:
                return None
            confirmed = task['external_stop_confirmed']
            payload = dict(text='取消请求已记录。', language='zh-CN',cancel_requested=True,external_stop_confirmed=None if confirmed is None else bool(confirmed))
        elif kind in ('answer.published', 'artifacts.published'):
            payload = _release_payload(connection, context.store, task, kind, event_id=row['event_id'])
            if payload is None:
                return None
        else:
            return None
        return PublicEvent.model_validate({**envelope,'kind':kind,'payload':payload}).model_dump(mode='json')
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
        return None


def _release_payload(connection, store, task, kind, *, event_id=None):
    """Read a frozen actual publication. Without event_id, require current eligibility.

Historic releases retain their original version and bytes. A previously hidden
model event never acquires authority because some later release was approved.
"""
    historical=event_id is not None
    if kind=='artifacts.published' and event_id is not None:
        from app.documents.publish import frozen_event_payload
        return frozen_event_payload(connection,store,event_id)
    if kind!='answer.published':
        return None
    checkpoint=json.loads(task['checkpoint_json'])
    if event_id is None:
        release=checkpoint.get('public_release')
        latest=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=? ORDER BY attempt_number DESC,created_at DESC,attempt_id DESC LIMIT 1',(task['task_id'],)).fetchone()
        if not isinstance(release,dict) or task['state']!='PUBLISHED' or task['cancel_requested'] or checkpoint.get('stale') or checkpoint.get('publication_blocked') or latest[0]!=task['attempt_id']:
            return None
        from app.storage.revisions import is_current_revision
        if not is_current_revision(connection,task['task_id'],task['attempt_id'],release['revision_id']):
            return None
        event_id=release.get('event_id')
    row=connection.execute("SELECT * FROM outbox_events WHERE event_id=? AND kind='answer.published' AND task_id=? AND attempt_id=?",(event_id,task['task_id'],task['attempt_id'])).fetchone()
    publication=connection.execute("SELECT * FROM checks WHERE id=? AND task_id=? AND attempt_id=? AND check_kind='release.publication' AND result='pass'",('publication-'+str(event_id),task['task_id'],task['attempt_id'])).fetchone()
    if row is None or publication is None or row['public_event_json'] is None:
        return None
    details=json.loads(publication['details_json'])
    public=PublicEvent.model_validate_json(row['public_event_json']).model_dump(mode='json')
    digest=hashlib.sha256(json.dumps(public,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()
    route=json.loads(task['route_snapshot_json'])
    publisher=details.get('published_via')
    if publisher not in ('native_publisher_v1','answer_publisher_v1'):
        return None
    expected={'event_id':event_id,'task_id':task['task_id'],'attempt_id':task['attempt_id'],'contract_version':row['contract_version'],'artifact_version_id':public['payload']['content_version_id'],'route_snapshot_id':route.get('id'),'public_event_sha256':digest,'approval_id':public['payload']['approval_id'],'published_via':publisher}
    if any(details.get(key)!=value for key,value in expected.items()) or publication['artifact_version_id']!=expected['artifact_version_id'] or publication['check_version']!=row['contract_version']:
        return None
    envelope={'schema_version':'1.0','event_id':event_id,'conversation_id':row['conversation_id'],'turn_id':row['turn_id'],'task_id':row['task_id'],'attempt_id':row['attempt_id'],'sequence':row['conversation_sequence'],'kind':'answer.published'}
    if any(public[key]!=value for key,value in envelope.items()) or json.loads(row['internal_payload_json']).get('release_id')!=details['approval_id']:
        return None
    if publisher=='native_publisher_v1':
        if route.get('route_policy')!='native' or route.get('model_family')!='gpt':
            return None
        content=read_artifact(connection,store,expected['artifact_version_id'])
    else:
        if route.get('route_policy')!='claude_en_bridge' or route.get('model_family')!='claude' or public['payload']['language']!='zh-CN':
            return None
        from .answer_publication import validate_translation_release
        translated=dict(revision_id=expected['artifact_version_id'],sha256=details.get('artifact_sha256'),
            source_revision_id=details.get('source_revision_id'),translation_job_id=details.get('translation_job_id'),qa_id=details.get('qa_id'))
        content=validate_translation_release(connection,store,task,translated,historical=historical)
    if hashlib.sha256(content).hexdigest()!=details.get('artifact_sha256') or content.decode('utf-8')!=public['payload']['text']:
        return None
    return public['payload']


def is_historical_answer(connection,event):
    if event['kind']!='answer.published':
        return False
    latest=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=? ORDER BY attempt_number DESC,created_at DESC,attempt_id DESC LIMIT 1',(event['task_id'],)).fetchone()
    if latest is None or latest[0]!=event['attempt_id']:
        return True
    from app.storage.revisions import is_current_revision
    return not is_current_revision(connection,event['task_id'],event['attempt_id'],event['payload']['content_version_id'])
