import secrets
import os
import asyncio
import inspect
from contextlib import closing, asynccontextmanager, suppress
from fastapi import FastAPI,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.config import AppSettings
from app.contracts.providers import ContractModel,NonEmptyString
from app.storage.database import Database
from app.storage.migrations import migrate
from app.storage.blobs import BlobStore
from . import conversations,turns,tasks

class ApiError(ContractModel):
    detail: NonEmptyString

def create_app(settings:AppSettings, *, backend_factory=None)->FastAPI:
    if not isinstance(settings,AppSettings):
        raise TypeError('AppSettings required')
    errors={code:{'model':ApiError} for code in (400,401,403,404,409,422,500)}
    if backend_factory is not None and not callable(backend_factory):
        raise TypeError('Private backend factory required')
    @asynccontextmanager
    async def lifespan(app):
        if backend_factory is None:
            yield
            return
        from app.runtime.supervisor import TaskSupervisor
        bindings=backend_factory(app)
        if inspect.isawaitable(bindings):
            bindings=await bindings
        supervisor=TaskSupervisor(app.state.database.path,bindings,provider_mode=settings.provider_mode)
        supervisor.register_profiles()
        app.state.provider_registry=supervisor.provider_registry
        app.state.supervisor=supervisor
        runner=asyncio.create_task(supervisor.run())
        app.state.supervisor_task=runner
        try:
            yield
        finally:
            await supervisor.shutdown()
            runner.cancel()
            with suppress(asyncio.CancelledError):
                await runner
            app.state.provider_registry={}
    app=FastAPI(title='Local workbench API',version='1.0',docs_url=None,redoc_url=None,responses=errors,lifespan=lifespan)
    app.state.settings=settings
    app.state.instance_id=os.environ.get('WORKBENCH_INSTANCE_ID') or secrets.token_hex(16)
    app.state.provider_registry={}
    app.state.storage_frozen=False
    app.state.relocation_plan=None
    app.state.relocation_result=None
    app.state.backup_refs={}
    app.state.backup_restore_result=None
    app.state.request_gate=asyncio.Lock()
    app.state.database=Database(settings.data_root/'workbench.sqlite3')
    app.state.blobs=BlobStore(settings.data_root/'blobs')
    with closing(app.state.database.connect()) as connection:
        migrate(connection)
        if settings.provider_mode=='fake':
            for family in ('gpt','glm'):
                connection.execute("INSERT OR IGNORE INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,identity_source,connection_version) VALUES (?,?,?,?,?,'unknown',NULL,'test-only')",(f'fake-{family}','fake',f'fixture-{family}',family,f'fake-{family}'))
    app.state.recovery_results=[]
    if settings.startup_recovery:
        from app.runtime.recovery import Recovery
        app.state.recovery_results=Recovery(app.state.database.path).recover(
            lambda row:{'status':'unknown'}, resume_publications=True, provider_mode=settings.provider_mode)
    @app.middleware('http')
    async def authenticate(request:Request,call_next):
        expected='Bearer '+settings.api_token
        if not secrets.compare_digest(request.headers.get('Authorization','').encode('utf-8'),expected.encode('utf-8')):
            return JSONResponse({'detail':'本地认证失败。'},status_code=401)
        host=request.url.hostname
        allowed={'localhost','127.0.0.1','::1'} | ({'testserver'} if settings.provider_mode=='fake' else set())
        if host not in allowed or request.headers.get('Origin') is not None:
            return JSONResponse({'detail':'请求来源不受支持。'},status_code=403)
        # Serialize mutations and relocation. Frozen roots can only be inspected
        # or checkpointed by their managed owner before a restart.
        if app.state.storage_frozen and request.url.path not in {'/v1/health','/v1/storage','/v1/checkpoint'}:
            return JSONResponse({'detail':'目录迁移已核验，正在等待后端重启。'},status_code=409)
        async with app.state.request_gate:
            # History reads can persist an outbox projection, so they use the
            # same fence as mutations rather than racing a verified copy.
            if app.state.storage_frozen and request.url.path not in {'/v1/health','/v1/storage','/v1/checkpoint'}:
                return JSONResponse({'detail':'目录迁移已核验，正在等待后端重启。'},status_code=409)
            return await call_next(request)
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,error):
        return JSONResponse({'detail':'请求字段不符合接口要求。'},status_code=422)
    app.include_router(conversations.router)
    app.include_router(turns.router)
    app.include_router(tasks.router)
    from . import settings as settings_api, usage, storage, diagnostics, attachments, profiles, artifacts, backups
    for module in (settings_api, usage, storage, diagnostics, attachments, profiles, artifacts, backups):
        app.include_router(module.router)
    @app.get('/v1/health')
    def health():
        return dict(protocol_version='1.0',instance_id=app.state.instance_id,pid=os.getpid(),provider_mode=settings.provider_mode)
    @app.post('/v1/checkpoint')
    def checkpoint():
        with closing(app.state.database.connect()) as connection:
            result=connection.execute('PRAGMA wal_checkpoint(FULL)').fetchone()
        if result[0] != 0:
            return JSONResponse({'saved':False,'detail':'检查点仍在等待写入完成。'},status_code=409)
        return dict(saved=True)
    return app
