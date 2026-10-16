"""Private text-only Codex phase controller; metadata is never an execution grant.

The pinned stdlib worker owns CLI stdin and bounds raw responses privately.
Only the trusted native_scope issuer can grant a live phase capability. Fixture
transports exercise the real Windows Job/codec but cannot qualify production.
"""
import asyncio
from contextlib import closing, suppress
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import threading
import time
from uuid import uuid4

from app.contracts.providers import ProviderContract, ProviderIdentity
from app.providers.phase_bridge import PhaseCapture, PhaseStarted, PhaseUsage, UsageReceipt
from app.providers.native_rpc import RpcCleanup
from app.runtime.processes import ProcessManager, _SecurityAttributes
from app.runtime.resources import ResourceLimits
from app.providers import scoped_codex_worker as codec


class ScopedCodexError(RuntimeError):
    def __init__(self, reason_code):
        self.reason_code=reason_code
        super().__init__(reason_code)


class NativePrivateProcess:
    """Trusted caller's one-shot anonymous-stdin worker inside an atomic Job.

    This is a private transport, not a model execution grant. The caller pins
    its worker entry. No packet/secret config is written to a temporary file.
    """
    def __init__(self,ledger_path,limits=None):
        self.manager=ProcessManager(Path(ledger_path),limits or ResourceLimits(max_running=1,
            max_output_bytes=2_000_000,cancel_grace_seconds=.1,kill_wait_seconds=3))
        self.handle=None
        self.context=None
        self._write_handle=None
        self._started=self._closed=False
        self._lock=threading.RLock()
        self._api=self.manager._windows.api
        self._cleanup=None

    def _start_with_issuer(self,cwd,issuer):
        with self._lock:
            if self._started or self._closed: raise ScopedCodexError('PRIVATE_PROCESS_ALREADY_STARTED')
            self._started=True
            api=self._api
            read,write=wintypes.HANDLE(),wintypes.HANDLE()
            sa=_SecurityAttributes(ctypes.sizeof(_SecurityAttributes),None,True)
            self.manager._windows.checked(api.CreatePipe(ctypes.byref(read),ctypes.byref(write),ctypes.byref(sa),4096))
            try:
                self.manager._windows.checked(api.SetHandleInformation(write,1,0))
                api.WriteFile.argtypes=[wintypes.HANDLE,wintypes.LPCVOID,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),wintypes.LPVOID]
                api.WriteFile.restype=wintypes.BOOL
                original=api.CreateFileW
                api.CreateFileW=lambda name,*args: read.value if name=='NUL' else original(name,*args)
                self._write_handle=write
                try:
                    issued=issuer(self.manager)
                    if isinstance(issued,tuple): self.handle,self.context=issued
                    else: self.handle=issued
                finally: api.CreateFileW=original
            except BaseException:
                if self.handle is None:
                    with suppress(OSError): api.CloseHandle(read)
                self.close(); raise
            return self

    def start(self,task_id,attempt_id,command,cwd,*,step_id='default'):
        return self._start_with_issuer(cwd,lambda manager:manager.start(task_id,attempt_id,command,Path(cwd),step_id=step_id))

    @property
    def stdout(self): return self.handle.stdout if self.handle else b''

    @property
    def stderr(self): return self.handle.stderr if self.handle else b''

    def write_json(self,packet):
        if self._closed or self.handle is None or self._write_handle is None: raise ScopedCodexError('PRIVATE_PROCESS_NOT_RUNNING')
        data=json.dumps(packet,ensure_ascii=True,allow_nan=False).encode()+b'\n'
        if len(data)>self.manager.limits.max_output_bytes: raise ScopedCodexError('INPUT_LIMIT')
        written=wintypes.DWORD()
        self.manager._windows.checked(self._api.WriteFile(self._write_handle,data,len(data),ctypes.byref(written),None))
        if written.value!=len(data): raise ScopedCodexError('PRIVATE_PIPE_PARTIAL_WRITE')

    def poll(self): return self.manager.poll(self.handle) if self.handle is not None else None

    def close(self):
        with self._lock:
            if self._cleanup is not None: return self._cleanup
            self._closed=True
            failed=False; result=None
            if self.handle is not None:
                try:
                    result=self.manager.poll(self.handle)
                    if result is None: result=self.manager.cancel(self.handle)
                except (OSError,RuntimeError): failed=True
            if self._write_handle is not None:
                if not self._api.CloseHandle(self._write_handle): failed=True
                self._write_handle=None
            try: self.manager.close()
            except (OSError,RuntimeError): failed=True
            snapshot=self.manager.resource_snapshot()
            self._cleanup=RpcCleanup(result.local_state if result else 'not_started' if self.handle is None else 'cleanup_failed',
                'unknown' if self.handle is not None else 'not_applicable',not failed and not any(snapshot[k] for k in ('running','open_handles','temp_dirs')),
                bool(result and result.forced),bool(result and result.output_truncated),snapshot['running'],snapshot['open_handles'],snapshot['temp_dirs'])
            return self._cleanup


