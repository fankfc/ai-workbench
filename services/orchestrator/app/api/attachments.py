"""Immutable attachments scoped by a conversation; no paths accepted from renderer."""
from contextlib import closing
import re
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from app.storage.database import transaction
from .conversations import require_conversation

router = APIRouter()
MAX_BYTES = 20 * 1024 * 1024


def public_attachment(row):
    return dict(id=row['id'], name=row['name'], size_bytes=row['size_bytes'], sha256=row['sha256'], status=row['status'])


@router.post('/v1/conversations/{conversation}/attachments', status_code=201)
async def upload_attachment(conversation: str, request: Request):
    name = unquote(request.headers.get('X-Filename', ''))
    if (not name or len(name) > 200 or any(character in name for character in '/\\:')
            or re.search(r'[\x00-\x1f]', name) or name.endswith(('.', ' '))
            or name.rsplit('.', 1)[-1].lower() not in {'md', 'txt', 'csv', 'json', 'pdf', 'docx'}):
        raise HTTPException(422, '请选择支持的文档文件。')
    if request.headers.get('Content-Type', '').split(';')[0] != 'application/octet-stream':
        raise HTTPException(422, '文件上传格式不受支持。')
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(413, '文件超过 20 MB 上限。')
        chunks.append(chunk)
    content = b''.join(chunks)
    if not content:
        raise HTTPException(422, '文件为空。')
    if name.rsplit('.', 1)[-1].lower() in {'md', 'txt', 'csv', 'json'}:
        try:
            content.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise HTTPException(422, '文本文件需为 UTF-8 编码。') from None
    elif name.lower().endswith('.pdf') and not content.startswith(b'%PDF-'):
        raise HTTPException(422, 'PDF 文件无效。')
    elif name.lower().endswith('.docx') and not content.startswith(b'PK'):
        raise HTTPException(422, 'Word 文件无效。')
    with closing(request.app.state.database.connect()) as connection, transaction(connection):
        require_conversation(connection, conversation)
        blob = request.app.state.blobs.put(content)
        identity = uuid4().hex
        connection.execute('INSERT INTO attachments(id,conversation_id,name,sha256,size_bytes,status) VALUES(?,?,?,?,?,?)',
                           (identity, conversation, name, blob.sha256, size, 'ready'))
        return dict(id=identity, name=name, sha256=blob.sha256, size_bytes=size, status='ready')


@router.get('/v1/conversations/{conversation}/attachments')
def list_attachments(conversation: str, request: Request):
    with closing(request.app.state.database.connect()) as connection:
        require_conversation(connection, conversation)
        return dict(items=[public_attachment(row) for row in connection.execute('SELECT * FROM attachments WHERE conversation_id=? AND deleted=0 ORDER BY created_at,id', (conversation,))])


@router.delete('/v1/conversations/{conversation}/attachments/{attachment}')
def remove_attachment(conversation: str, attachment: str, request: Request):
    with closing(request.app.state.database.connect()) as connection, transaction(connection):
        row = connection.execute('SELECT * FROM attachments WHERE id=? AND conversation_id=? AND deleted=0', (attachment, conversation)).fetchone()
        if row is None:
            raise HTTPException(404, '文件引用不存在。')
        if connection.execute('SELECT 1 FROM turn_attachments WHERE attachment_id=?', (attachment,)).fetchone():
            raise HTTPException(409, '文件已用于任务，不能移除原始引用。')
        connection.execute('UPDATE attachments SET deleted=1 WHERE id=?', (attachment,))
    return dict(removed=True)
