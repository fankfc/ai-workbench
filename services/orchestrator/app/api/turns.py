import json
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter,HTTPException,Request
from pydantic import Field
from app.contracts.providers import ContractModel, NonEmptyString,ProviderContract,RouteSnapshot
from app.storage.database import transaction

router=APIRouter()

class NewTurn(ContractModel):
    text: NonEmptyString = Field(max_length=65536)
    provider_profile_id: NonEmptyString = Field(max_length=128)
    client_request_id: NonEmptyString = Field(max_length=128)
    domain: Literal['code','paper','document','mixed'] = 'mixed'
    connection_version: NonEmptyString | None = Field(default=None,max_length=128)
    attachment_ids: list[NonEmptyString] = Field(default_factory=list,max_length=20)
    profile_inputs: dict | None = None

class TurnAccepted(ContractModel):
    turn_id:str
    task_id:str

def append_event(connection,turn,task,attempt,kind,payload,contract_version='1.0'):
    sequence=connection.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM outbox_events WHERE task_id=? AND attempt_id=?',(task,attempt)).fetchone()[0]
    conversation=connection.execute('SELECT conversation_id FROM turns WHERE id=?',(turn,)).fetchone()[0]
    cursor=connection.execute('SELECT COALESCE(MAX(conversation_sequence),0)+1 FROM outbox_events WHERE conversation_id=?',(conversation,)).fetchone()[0]
    connection.execute('INSERT INTO outbox_events(event_id,conversation_id,turn_id,task_id,attempt_id,sequence,conversation_sequence,kind,contract_version,internal_payload_json,deduplication_key) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(uuid4().hex,conversation,turn,task,attempt,sequence,cursor,kind,contract_version,json.dumps(payload),f'{task}:{attempt}:{sequence}'))
    connection.execute('UPDATE task_runs SET last_sequence=? WHERE task_id=? AND attempt_id=?',(sequence,task,attempt))

@router.post('/v1/conversations/{conversation}/turns',status_code=202,response_model=TurnAccepted)
def submit_turn(conversation:str,body:NewTurn,request:Request):
    with closing(request.app.state.database.connect()) as connection,transaction(connection):
        if connection.execute('SELECT id FROM conversations WHERE id=?',(conversation,)).fetchone() is None:
            raise HTTPException(404,'会话不存在。')
        existing=connection.execute('SELECT * FROM turns WHERE conversation_id=? AND client_request_id=?',(conversation,body.client_request_id)).fetchone()
        if existing is not None:
            context=connection.execute('SELECT checkpoint_json FROM task_runs WHERE task_id=? ORDER BY attempt_number DESC LIMIT 1',(existing['task_id'],)).fetchone()
            prior_domain=json.loads(context[0]).get('request_domain','mixed') if context else 'mixed'
            prior_inputs=json.loads(context[0]).get('task_profile',{}).get('inputs') if context else None
            prior_attachments=[row[0] for row in connection.execute('SELECT attachment_id FROM turn_attachments WHERE turn_id=? ORDER BY ordinal',(existing['id'],))]
            if (existing['user_text'],existing['provider_profile_id'],prior_domain,prior_attachments,prior_inputs) != (body.text,body.provider_profile_id,body.domain,body.attachment_ids,body.profile_inputs):
                raise HTTPException(409,'请求标识已用于不同内容。')
            if body.connection_version is not None and json.loads(existing['route_snapshot_json']).get('connection_version') != body.connection_version:
                raise HTTPException(409,'请求标识已用于不同的连接版本。')
            return {'turn_id':existing['id'],'task_id':existing['task_id']}
        profile=connection.execute('SELECT * FROM provider_profiles WHERE id=? AND enabled=1',(body.provider_profile_id,)).fetchone()
        if profile is None or profile['family'] not in ('gpt','claude'):
            raise HTTPException(409,'该模型连接尚未验证。')
        if body.connection_version is not None and body.connection_version != profile['connection_version']:
            raise HTTPException(409,'模型连接已改变，请刷新后再发送。')
        checkpoint={'request_domain':body.domain}
        needs_profile_input=False
        if body.profile_inputs is not None:
            from app.profiles.registry import preflight
            try:
                if len(json.dumps(body.profile_inputs,ensure_ascii=False,allow_nan=False).encode('utf-8'))>65536:
                    raise ValueError('PROFILE_INPUT_TOO_LARGE')
                prepared=preflight(body.domain,body.profile_inputs,profile['family'])
            except (ValueError,TypeError):
                raise HTTPException(422,'领域资料、格式或文件引用无效。') from None
            checkpoint['task_profile']={**prepared,'version':prepared['profile_version'],'inputs':body.profile_inputs}
            checkpoint['requested_formats']=body.profile_inputs.get('formats',[])
            needs_profile_input=prepared['status']=='NEEDS_INPUT'
        if len(set(body.attachment_ids)) != len(body.attachment_ids):
            raise HTTPException(422,'文件引用重复。')
        for attachment_id in body.attachment_ids:
            attachment=connection.execute('SELECT * FROM attachments WHERE id=? AND conversation_id=? AND deleted=0 AND status=?',(attachment_id,conversation,'ready')).fetchone()
            if attachment is None:
                raise HTTPException(409,'文件引用不属于当前会话或尚未就绪。')
            request.app.state.blobs.verify(attachment['sha256'])
        turn,task,attempt=uuid4().hex,uuid4().hex,uuid4().hex
        route=dict(id=uuid4().hex,task_id=task,turn_id=turn,attempt_id=attempt,provider_id=profile['id'],model_id=profile['model_id'],model_family=profile['family'],adapter_id=profile['adapter'],identity_status=profile['identity_status'],identity_source=profile['identity_source'],connection_version=profile['connection_version'],policy_version='1.0',route_policy='native' if profile['family']=='gpt' else 'claude_en_bridge',locked_at=datetime.now(timezone.utc).isoformat())
        if request.app.state.settings.provider_mode=='real':
            if profile['id'] not in request.app.state.provider_registry:
                raise HTTPException(409,'该模型连接尚未完成运行能力验证。')
            try:
                provider=ProviderContract.model_validate_json(profile['provider_json'])
                RouteSnapshot.model_validate(route).require_executable(provider)
            except ValueError:
                raise HTTPException(409,'该模型连接尚未验证。') from None
            if profile['family']=='claude':
                raise HTTPException(409,'任务所需的语言处理尚未就绪。')
        else:
            route['test_only']=True
        serialized=json.dumps(route,sort_keys=True)
        connection.execute('INSERT INTO turns(id,conversation_id,task_id,provider_profile_id,client_request_id,user_text,route_snapshot_json) VALUES (?,?,?,?,?,?,?)',(turn,conversation,task,profile['id'],body.client_request_id,body.text,serialized))
        for ordinal,attachment_id in enumerate(body.attachment_ids):
            connection.execute('INSERT INTO turn_attachments(turn_id,attachment_id,ordinal) VALUES(?,?,?)',(turn,attachment_id,ordinal))
        connection.execute("INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,state,route_snapshot_json,checkpoint_json) VALUES (?,?,?,?,'RECEIVED',?,?)",(task,attempt,turn,profile['id'],serialized,json.dumps(checkpoint)))
        if profile['identity_status']=='verified':
            from app.translation.router import persist_snapshot
            persist_snapshot(connection,RouteSnapshot.model_validate({key:value for key,value in route.items() if key!='test_only'}))
        append_event(connection,turn,task,attempt,'message.accepted',{})
        if needs_profile_input:
            connection.execute("UPDATE task_runs SET state='NEEDS_INPUT' WHERE task_id=? AND attempt_id=?",(task,attempt))
            append_event(connection,turn,task,attempt,'task.state_changed',{'expected_state':'RECEIVED','new_state':'NEEDS_INPUT','contract_version':'1.0'})
            append_event(connection,turn,task,attempt,'input.required',{'prompt_code':'missing_input'})
        else:
            append_event(connection,turn,task,attempt,'response.pending',{})
        connection.execute("UPDATE conversations SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(conversation,))
    return {'turn_id':turn,'task_id':task}
