from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field
from app.contracts.providers import ContractModel, NonEmptyString
from app.api.public_events import public_events

router = APIRouter()

class NewConversation(ContractModel):
    title: NonEmptyString = Field(max_length=200)

class ConversationCreated(ContractModel):
    id: str

class ConversationItem(ContractModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    pinned: bool = False
    archived: bool = False

class ConversationPatch(ContractModel):
    title: NonEmptyString | None = Field(default=None, max_length=200)
    pinned: bool | None = None
    archived: bool | None = None

class ConversationsPage(ContractModel):
    items: list[ConversationItem]
    next_offset: int | None

class PublicMessage(ContractModel):
    id: str
    turn_id: str
    kind: str
    text: str
    language: str
    attempt_id: str
    content_version_id: str | None
    historical: bool

class MessagesPage(ContractModel):
    items: list[PublicMessage]

def require_conversation(connection, conversation):
    if connection.execute('SELECT id FROM conversations WHERE id=?',(conversation,)).fetchone() is None:
        raise HTTPException(404,'会话不存在。')

@router.post('/v1/conversations',status_code=201,response_model=ConversationCreated)
def create_conversation(body:NewConversation,request:Request):
    from uuid import uuid4
    from contextlib import closing
    with closing(request.app.state.database.connect()) as connection:
        identity=uuid4().hex
        connection.execute('INSERT INTO conversations(id,title) VALUES (?,?)',(identity,body.title))
    return {'id':identity}

@router.get('/v1/conversations',response_model=ConversationsPage)
def list_conversations(request:Request,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),query:str=Query('',max_length=200),archived:bool=False):
    from contextlib import closing
    with closing(request.app.state.database.connect()) as connection:
        literal=query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        rows=connection.execute("SELECT id,title,created_at,updated_at,pinned,archived FROM conversations WHERE archived=? AND title LIKE ? ESCAPE '\\' ORDER BY pinned DESC,updated_at DESC,id LIMIT ? OFFSET ?",(int(archived),'%'+literal+'%',limit+1,offset)).fetchall()
    return {'items':[dict(row) for row in rows[:limit]],'next_offset':offset+limit if len(rows)>limit else None}

@router.patch('/v1/conversations/{conversation}',response_model=ConversationItem)
def edit_conversation(conversation:str,body:ConversationPatch,request:Request):
    from contextlib import closing
    from app.storage.database import transaction
    changes=body.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422,'请提供有效的会话设置。')
    with closing(request.app.state.database.connect()) as connection,transaction(connection):
        require_conversation(connection,conversation)
        connection.execute('UPDATE conversations SET '+','.join(key+'=?' for key in changes)+",updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(*changes.values(),conversation))
        return dict(connection.execute('SELECT id,title,created_at,updated_at,pinned,archived FROM conversations WHERE id=?',(conversation,)).fetchone())

@router.get('/v1/conversations/{conversation}/messages',response_model=MessagesPage)
def messages(conversation:str,request:Request):
    from contextlib import closing
    if request.query_params:
        raise HTTPException(400,'不支持该查询参数。')
    with closing(request.app.state.database.connect()) as connection:
        require_conversation(connection,conversation)
        events=public_events(connection,request.app.state.blobs,conversation)
        from app.runtime.public_projection import is_historical_answer
        items=[{'id':event['payload'].get('message_id',event['event_id']),'turn_id':event['turn_id'],'kind':event['kind'],'text':event['payload']['text'],'language':event['payload']['language'],'attempt_id':event['attempt_id'],'content_version_id':event['payload'].get('content_version_id'),'historical':is_historical_answer(connection,event)} for event in events if 'text' in event['payload']]
    return {'items':items}

@router.get('/v1/conversations/{conversation}/events',responses={200:{'content':{'text/event-stream':{}}}})
def events(conversation:str,request:Request,after_seq:int=Query(0,ge=0)):
    from contextlib import closing
    import json
    from fastapi.responses import StreamingResponse
    if set(request.query_params)-{'after_seq'}:
        raise HTTPException(400,'不支持该查询参数。')
    with closing(request.app.state.database.connect()) as connection:
        require_conversation(connection,conversation)
        projected=public_events(connection,request.app.state.blobs,conversation,after_seq)
    def stream():
        for event in projected:
            yield f"id: {event['sequence']}\nevent: {event['kind']}\ndata: {json.dumps(event,ensure_ascii=False,separators=(',',':'))}\n\n"
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