@dataclass(frozen=True)
class ScopePreparation:
    control_count: int
    controls_verified: bool
    transport_kind: str
    production_qualified: bool
    control_policy_sha256: str
    configured_mcp_count: int
    thread_id: str
    entry_sha256: str | None
    source_worker_sha256: str
    submitted_model_turns: int = 0


def _sha(data): return hashlib.sha256(data).hexdigest()


def _safe_path(path, root):
    original=Path(path).absolute()
    for ancestor in (original,*original.parents):
        attrs=ancestor.lstat()
        if stat.S_ISLNK(attrs.st_mode) or getattr(attrs,'st_file_attributes',0)&0x400:
            raise ScopedCodexError('WORKSPACE_REPARSE_FORBIDDEN')
    path=original.resolve(strict=True)
    if not path.is_relative_to(root): raise ScopedCodexError('WORKSPACE_SCOPE_MISMATCH')
    return path


class _ScopeCapability:
    def __init__(self,runtime): self._runtime=runtime

    def require_verified(self,provider):
        runtime=self._runtime
        if runtime._fixture: raise ScopedCodexError('FIXTURE_SCOPE_NOT_PRODUCTION')
        if not isinstance(provider,ProviderContract) or provider!=runtime.provider: raise ScopedCodexError('PROVIDER_SCOPE_MISMATCH')
        provider.require_executable()
        if runtime._enforcer is None: raise ScopedCodexError('LIFETIME_ENFORCER_MISSING')
        if runtime._preparation is None or not runtime._preparation.controls_verified: raise ScopedCodexError('SCOPE_NOT_PREPARED')
        if runtime._scope_seal is None: raise ScopedCodexError('PRIVATE_SCOPE_SEAL_REQUIRED')
        runtime._enforcer.require_verified(codec.ENTRY_SHA256,runtime._policy_hash())

    def authorize(self,request,binding):
        self.require_verified(self._runtime.provider)
        path=self._runtime._request_source(request,binding)
        if _sha(path.read_bytes())!=binding.prompt_sha256: raise ScopedCodexError('INPUT_SOURCE_CHANGED')


