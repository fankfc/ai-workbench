from contextlib import closing
import json
from fastapi import APIRouter,HTTPException,Request
from app.contracts.providers import ContractModel
from app.storage.database import transaction
from app.api.turns import append_event

router=APIRouter()

class TaskStatus(ContractModel):
    task_id:str
    status:str
    cancel_requested:bool
    external_stop_confirmed:bool | None
    cancel_pending_remote:bool

def public_status(row):
    state=row['state']
    status='cancel_pending_remote' if row['cancel_pending_remote'] else ('cancelled' if state=='CANCELLED' else 'completed' if state=='PUBLISHED' else 'failed' if state=='FAILED' else 'needs_input' if state=='NEEDS_INPUT' else 'blocked' if state in ('BLOCKED','PAUSED') else 'pending')
    return dict(task_id=row['task_id'],status=status,cancel_requested=bool(row['cancel_requested']),external_stop_confirmed=None if row['external_stop_confirmed'] is None else bool(row['external_stop_confirmed']),cancel_pending_remote=bool(row['cancel_pending_remote']))

def current_task(connection,task):
    row=connection.execute('SELECT * FROM task_runs WHERE task_id=? ORDER BY attempt_number DESC,created_at DESC,attempt_id DESC LIMIT 1',(task,)).fetchone()
    if row is None:
        raise HTTPException(404,'任务不存在。')
    return row

@router.get('/v1/tasks/{task}',response_model=TaskStatus)
def get_task(task:str,request:Request):
    with closing(request.app.state.database.connect()) as connection:
        return public_status(current_task(connection,task))

@router.post('/v1/tasks/{task}/cancel',status_code=202,response_model=TaskStatus)
def cancel_task(task:str,request:Request):
    with closing(request.app.state.database.connect()) as connection,transaction(connection):
        row=current_task(connection,task)
        if row['state']=='PUBLISHED':
            raise HTTPException(409,'任务已完成。')
        if not row['cancel_requested']:
            checkpoint=json.loads(row['checkpoint_json'])
            remote=checkpoint.get('active_external_request',{})
            accepted=remote.get('accepted') is True
            possible=remote.get('submission_possible') is True and remote.get('status')=='unknown'
            pending=bool(accepted or possible or row['external_execution_id'] or row['external_request_id']) and row['external_stop_confirmed']!=1
            connection.execute("UPDATE task_runs SET state='CANCELLED',cancel_requested=1,cancel_pending_remote=?,lease_owner=NULL,lease_expires_at=NULL WHERE task_id=? AND attempt_id=?",(int(pending),task,row['attempt_id']))
            append_event(connection,row['turn_id'],task,row['attempt_id'],'request.cancelled',{},row['contract_version'])
        return public_status(current_task(connection,task))
