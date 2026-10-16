"""Authenticated published bundle bytes, scoped by cid/bid/aid, never paths."""
from contextlib import closing
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.documents.publish import bundle_card, CONTENT_TYPES
from app.storage.blobs import read_artifact

router=APIRouter()


def _no_query(request):
    if request.query_params: raise HTTPException(422,'该接口不接受路径或额外参数。')


def _conversation(c,cid):
    if c.execute('SELECT id FROM conversations WHERE id=?',(cid,)).fetchone() is None: raise HTTPException(404,'会话不存在。')


def _published(c,store,cid,bid):
    _conversation(c,cid)
    row=c.execute("SELECT * FROM delivery_bundles WHERE id=? AND conversation_id=? AND state='PUBLISHED'",(bid,cid)).fetchone()
    if row is None: raise HTTPException(404,'交付文件不存在或尚未发布。')
    try: return row,bundle_card(c,store,row)
    except (ValueError,OSError): raise HTTPException(409,'交付文件校验失败，已停止提供该版本。') from None


@router.get('/v1/conversations/{cid}/bundles')
def list_bundles(cid:str,request:Request):
    _no_query(request)
    with closing(request.app.state.database.connect()) as c:
        _conversation(c,cid); items=[]
        for row in c.execute("SELECT * FROM delivery_bundles WHERE conversation_id=? AND state='PUBLISHED' ORDER BY published_at,created_at,id",(cid,)):
            try: items.append(bundle_card(c,request.app.state.blobs,row))
            except (ValueError,OSError): continue
        return {'items':items}


def _file(cid,bid,aid,request,preview):
    _no_query(request); store=request.app.state.blobs
    with closing(request.app.state.database.connect()) as c:
        row,card=_published(c,store,cid,bid)
        member=c.execute('SELECT * FROM delivery_bundle_artifacts WHERE bundle_id=? AND artifact_id=?',(bid,aid)).fetchone()
        if member is None: raise HTTPException(404,'该文件不属于当前交付版本。')
        selected=aid; format=member['format']
        if preview and format=='docx':
            if not member['preview_artifact_id']: raise HTTPException(409,'此 Word 文件的预览暂不可用。')
            selected=member['preview_artifact_id']; format='pdf'
        if preview and format not in ('pdf','markdown','png'): raise HTTPException(409,'该格式暂不支持预览。')
        try:
            data=read_artifact(c,store,selected)
            artifact=c.execute('SELECT byte_sha256 FROM artifact_revisions WHERE id=?',(selected,)).fetchone()
        except (ValueError,OSError): raise HTTPException(409,'交付文件校验失败，已停止提供该版本。') from None
        content_type='text/plain; charset=utf-8' if preview and format=='markdown' else CONTENT_TYPES[format]
        disposition='inline' if preview else 'attachment'
        headers={'X-Content-SHA256':artifact['byte_sha256'],'ETag':'"'+artifact['byte_sha256']+'"',
            'X-Content-Type-Options':'nosniff','Cache-Control':'private, no-store',
            'Content-Security-Policy':"default-src 'none'; sandbox",'Content-Disposition':disposition+"; filename*=UTF-8''"+quote(member['file_name'])}
        return Response(data,media_type=content_type,headers=headers)


@router.get('/v1/conversations/{cid}/bundles/{bid}/artifacts/{aid}/download')
def download(cid:str,bid:str,aid:str,request:Request): return _file(cid,bid,aid,request,False)


@router.get('/v1/conversations/{cid}/bundles/{bid}/artifacts/{aid}/preview')
def preview(cid:str,bid:str,aid:str,request:Request): return _file(cid,bid,aid,request,True)