class ScopedCodexRuntime:
    def __init__(self,provider:ProviderContract,*,ledger_path:Path,workspace_root:Path,entry_manifest:Path,
                 lifetime_enforcer=None,timeout_seconds=120,max_output_bytes=2_000_000,worker_factory=None):
        if not isinstance(provider,ProviderContract) or (provider.identity.adapter,provider.identity.family.value)!=('codex','gpt'):
            raise ScopedCodexError('GPT_NATIVE_PROVIDER_REQUIRED')
        if type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or not 0<timeout_seconds<=120:
            raise ScopedCodexError('TIME_LIMIT_INVALID')
        if type(max_output_bytes) is not int or not 1024<=max_output_bytes<=2_000_000: raise ScopedCodexError('OUTPUT_LIMIT_INVALID')
        if lifetime_enforcer is not None and (isinstance(lifetime_enforcer,(dict,str,bool)) or not all(callable(getattr(lifetime_enforcer,m,None)) for m in
            ('require_verified','authorize_rpc','observe_rpc_response','start_native_phase','open_fixture_phase','scope_seal','close'))):
            raise ScopedCodexError('TRUSTED_LIFETIME_ENFORCER_REQUIRED')
        self.provider=ProviderContract.model_validate(provider.model_dump())
        self.workspace_root=Path(workspace_root).resolve(strict=True)
        if not self.workspace_root.is_dir(): raise ScopedCodexError('WORKSPACE_REQUIRED')
        _safe_path(self.workspace_root,self.workspace_root)
        self.ledger_path,self.entry_manifest=Path(ledger_path).resolve(),Path(entry_manifest)
        self.timeout_seconds,self.max_output_bytes=timeout_seconds,max_output_bytes
        self._enforcer,self._factory=lifetime_enforcer,worker_factory
        self._fixture=worker_factory is not None
        if self._fixture and not callable(worker_factory): raise ScopedCodexError('TRUSTED_FIXTURE_FACTORY_REQUIRED')
        self.scope_capability=_ScopeCapability(self)
        self._manager=self._handle=self._write_handle=self._context=None
        self._transport=None
        self._api=None
        self._preparation=None
        self._scope_seal=None
        self._active=None
        self._closed=False
        self._cancelled=threading.Event()
        self._lock=threading.RLock()
        self._operation_lock=asyncio.Lock()
        self.last_cleanup=RpcCleanup('not_started','not_applicable',True)
        self.last_capture_sha256=None
        self._last_observed=None
        self.diagnostics={'transport_kind':'fixture' if self._fixture else 'native','submitted_model_turns':0,
            'actual_external_model_submissions':0 if self._fixture else None,'accepted':False,
            'interrupt_acknowledged':False,'remote_stop_confirmed':False,'raw_private_output_exported':False,
            'source_worker_sha256':_sha(Path(codec.__file__).read_bytes())}

    @property
    def classification(self): return 'fixture' if self._fixture else 'production'

    def _policy_hash(self):
        if self._enforcer is not None:
            from app.providers.native_scope import CONTROL_POLICY_SHA256
            return CONTROL_POLICY_SHA256
        return codec.POLICY_SHA256

    def _entry(self):
        if self._fixture: return None
        if any(name in os.environ for name in ('CODEX_HOME','CODEX_SQLITE_HOME')):
            raise ScopedCodexError('NONDEFAULT_NATIVE_HOME_REQUIRES_PRESERVATION')
        try:
            manifest=codec.parse(self.entry_manifest.read_bytes())
            exe=Path(manifest['executable']).resolve(strict=True)
            if manifest.get('source_kind')!='official_installed_runtime' or manifest.get('runtime_version')!='0.160.0' or manifest.get('executable_sha256')!=codec.ENTRY_SHA256:
                raise ScopedCodexError('OFFICIAL_ENTRY_PIN_MISMATCH')
            if not str(exe).replace('\\','/').endswith(codec.ENTRY_SUFFIX) or _sha(exe.read_bytes())!=codec.ENTRY_SHA256:
                raise ScopedCodexError('OFFICIAL_ENTRY_PIN_MISMATCH')
            return exe
        except (OSError,KeyError,ValueError): raise ScopedCodexError('OFFICIAL_ENTRY_PIN_MISMATCH') from None

    def _claim(self,task,attempt,request):
        self.ledger_path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.ledger_path)) as conn, conn:
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('CREATE TABLE IF NOT EXISTS scoped_invocations(task TEXT,attempt TEXT,request TEXT,state TEXT,external_request TEXT,external_execution TEXT,PRIMARY KEY(task,attempt,request))')
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM scoped_invocations WHERE task=? AND attempt=? AND request=?',(task,attempt,request)).fetchone():
                raise ScopedCodexError('REQUEST_ALREADY_USED')
            if conn.execute("SELECT 1 FROM scoped_invocations WHERE task=? AND attempt=? AND state IN ('launching','submitted','accepted','unknown')",(task,attempt)).fetchone():
                raise ScopedCodexError('UNKNOWN_REMOTE_UNRESOLVED')
            conn.execute("INSERT INTO scoped_invocations VALUES(?,?,?,'launching',NULL,NULL)",(task,attempt,request))

    def _record(self,state,request=None,execution=None):
        if self._active is None or self._active[0]=='scope-prepare': return
        with closing(sqlite3.connect(self.ledger_path)) as conn, conn:
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('UPDATE scoped_invocations SET state=?,external_request=coalesce(?,external_request),external_execution=coalesce(?,external_execution) WHERE task=? AND attempt=? AND request=?',
                (state,request,execution,*self._active))

    def _boot(self,action,text,task,attempt,request,phase,workspace,schema):
        entry=self._entry()
        boot={'action':action,'nonce':uuid4().hex,'workspace':str(workspace),'task_id':task,'attempt_id':attempt,'request_id':request,
            'phase':phase,'text':text,'input_source_sha256':_sha(text.encode()),'output_schema':schema,
            'expected_model':self.provider.identity.model_id,'transport_kind':'fixture' if self._fixture else 'native',
            'timeout_seconds':max(.1,self.timeout_seconds-min(5,self.timeout_seconds*.15)),'max_output_bytes':self.max_output_bytes}
        if self._fixture:
            command=self._factory()
            if not isinstance(command,list) or not command or any(not isinstance(arg,str) or '\0' in arg for arg in command): raise ScopedCodexError('FIXTURE_COMMAND_INVALID')
            if Path(command[0]).resolve()!=Path(sys._base_executable).resolve(): raise ScopedCodexError('FIXTURE_PYTHON_ENTRY_REQUIRED')
            boot['fixture_command']=command
        else: boot['executable']=str(entry)
        return boot,entry

    def _launch(self,boot,entry):
        with self._lock:
            if self._closed or self._cancelled.is_set(): raise ScopedCodexError('RUNTIME_CLOSED')
            self._transport=NativePrivateProcess(self.ledger_path,ResourceLimits(max_running=1,max_processes_per_job=8,
                max_output_bytes=self.max_output_bytes,cancel_grace_seconds=.1,kill_wait_seconds=3))
            self._manager=self._transport.manager
            if self._enforcer is not None:
                from app.providers.native_scope import NativePhaseBinding
                binding=NativePhaseBinding(boot['task_id'],boot['attempt_id'],boot['request_id'],boot['phase'],Path(boot['workspace']),
                    boot['text'],boot['input_source_sha256'],boot['expected_model'],codec.ROUTE)
            if self._enforcer is not None and not self._fixture:
                self._transport._start_with_issuer(Path(boot['workspace']),lambda manager:self._enforcer.start_native_phase(manager,binding,entry))
                self._context=self._transport.context
            else:
                self._transport.start(boot['task_id'],boot['attempt_id'],[sys._base_executable,str(Path(codec.__file__))],
                    Path(boot['workspace']),step_id=boot['request_id'])
                if self._enforcer is not None: self._context=self._enforcer.open_fixture_phase(binding,metadata_stage='baseline')
            self._handle=self._transport.handle

    def _write(self,value):
        if self._transport is None: raise ScopedCodexError('PRIVATE_PROCESS_NOT_RUNNING')
        self._transport.write_json(value)

    def _authorize(self,packet,boot):
        method=packet.get('method'); params=packet.get('params')
        if method not in codec.METHODS or not isinstance(params,dict): raise ScopedCodexError('RPC_METHOD_FORBIDDEN')
        if method=='turn/start':
            if boot['action']!='invoke' or self._preparation is None or not self._preparation.controls_verified:
                raise ScopedCodexError('MODEL_PRECONDITIONS_MISSING')
            if not self._fixture and self._enforcer is None: raise ScopedCodexError('LIFETIME_ENFORCER_MISSING')
            if params.get('input_source_sha256')!=boot['input_source_sha256']: raise ScopedCodexError('INPUT_SOURCE_CHANGED')
            params=dict(params); params.pop('input_source_sha256')
            params['input']=[{'type':'text','text':boot['text'],'text_elements':[]}]
        if self._enforcer is not None:
            self._enforcer.authorize_rpc(method,params,self._context)
            if method=='turn/start' and not self._fixture: self._enforcer.require_verified(codec.ENTRY_SHA256,self._policy_hash())
        if method=='turn/start':
            # Once permission can reach the worker, transmission is possible.
            # A missing later worker receipt cannot prove that it never sent.
            self._record('submitted')
            self.diagnostics['submission_possible']=True

    def _cleanup(self):
        with self._lock:
            if self._manager is None: return self.last_cleanup
            self.last_cleanup=self._transport.close()
            if self._enforcer is not None and self._context is not None:
                with suppress(Exception): self._enforcer.close(self._context,self.last_cleanup.cleanup_complete)
            self._manager=self._handle=self._context=self._transport=None
            return self.last_cleanup

    async def _exchange(self,boot,entry,schema):
        offset=0; pending=b''; capture=None; started=None; accepted_execution=None; failure=None; bill=None
        deadline=time.monotonic()+self.timeout_seconds
        try:
            await asyncio.to_thread(self._launch,boot,entry)
            await asyncio.to_thread(self._write,boot)
            while True:
                if self._cancelled.is_set(): raise ScopedCodexError('LOCAL_CANCELLED_REMOTE_UNKNOWN')
                if time.monotonic()>=deadline: raise ScopedCodexError('TIMEOUT_REMOTE_UNKNOWN')
                handle=self._handle
                if handle is None: raise ScopedCodexError('LOCAL_CANCELLED_REMOTE_UNKNOWN')
                data=handle.stdout
                pending+=data[offset:]; offset=len(data)
                while b'\n' in pending:
                    line,pending=pending.split(b'\n',1)
                    try: packet=codec.parse(line)
                    except (ValueError,UnicodeError): raise ScopedCodexError('INVALID_PRIVATE_WORKER_FRAME') from None
                    if not isinstance(packet,dict) or packet.get('nonce')!=boot['nonce']: raise ScopedCodexError('PRIVATE_WORKER_BINDING_MISMATCH')
                    kind=packet.get('kind')
                    if kind=='rpc.authorize':
                        try: self._authorize(packet,boot)
                        except Exception:
                            with suppress(Exception): await asyncio.to_thread(self._write,{'nonce':boot['nonce'],'allow':False})
                            raise ScopedCodexError('RPC_AUTHORIZATION_DENIED') from None
                        await asyncio.to_thread(self._write,{'nonce':boot['nonce'],'allow':True})
                    elif kind=='rpc.observed':
                        if self._enforcer is not None:
                            try: self._enforcer.observe_rpc_response(packet['method'],packet['result'],self._context)
                            except Exception: raise ScopedCodexError('SCOPE_OBSERVATION_REJECTED') from None
                        await asyncio.to_thread(self._write,{'nonce':boot['nonce'],'observed':True})
                    elif kind=='prepared':
                        if packet.get('control_count')!=22 or packet.get('controls_verified') is not True or not all(packet.get(k) is True for k in
                            ('mcp_keys_match','all_mcp_disabled','thread_start_verified','thread_read_verified')):
                            raise ScopedCodexError('SCOPE_PREPARATION_INVALID')
                        if packet.get('policy_sha256')!=codec.POLICY_SHA256 or packet.get('transport_kind')!=boot['transport_kind']:
                            raise ScopedCodexError('SCOPE_POLICY_MISMATCH')
                        qualified=False
                        if self._enforcer is not None and not self._fixture:
                            from app.providers.native_scope import VerifiedScopeSeal
                            seal=self._enforcer.scope_seal(self._context)
                            if not isinstance(seal,VerifiedScopeSeal): raise ScopedCodexError('PRIVATE_SCOPE_SEAL_REQUIRED')
                            self._enforcer.require_verified(codec.ENTRY_SHA256,self._policy_hash())
                            self._scope_seal=seal; qualified=True
                        self._preparation=ScopePreparation(22,True,boot['transport_kind'],qualified,self._policy_hash(),packet['configured_mcp_count'],
                            packet['thread_id'],codec.ENTRY_SHA256 if entry else None,self.diagnostics['source_worker_sha256'])
                    elif kind=='submitted':
                        self.diagnostics['submitted_model_turns']+=1
                        if self.diagnostics['submitted_model_turns']!=1: raise ScopedCodexError('SECOND_MODEL_SUBMISSION_FORBIDDEN')
                        self._record('submitted')
                    elif kind=='accepted':
                        self.diagnostics['accepted']=True
                        accepted_execution=packet.get('external_execution_id')
                        self._record('accepted',execution=accepted_execution)
                    elif kind=='started':
                        value=PhaseStarted(boot['request_id'],packet.get('external_request_id'),packet.get('external_execution_id'))
                        if started is not None: raise ScopedCodexError('DUPLICATE_PHASE_START')
                        if value.external_execution_id!=accepted_execution: raise ScopedCodexError('REMOTE_REFERENCE_MISMATCH')
                        started=value; self._record('accepted',value.external_request_id,value.external_execution_id)
                        yield value
                    elif kind in ('capture','usage'):
                        if capture is not None or started is None: raise ScopedCodexError('CAPTURE_NOT_UNIQUE')
                        if (packet.get('external_request_id'),packet.get('external_execution_id'))!=(started.external_request_id,started.external_execution_id):
                            raise ScopedCodexError('REMOTE_REFERENCE_MISMATCH')
                        if packet.get('actual_model_id')!=self.provider.identity.model_id or packet.get('identity_source')!='official_response_completed_model':
                            raise ScopedCodexError('ACTUAL_MODEL_IDENTITY_MISMATCH')
                        if kind=='usage':
                            if bill is not None or capture is not None or any(key in packet for key in ('final_text','final_sha256')):
                                raise ScopedCodexError('BILLING_NOT_UNIQUE')
                            usage=packet.get('usage')
                            if not isinstance(usage,dict): raise ScopedCodexError('USAGE_RECEIPT_MISSING')
                            bill=PhaseUsage(boot['request_id'],self.provider,started.external_request_id,
                                started.external_execution_id,(UsageReceipt(boot['request_id']+':response',1,usage),))
                            continue
                        if bill is not None: raise ScopedCodexError('BILLING_ONLY_CANNOT_COMPLETE')
                        text=packet.get('final_text')
                        if not isinstance(text,str) or not text.strip() or _sha(text.encode())!=packet.get('final_sha256'):
                            raise ScopedCodexError('FINAL_BYTES_BINDING_MISMATCH')
                        # Preserve a genuine, bound completion and its usage even
                        # when the model violates the requested business schema.
                        # Planner/PhaseBridge record usage before parsing text.
                        usage=packet.get('usage')
                        if not isinstance(usage,dict): raise ScopedCodexError('USAGE_RECEIPT_MISSING')
                        capture=PhaseCapture(boot['request_id'],self.provider,text,started.external_request_id,started.external_execution_id,
                            (UsageReceipt(boot['request_id']+':response',1,usage),),exit_code=0,finished=True)
                        self.last_capture_sha256=packet['final_sha256']
                    elif kind=='interrupt_ack': self.diagnostics['interrupt_acknowledged']=packet.get('acknowledged') is True
                    elif kind=='error':
                        reason=packet.get('reason_code'); failure=reason if isinstance(reason,str) and re.fullmatch('[A-Z_]{1,90}',reason) else 'PRIVATE_WORKER_FAILED'
                    else: raise ScopedCodexError('UNSUPPORTED_PRIVATE_FRAME')
                manager=self._manager
                if manager is None: raise ScopedCodexError('LOCAL_CANCELLED_REMOTE_UNKNOWN')
                result=manager.poll(handle)
                if result is not None:
                    # All stdout readers finish before ProcessManager reports
                    # terminal state. Drain any last bytes before accepting EOF.
                    if len(handle.stdout)>offset: continue
                    if result.output_truncated: raise ScopedCodexError('OUTPUT_LIMIT')
                    if pending: raise ScopedCodexError('TRUNCATED_PRIVATE_WORKER_FRAME')
                    if failure: raise ScopedCodexError(failure)
                    if result.returncode!=0: raise ScopedCodexError('UNKNOWN_REMOTE' if self.diagnostics['accepted'] else 'PRIVATE_WORKER_FAILED')
                    if boot['action']=='invoke' and capture is None: raise ScopedCodexError('UNKNOWN_REMOTE' if self.diagnostics['accepted'] else 'CAPTURE_MISSING')
                    break
                await asyncio.sleep(.005)
            if capture is not None:
                self._record('completed',capture.external_request_id,capture.external_execution_id)
                self._last_observed=ProviderIdentity(**self.provider.identity.model_dump())
        except BaseException:
            if boot['action']=='invoke': self._record('unknown' if self.diagnostics.get('submission_possible') else 'failed_before_submission')
            if self.diagnostics['accepted'] and started is None:
                yield PhaseStarted(boot['request_id'],None,accepted_execution)
            # Even when trailing transport activity invalidates business output,
            # keep a separately authenticated receipt. Cleanup precedes delivery.
            if bill is None and capture is not None:
                bill=PhaseUsage(capture.local_request_id,capture.observed_provider,
                    capture.external_request_id,capture.external_execution_id,capture.usage_receipts)
            if bill is not None:
                await asyncio.to_thread(self._cleanup)
                yield bill
            raise
        finally:
            cleanup=await asyncio.to_thread(self._cleanup)
            if not cleanup.cleanup_complete: self.diagnostics['cleanup_failed']=True
        if not self.last_cleanup.cleanup_complete: raise ScopedCodexError('PROCESS_CLEANUP_FAILED')
        if capture is not None: yield capture

    async def prepare(self):
        async with self._operation_lock:
            if self._closed: raise ScopedCodexError('RUNTIME_CLOSED')
            self._active=('scope-prepare',uuid4().hex,uuid4().hex)
            self._cancelled.clear()
            boot,entry=self._boot('prepare','',*self._active,'preparation',self.workspace_root,{})
            async for _ in self._exchange(boot,entry,{}): raise ScopedCodexError('UNEXPECTED_PREPARATION_MODEL_EVENT')
            self._active=None
            if self._preparation is None: raise ScopedCodexError('SCOPE_PREPARATION_MISSING')
            return self._preparation

    @staticmethod
    def _schema(schema):
        try:
            if not isinstance(schema,dict) or len(json.dumps(schema,allow_nan=False).encode())>65536: raise ValueError()
            def visit(node):
                if isinstance(node,dict):
                    if '$ref' in node and (not isinstance(node['$ref'],str) or not node['$ref'].startswith('#/')): raise ValueError()
                    if '$dynamicRef' in node: raise ValueError()
                    if 'type' in node:
                        types=node['type'] if isinstance(node['type'],list) else [node['type']]
                        if not types or any(value not in {'null','boolean','object','array','number','integer','string'} for value in types): raise ValueError()
                    for key in ('properties','$defs','definitions'):
                        if key in node and not isinstance(node[key],dict): raise ValueError()
                    if 'required' in node and (not isinstance(node['required'],list) or any(not isinstance(value,str) for value in node['required']) or len(set(node['required']))!=len(node['required'])): raise ValueError()
                    for key in ('anyOf','oneOf','allOf'):
                        if key in node and (not isinstance(node[key],list) or not node[key] or any(not isinstance(value,(dict,bool)) for value in node[key])): raise ValueError()
                    for value in node.values(): visit(value)
                elif isinstance(node,list):
                    for value in node: visit(value)
            visit(schema)
        except Exception: raise ScopedCodexError('OUTPUT_SCHEMA_INVALID') from None
        return json.loads(json.dumps(schema))

    async def _invoke(self,text,*,task_id,attempt_id,request_id,phase,workspace,output_schema):
        if not isinstance(text,str) or not text.strip() or len(text.encode())>min(900000,self.max_output_bytes//2): raise ScopedCodexError('INPUT_TEXT_INVALID')
        if any(not codec.safe_id(value) for value in (task_id,attempt_id,request_id)): raise ScopedCodexError('REQUEST_BINDING_INVALID')
        workspace=_safe_path(workspace,self.workspace_root)
        if not workspace.is_dir(): raise ScopedCodexError('WORKSPACE_REQUIRED')
        schema=self._schema(output_schema)
        if self._closed: raise ScopedCodexError('RUNTIME_CLOSED')
        if self._operation_lock.locked(): raise ScopedCodexError('RUNTIME_BUSY')
        if not self._fixture:
            self.provider.require_executable()
            if self._enforcer is None: raise ScopedCodexError('LIFETIME_ENFORCER_MISSING')
        async with self._operation_lock:
            self._claim(task_id,attempt_id,request_id)
            self._active=(task_id,attempt_id,request_id)
            self._cancelled.clear()
            self.diagnostics['submitted_model_turns']=0; self.diagnostics['accepted']=False
            self.diagnostics['submission_possible']=False
            try:
                try:
                    boot,entry=self._boot('invoke',text,task_id,attempt_id,request_id,phase,workspace,schema)
                except BaseException:
                    self._record('failed_before_submission')
                    raise
                async for event in self._exchange(boot,entry,schema): yield event
            finally: self._active=None

    async def invoke_text(self,text,*,task_id,attempt_id,request_id,phase,workspace,output_schema):
        if phase not in {'planning','finalization'}: raise ScopedCodexError('PRIVATE_TEXT_PHASE_INVALID')
        async for event in self._invoke(text,task_id=task_id,attempt_id=attempt_id,request_id=request_id,phase=phase,workspace=workspace,output_schema=output_schema): yield event

    def _request_source(self,request,binding):
        if request.role!='A' or request.identity!=ProviderIdentity(**self.provider.identity.model_dump()): raise ScopedCodexError('PHASE_IDENTITY_MISMATCH')
        workspace=_safe_path(request.workspace,self.workspace_root)
        path=_safe_path(request.prompt_path,workspace)
        if not path.is_file() or path.stat().st_nlink!=1 or path.stat().st_size>900000: raise ScopedCodexError('INPUT_SOURCE_INVALID')
        if (request.task_id,request.attempt_id)!=(binding.contract.task_id,binding.contract.attempt_id) or path.stem!=binding.request_id:
            raise ScopedCodexError('PHASE_REQUEST_BINDING_MISMATCH')
        return path

    async def run(self,request,binding):
        path=self._request_source(request,binding)
        data=path.read_bytes()
        if _sha(data)!=binding.prompt_sha256: raise ScopedCodexError('INPUT_SOURCE_CHANGED')
        from app.providers.phase_bridge import _Review,_Candidate,phase_prompt_text
        schema=(_Review if binding.phase=='review' else _Candidate).model_json_schema()
        text=phase_prompt_text(binding,data.decode('utf-8'))
        async for event in self._invoke(text,task_id=request.task_id,attempt_id=request.attempt_id,request_id=binding.request_id,
            phase=binding.phase,workspace=request.workspace,output_schema=schema): yield event

    async def probe(self):
        if self._last_observed is None: raise ScopedCodexError('EXECUTED_MODEL_IDENTITY_UNKNOWN')
        return self._last_observed

    async def cancel(self,task_id,attempt_id):
        active=self._active
        if active is not None and active[:2]!=(task_id,attempt_id): raise ScopedCodexError('CANCEL_CONTEXT_MISMATCH')
        self._cancelled.set()
        if active is not None: self._record('unknown' if self.diagnostics.get('submission_possible') else 'failed_before_submission')
        return await asyncio.to_thread(self._cleanup)

    def close(self):
        self._closed=True; self._cancelled.set()
        return self._cleanup()
