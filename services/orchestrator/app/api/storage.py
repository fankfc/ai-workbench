from contextlib import closing
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from app.contracts.providers import ContractModel, Sha256
from app.storage.database import transaction
from app.storage.cleanup import inventory, preview, cleanup
from app.storage.relocation import prepare, execute, RelocationError
from uuid import uuid4

router = APIRouter()


class CleanupRequest(ContractModel):
    version: str = Field(min_length=1, max_length=128)
    sha256s: list[Sha256] = Field(max_length=10000)


class RelocationPreview(ContractModel):
    destination: str = Field(min_length=1, max_length=32768)


class RelocationRequest(ContractModel):
    version: str = Field(min_length=1, max_length=128)


@router.get('/v1/storage')
def get_storage(request: Request):
    with closing(request.app.state.database.connect()) as connection:
        current = inventory(connection, request.app.state.blobs)
    return dict(version=current['version'], blob_count=len(current['files']),
        used_bytes=sum(row['size_bytes'] for row in current['files']),
        referenced_bytes=sum(row['size_bytes'] for row in current['files'] if row['referenced']),
        active_tasks=current['active'], relocation_available=True,
        relocation_pending=request.app.state.storage_frozen)


@router.post('/v1/storage/cleanup-preview')
def cleanup_preview(request: Request):
    with closing(request.app.state.database.connect()) as connection:
        return preview(connection, request.app.state.blobs)


@router.post('/v1/storage/cleanup')
def run_cleanup(body: CleanupRequest, request: Request):
    with closing(request.app.state.database.connect()) as connection, transaction(connection):
        try:
            return cleanup(connection, request.app.state.blobs, body.version, body.sha256s)
        except ValueError:
            raise HTTPException(409, '清理条件已改变，请重新预览。') from None


@router.post('/v1/storage/relocation-preview')
def relocation_preview(body: RelocationPreview, request: Request):
    try:
        with closing(request.app.state.database.connect()) as connection:
            plan = prepare(connection, request.app.state.settings.data_root, body.destination)
    except RelocationError as error:
        status = 422 if str(error) in {'DESTINATION_MUST_BE_ABSOLUTE', 'DESTINATION_LINK_FORBIDDEN', 'DESTINATION_OVERLAPS_SOURCE'} else 409
        raise HTTPException(status, '目录不满足迁移条件，原目录保留。') from None
    except OSError:
        raise HTTPException(409, '目标目录不可写，原目录保留。') from None
    version = uuid4().hex
    request.app.state.relocation_plan = dict(plan, token=version)
    return dict(version=version, ready=True, files=len(plan['manifest']['files']),
        required_bytes=plan['manifest']['required_bytes'], source_retained=True)


@router.post('/v1/storage/relocate')
def relocate(body: RelocationRequest, request: Request):
    plan = request.app.state.relocation_plan
    if not plan or body.version != plan['token']:
        raise HTTPException(409, '迁移预检已失效，请重新预检。')
    request.app.state.storage_frozen = True
    try:
        result = execute(request.app.state.database, plan)
    except (RelocationError, OSError):
        request.app.state.storage_frozen = False
        request.app.state.relocation_plan = None
        raise HTTPException(409, '迁移未完成，原目录继续使用。') from None
    # Keep the old process read-only until its private main-process owner restarts.
    request.app.state.relocation_result = result
    return result
