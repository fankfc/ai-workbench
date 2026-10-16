"""Authenticated opaque backup references; renderer paths are never accepted."""
from pathlib import Path
import hashlib
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Request, Response
from app.contracts.providers import ContractModel
from app.storage.backup import (BackupError, MAX_BYTES, create_backup, validate_backup,
                                export_backup, import_backup)
from app.storage.restore import restore_backup
from app.storage.directory_commit import DirectoryCommitBusy

router = APIRouter()


class EmptyRequest(ContractModel):
    pass


def _staging(request):
    source = request.app.state.settings.data_root
    return source.parent / ('.' + source.name + '-backups')


def _register(request, path):
    report = validate_backup(path)
    identity = uuid4().hex
    request.app.state.backup_refs[identity] = Path(path)
    return dict(backup_id=identity, verified=True, schema_version=report['schema_version'],
        app_version=report['app_version'], files_verified=report['files_verified'],
        size_bytes=report['size_bytes'], credentials_included=False, reconnect_required=True)


def _lookup(request, identity):
    path = request.app.state.backup_refs.get(identity)
    if path is None: raise HTTPException(404, '备份选择已失效，请重新选择。')
    return path


@router.post('/v1/backups', status_code=201)
def create(body: EmptyRequest, request: Request):
    try: return _register(request, create_backup(request.app.state.settings.data_root, _staging(request)))
    except DirectoryCommitBusy: raise HTTPException(409, '备份文件暂被占用，原数据保留，请稍后重试。') from None
    except (ValueError, OSError): raise HTTPException(409, '备份未完成。请暂停运行任务并检查存储空间，原数据保留。') from None


@router.get('/v1/backups/{backup_id}/download')
def download(backup_id: str, request: Request):
    try: content = export_backup(_lookup(request, backup_id))
    except (ValueError, OSError): raise HTTPException(409, '备份校验失败，未导出。') from None
    return Response(content, media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="workbench-backup.zip"', 'X-Content-SHA256': hashlib.sha256(content).hexdigest()})


@router.post('/v1/backups/import', status_code=201)
async def upload(request: Request):
    if request.headers.get('Content-Type', '').split(';')[0] != 'application/zip':
        raise HTTPException(422, '请选择工作台备份 ZIP 文件。')
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES: raise HTTPException(413, '备份超过 256 MB 上限。')
        chunks.append(chunk)
    try: return _register(request, import_backup(b''.join(chunks), _staging(request)))
    except DirectoryCommitBusy: raise HTTPException(422, '备份导入暂因文件占用未完成，原数据保留，请稍后重试。') from None
    except (ValueError, OSError): raise HTTPException(422, '备份内容、路径、配对或版本校验失败，原数据保留。') from None


@router.post('/v1/backups/{backup_id}/restore')
def restore(backup_id: str, body: EmptyRequest, request: Request):
    path = _lookup(request, backup_id)
    request.app.state.storage_frozen = True
    try:
        result = restore_backup(path, request.app.state.settings.data_root)
    except DirectoryCommitBusy:
        request.app.state.storage_frozen = False
        raise HTTPException(409, '恢复文件暂被占用，原目录继续使用，请稍后重试。') from None
    except (ValueError, OSError):
        request.app.state.storage_frozen = False
        raise HTTPException(409, '恢复未完成，原目录继续使用。请检查任务状态、备份与可用空间。') from None
    request.app.state.backup_restore_result = result
    return result
