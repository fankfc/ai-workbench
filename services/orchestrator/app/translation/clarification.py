"""A-owned complete clarification, translated and frozen before public use."""
from contextlib import closing
import hashlib
import json
import unicodedata
from uuid import uuid4
from app.contracts.events import PublicEvent
from app.contracts.providers import AgentRequestRecord,ProviderContract
from app.runtime.outbox import enqueue_event
from app.runtime.state_machine import checkpoint_for,require_current_attempt
from app.storage.blobs import BlobStore
from app.storage.database import Database,transaction
from .segments import segment_document
from .protection import protect,MARKER

def _json(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def _sha(raw): return hashlib.sha256(raw).hexdigest()

def question(response):
    if not isinstance(response,dict) or response.get('decision')!='NEED_EVIDENCE': raise ValueError('A_CLARIFICATION_DECISION_REQUIRED')
    text=response.get('clarification_text')
    if not isinstance(text,str) or not text.strip() or len(text.encode())>65536: raise ValueError('COMPLETE_A_CLARIFICATION_REQUIRED')
    return text

def read_source(connection,store,task,step_id,origin):
    route=json.loads(task['route_snapshot_json'])
    step=connection.execute("SELECT * FROM steps WHERE id=? AND task_id=? AND attempt_id=? AND role='A' AND state='COMPLETED'",(step_id,task['task_id'],task['attempt_id'])).fetchone()
    if step is None or step['provider_profile_id']!=route['provider_id'] or step['contract_version']!=task['contract_version']: raise ValueError('A_CLARIFICATION_STEP_REQUIRED')
    if origin=='workflow_review':
        request=AgentRequestRecord.model_validate_json(step['request_json'])
        if (request.task_id,request.attempt_id,request.role,request.identity.model_id,request.identity.adapter,request.identity.family.value)!=(task['task_id'],task['attempt_id'],'A',route['model_id'],route['adapter_id'],route['model_family']): raise ValueError('A_CLARIFICATION_IDENTITY_MISMATCH')
        events=[]
        for row in connection.execute("SELECT internal_payload_json FROM outbox_events WHERE task_id=? AND attempt_id=? AND kind='workflow.provider_event' ORDER BY sequence",(task['task_id'],task['attempt_id'])):
            event=json.loads(row[0])
            if event.get('step_id')==step_id: events.append(event)
        seq=[e['provider_sequence'] for e in events]
        reviews=[e for e in events if e['kind']=='review.decision']; completed=[e for e in events if e['kind'] in ('model.completed','provider.completed')]
        if not events or seq!=sorted(set(seq)) or len(reviews)!=1 or len(completed)!=1 or reviews[0]['provider_sequence']>=completed[0]['provider_sequence'] or any(e['kind']=='provider.error' for e in events): raise ValueError('A_CLARIFICATION_RESPONSE_NOT_COMPLETE')
        if completed[0]['payload'].get('reported_complete') is False or completed[0]['payload'].get('finish_reason','stop') not in ('stop','end_turn','completed'): raise ValueError('A_CLARIFICATION_RESPONSE_NOT_COMPLETE')
        response=reviews[0]['payload']; raw=_json(events).encode()
        for key,value in dict(task_id=task['task_id'],attempt_id=task['attempt_id'],contract_version=task['contract_version']).items():
            if key in response and response[key]!=value: raise ValueError('A_CLARIFICATION_SCOPE_MISMATCH')
    elif origin=='planning':
        receipt=connection.execute("SELECT * FROM checks WHERE id=? AND task_id=? AND attempt_id=? AND check_kind='A.planning_capture' AND result='pass'",('planning-capture-'+step_id,task['task_id'],task['attempt_id'])).fetchone()
        if receipt is None: raise ValueError('A_PLANNING_CAPTURE_REQUIRED')
        detail=json.loads(receipt['details_json']); request=json.loads(step['request_json'])
        provider=ProviderContract.model_validate(detail['observed_provider']); provider.require_executable()
        expected=(task['task_id'],task['attempt_id'],step_id,route['provider_id'],route['model_id'],route['adapter_id'],route['model_family'])
        if (request.get('task_id'),request.get('attempt_id'),request.get('request_id'),provider.provider_id,provider.identity.model_id,provider.identity.adapter,provider.identity.family.value)!=expected or request.get('phase')!='planning': raise ValueError('A_PLANNING_CAPTURE_IDENTITY_MISMATCH')
        remote=json.loads(step['checkpoint_json']).get('remote_execution',{})
        if detail['external_request_id']!=remote.get('external_request_id') or detail['external_execution_id']!=step['external_execution_id'] or remote.get('status')!='completed': raise ValueError('A_PLANNING_CAPTURE_BINDING_MISMATCH')
        raw=store.read(detail['capture_sha256']); response=json.loads(raw)
        if _sha(raw)!=detail['capture_sha256']: raise ValueError('A_PLANNING_CAPTURE_BYTES_CHANGED')
        for key,value in dict(task_id=task['task_id'],attempt_id=task['attempt_id'],route_snapshot_id=route['id']).items():
            if key in response and response[key]!=value: raise ValueError('A_CLARIFICATION_SCOPE_MISMATCH')
    else: raise ValueError('A_CLARIFICATION_ORIGIN_REQUIRED')
    text=question(response); source=text.encode()
    # Claude source is an English A response. Protected literals retain their
    # original script, but unprotected natural language cannot masquerade as en.
    if route['model_family']=='claude':
        natural=''.join(MARKER.sub('',protect(s).text) for s in segment_document(text))
        if any(unicodedata.category(c).startswith('L') and 'LATIN' not in unicodedata.name(c,'') for c in natural): raise ValueError('A_CLARIFICATION_ENGLISH_REQUIRED')
    return text,dict(step_id=step_id,origin=origin,source_sha256=_sha(source),raw_response_sha256=_sha(raw),route_snapshot_id=route['id']),raw

def validate_publication(connection,store,event_id,*,historical=True):
    event=connection.execute("SELECT * FROM outbox_events WHERE event_id=? AND kind='input.required'",(event_id,)).fetchone()
    proof=connection.execute("SELECT * FROM checks WHERE id=? AND check_kind='clarification.publication' AND result='pass'",('clarification-publication-'+event_id,)).fetchone()
    if event is None or proof is None or event['public_event_json'] is None: raise ValueError('CLARIFICATION_PUBLICATION_REQUIRED')
    task=connection.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?',(event['task_id'],event['attempt_id'])).fetchone()
    detail=json.loads(proof['details_json']); public=PublicEvent.model_validate_json(event['public_event_json']).model_dump(mode='json')
    if (proof['task_id'],proof['attempt_id'],proof['check_version'])!=(event['task_id'],event['attempt_id'],event['contract_version']) or detail.get('published_via')!='clarification_publisher_v1' or detail.get('event_id')!=event_id or detail.get('public_event_sha256')!=_sha(_json(public).encode()): raise ValueError('CLARIFICATION_PUBLICATION_BINDING_MISMATCH')
    expected=dict(event_id=event_id,task_id=event['task_id'],attempt_id=event['attempt_id'],turn_id=event['turn_id'],conversation_id=event['conversation_id'],sequence=event['conversation_sequence'],kind='input.required')
    if any(public.get(k)!=v for k,v in expected.items()) or json.loads(event['internal_payload_json'])!={'clarification_release_id':detail['release_id']}: raise ValueError('CLARIFICATION_ENVELOPE_MISMATCH')
    source,source_proof,_=read_source(connection,store,task,detail['source']['step_id'],detail['source']['origin'])
    if source_proof!=detail['source'] or store.read(detail['source']['source_sha256']).decode()!=source or _sha(store.read(detail['source']['raw_response_sha256']))!=detail['source']['raw_response_sha256']: raise ValueError('CLARIFICATION_SOURCE_CHANGED')
    target=store.read(detail['target_sha256'])
    route=json.loads(task['route_snapshot_json'])
    if route['model_family']=='claude':
        from .quality import has_english_sentence_copy
        natural_source=[]; natural_target=target.decode()
        for segment in segment_document(source):
            block=protect(segment); natural_source.append(MARKER.sub(' ',block.text))
            for span in block.spans: natural_target=natural_target.replace(span.raw,' ',1)
        if has_english_sentence_copy(''.join(natural_source),natural_target): raise ValueError('CLAUDE_UNTRANSLATED_QUESTION_NOT_PUBLIC')
        job=connection.execute('SELECT * FROM translation_jobs WHERE id=? AND task_id=? AND attempt_id=?',(detail['job_id'],task['task_id'],task['attempt_id'])).fetchone()
        qa=connection.execute("SELECT * FROM checks WHERE id=? AND job_id=? AND check_kind='translation.qa' AND result='pass'",(detail['qa_id'],detail['job_id'])).fetchone()
        if job is None or qa is None or job['status'] not in (('READY','STALE') if historical else ('READY',)) or job['route_snapshot_id']!=route['id'] or job['source_sha256']!=source_proof['source_sha256'] or job['target_sha256']!=detail['target_sha256'] or job['qa_id']!=detail['qa_id']: raise ValueError('CLARIFICATION_TRANSLATION_BINDING_REQUIRED')
        q=json.loads(qa['details_json']); spec=json.loads(job['job_json'])
        if ((qa['task_id'],qa['attempt_id'],qa['check_version'])!=(task['task_id'],task['attempt_id'],q.get('check_version'))
                or q.get('job_id')!=job['id'] or spec['purpose']!='clarification' or spec['source_language']!='en' or spec['target_language']!='zh-CN'
                or job['context_sha256']!=_sha(_json(source_proof).encode()) or job['source_locator']!='A:'+source_proof['step_id']
                or any(q.get(k)!='pass' for k in ('coverage_result','protected_span_result','numeric_entity_result')) or q.get('severity') in ('major','critical') or any(f.get('severity') in ('major','critical') for f in q.get('semantic_findings',[])) or (q.get('stale') and not historical)): raise ValueError('CLARIFICATION_QA_REQUIRED')
        if public['payload']['language']!='zh-CN': raise ValueError('CLAUDE_ENGLISH_CLARIFICATION_NOT_PUBLIC')
    elif route['model_family']=='gpt':
        if target!=source.encode() or detail.get('job_id') is not None: raise ValueError('GPT_CLARIFICATION_MUST_BE_NATIVE')
    else: raise ValueError('CLARIFICATION_ROUTE_UNVERIFIED')
    if target.decode()!=public['payload']['text'] or public['payload']['prompt_id']!=detail['release_id']: raise ValueError('CLARIFICATION_TARGET_CHANGED')
    if not historical:
        require_current_attempt(connection,task['task_id'],task['attempt_id'])
        if task['cancel_requested'] or checkpoint_for(task).get('identity_changed') or connection.execute('SELECT 1 FROM route_invalidations WHERE route_snapshot_id=?',(route['id'],)).fetchone(): raise ValueError('CLARIFICATION_CURRENT_FENCE')
    return public['payload']

class ClarificationPublisher:
    def __init__(self,database_path,service=None):
        self.database=Database(database_path); self.store=BlobStore(self.database.path.parent/'blobs'); self.service=service
    async def publish(self,task_id,attempt_id,step_id,*,origin):
        with closing(self.database.connect()) as connection:
            task=require_current_attempt(connection,task_id,attempt_id); route=json.loads(task['route_snapshot_json'])
            if task['cancel_requested'] or checkpoint_for(task).get('identity_changed') or task['state'] not in ('REVIEWING','PLANNING','NEEDS_INPUT'): raise ValueError('CLARIFICATION_STATE_FENCE')
            source,proof,raw=read_source(connection,self.store,task,step_id,origin)
        self.store.put(source.encode()); self.store.put(raw)
        job_id=qa_id=None; target=source; language='zh-CN' if any('\u3400'<=c<='\u9fff' for c in source) else 'en'
        if route['model_family']=='claude':
            if self.service is None: raise ValueError('CLARIFICATION_TRANSLATOR_REQUIRED')
            result=await self.service.translate(task_id=task_id,attempt_id=attempt_id,source=source,source_ref=self.store.uri_for(proof['source_sha256']),
                source_language='en',target_language='zh-CN',purpose='clarification',source_locator='A:'+step_id,
                context_sha256=_sha(_json(proof).encode()))
            if result.status!='READY': raise ValueError('CLARIFICATION_TRANSLATION_NOT_READY')
            target=result.text; language='zh-CN'; job_id=result.job_id; qa_id=result.qa_id
        target_hash=self.store.put(target.encode()).sha256
        with closing(self.database.connect()) as connection,transaction(connection):
            task=require_current_attempt(connection,task_id,attempt_id); checkpoint=checkpoint_for(task)
            if task['cancel_requested'] or checkpoint.get('identity_changed') or task['state'] not in ('REVIEWING','PLANNING','NEEDS_INPUT') or connection.execute('SELECT 1 FROM route_invalidations WHERE route_snapshot_id=?',(route['id'],)).fetchone(): raise ValueError('CLARIFICATION_STATE_FENCE')
            if read_source(connection,self.store,task,step_id,origin)[1]!=proof: raise ValueError('A_CLARIFICATION_SOURCE_CHANGED')
            release='clarification-'+step_id; event_id='clarification-event-'+step_id
            existing=connection.execute('SELECT 1 FROM outbox_events WHERE event_id=?',(event_id,)).fetchone()
            if existing:
                validate_publication(connection,self.store,event_id,historical=False); return event_id
            if task['state']!='NEEDS_INPUT':
                connection.execute("UPDATE task_runs SET state='NEEDS_INPUT' WHERE task_id=? AND attempt_id=?",(task_id,attempt_id))
                enqueue_event(connection,task_id,attempt_id,'task.state_changed',dict(expected_state=task['state'],new_state='NEEDS_INPUT',contract_version=task['contract_version']),deduplication_key='clarification-state:'+step_id)
            event=enqueue_event(connection,task_id,attempt_id,'input.required',{'clarification_release_id':release},public_payload=dict(prompt_id=release,text=target,language=language),event_id=event_id,deduplication_key='clarification-public:'+step_id)
            public=PublicEvent.model_validate_json(event['public_event_json']).model_dump(mode='json')
            detail=dict(event_id=event_id,release_id=release,published_via='clarification_publisher_v1',source=proof,target_sha256=target_hash,job_id=job_id,qa_id=qa_id,public_event_sha256=_sha(_json(public).encode()))
            connection.execute("INSERT INTO checks(id,task_id,attempt_id,check_kind,result,check_version,details_json) VALUES(?,?,?,'clarification.publication','pass',?,?)",('clarification-publication-'+event_id,task_id,attempt_id,task['contract_version'],_json(detail)))
            checkpoint['clarification_release']=detail
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task_id,attempt_id))
            validate_publication(connection,self.store,event_id,historical=False)
            # Preserve A's complete English question beside the approved
            # Chinese text; a follow-up must never translate that Chinese copy
            # back into a different supposed A original.
            english_hash=proof['source_sha256'] if route['model_family']=='claude' or language=='en' else None
            connection.execute('INSERT INTO bilingual_history(id,conversation_id,task_id,turn_id,source_role,language,raw_content_ref,content_sha256,parent_message_id,route_snapshot_id,visibility,english_ref,english_sha256,job_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (release,event['conversation_id'],task_id,task['turn_id'],'assistant',language,self.store.uri_for(target_hash),target_hash,step_id,route['id'],'user',self.store.uri_for(english_hash) if english_hash else None,english_hash,job_id))
        return event_id
