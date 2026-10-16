"""Private source-bound model-tool ceiling. This is not an OS sandbox."""
import copy
import hashlib
import json
import re
import sys
import stat
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

OFFICIAL_ENTRY_SHA256 = '4b01d5920e6785614727443bbecf343f4dedbb7347052b72ba805aab6353ef01'
WORKER_SOURCE_SHA256 = '92fd9440c70307c9c5b7e2c9be30489ea2c4454c760b086f06478d4f1b7210ab'
_ROUTE = 'workbench_scoped_chatgpt_http'
_CONTROLS = {
    'features.shell_tool': False, 'features.view_image': False,
    'features.code_mode': False, 'features.code_mode_only': False,
    'features.code_mode_host.enabled': False,
    'features.code_mode_host.disable_in_process_fallback': False,
    'features.multi_agent': False, 'features.multi_agent_v2': False,
    'agents.enabled': False, 'features.apps': False, 'features.plugins': False,
    'features.tool_suggest': False, 'features.recommended_plugins': False,
    'features.memories': False, 'memories.use_memories': False,
    'cloud.skills.enabled': False, 'features.image_generation': False,
    'web_search': 'disabled', 'features.hooks': False, 'notify': [],
    'features.deferred_executor': False, 'features.request_permissions_tool': False,
}
_METHODS = ('initialize', 'initialized', 'config/read', 'thread/start', 'thread/read',
            'turn/start', 'turn/interrupt', 'thread/unsubscribe')
_SOURCE = {
    'tag': 'rust-v0.160.0', 'commit': 'a956835d020762cb2b570053af06f643a11c0ecc',
    'archive_sha256': 'e9ba182239bb984f1d24a57c8b3abb3da127e0a108e5f17d7a9038688cf4369c',
    'entry_sha256': OFFICIAL_ENTRY_SHA256,
    'worker_source_sha256': WORKER_SOURCE_SHA256,
    'provider_route': _ROUTE,
    'boundary': 'software_model_tool_no_filesystem_or_arbitrary_execution',
    'os_sandbox_verified': False,
    'sources': {
        'core/src/config/mod.rs': '854f5a6b184714740500b8d3eae2bb04cb88172efccf11d38a74f2f6189c0341',
        'core/src/session/mcp_runtime.rs': 'ff6c351e3af4f662c265a2f0c16e84da7815771913a493694eba0d99ec08d8eb',
        'core/src/session/mcp_prewarm.rs': '7cf5ad62e835c1f51399cbf7786b3adfb20cf4c4f02c0b37822035c2b1c00d23',
        'core/src/session/mod.rs': 'd05728bce8f6f3163d20ec4286bf964d7dfda27a39d4669b755e7a2e51849ecf',
        'core/src/tools/spec_plan.rs': '849ef21d4e5c83febdc31eacd7609911d43e3f69a35168fe02ae899273b5ef3e',
        'core/src/tools/registry.rs': 'd2793cddbdc34ad8d849a991dafd5871a3ce8ded4b33c446b2c1934e1cee526b',
        'core/src/tools/handlers/dynamic.rs': '5e315b42993b4637e5543bcfcc858b82336437f7fb3a367ff5dc911273fa97b4',
        'core-plugins/src/manager.rs': '4d1ac59d49155bfe434b169243c53eab4099ccf2c3d2649ec5e273e255419153',
        'core/src/thread_manager.rs': '1c356242684633729042aaac6350295b759a8fe1fc05eff28b78895f6ff2fa9d',
    },
}
_POLICY = {'version': 2, 'controls': _CONTROLS, 'methods': list(_METHODS),
    'thread': {'ephemeral': True, 'environments': [], 'dynamicTools': [],
               'approvalPolicy': 'never', 'sandbox': 'read-only'},
    'turn': {'maximum_top_level_turns': 1, 'input_type': 'text', 'effort': 'low', 'environments': [],
             'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False}},
    'source': _SOURCE}
CONTROL_POLICY = copy.deepcopy(_POLICY)
SOURCE_POLICY_MANIFEST = copy.deepcopy(_SOURCE)
CONTROL_POLICY_SHA256 = hashlib.sha256(json.dumps(_POLICY, sort_keys=True,
    separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
_MINT = object()

class NativeScopeError(ValueError):
    """Only fixed codes; private paths and metadata never appear in errors."""

def _error(code):
    raise NativeScopeError(code)

def _same(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b

def _keys(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        _error('NATIVE_FIXED_FIELDS_REQUIRED')

def _id(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,180}', value) is not None

def _sha(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        _error('NATIVE_PIN_FILE_INVALID')
    return hashlib.sha256(path.read_bytes()).hexdigest()

@dataclass(frozen=True)
class NativePhaseBinding:
    task_id: str
    attempt_id: str
    request_id: str
    phase: str
    workspace: Path
    input_text: str = field(repr=False)
    input_source_sha256: str
    model_id: str = 'gpt-6.1-sol'
    provider_id: str = _ROUTE

    def __post_init__(self):
        if not all(_id(v) for v in (self.task_id, self.attempt_id, self.request_id, self.model_id, self.provider_id)):
            _error('NATIVE_BINDING_INVALID')
        if (self.phase not in ('preparation', 'planning', 'finalization', 'execution', 'review', 'takeover')
                or not self.model_id.startswith('gpt-') or self.provider_id != _ROUTE):
            _error('NATIVE_BINDING_INVALID')
        if (type(self.input_text) is not str or (not self.input_text.strip() and self.phase != 'preparation')
                or len(self.input_text.encode()) > 1_048_576):
            _error('NATIVE_TEXT_INPUT_REQUIRED')
        if hashlib.sha256(self.input_text.encode()).hexdigest() != self.input_source_sha256:
            _error('NATIVE_INPUT_HASH_MISMATCH')
        if not isinstance(self.workspace, Path) or not self.workspace.is_dir() or self.workspace.is_symlink():
            _error('NATIVE_WORKSPACE_INVALID')
        for path in (self.workspace, *self.workspace.parents):
            attrs = path.lstat()
            if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, 'st_file_attributes', 0) & 0x400:
                _error('NATIVE_WORKSPACE_INVALID')
        object.__setattr__(self, 'workspace', self.workspace.resolve(strict=True))

@dataclass(frozen=True, init=False)
class OwnedNativeContext:
    binding: NativePhaseBinding
    nonce: str
    transport_kind: str

    def __init__(self, binding, nonce, transport_kind, *, _mint=None):
        if _mint is not _MINT:
            _error('NATIVE_PRIVATE_CONTEXT_REQUIRED')
        object.__setattr__(self, 'binding', binding)
        object.__setattr__(self, 'nonce', nonce)
        object.__setattr__(self, 'transport_kind', transport_kind)

@dataclass(frozen=True, init=False)
class VerifiedScopeSeal:
    context_nonce: str
    entry_sha256: str
    control_policy_sha256: str
    input_source_sha256: str
    thread_id: str
    boundary: str
    os_sandbox_verified: bool

    def __init__(self, context, thread_id, *, _mint=None):
        if _mint is not _MINT or type(context) is not OwnedNativeContext or context.transport_kind != 'native':
            _error('NATIVE_PRIVATE_SEAL_REQUIRED')
        values = {'context_nonce': context.nonce, 'entry_sha256': OFFICIAL_ENTRY_SHA256,
            'control_policy_sha256': CONTROL_POLICY_SHA256, 'input_source_sha256': context.binding.input_source_sha256,
            'thread_id': thread_id, 'boundary': _SOURCE['boundary'], 'os_sandbox_verified': False}
        for name, value in values.items():
            object.__setattr__(self, name, value)

@dataclass(frozen=True, init=False)
class FixtureScopeSeal:
    context_nonce: str
    scope_enforced: bool
    os_sandbox_verified: bool

    def __init__(self, context=None, *, _mint=None):
        if _mint is not _MINT or type(context) is not OwnedNativeContext:
            _error('NATIVE_PRIVATE_FIXTURE_SEAL_REQUIRED')
        object.__setattr__(self, 'context_nonce', context.nonce)
        object.__setattr__(self, 'scope_enforced', False)
        object.__setattr__(self, 'os_sandbox_verified', False)

class NativeScopeEnforcer:
    def __init__(self):
        self._context = self._origin = self._seal = None
        self._stage = 'UNBOUND'
        self._pending = None
        self._baseline_keys = self._config = None
        self._thread_id = self._turn_id = None
        self._turns = 0
        self._launched = None

    def open_fixture_phase(self, binding, *, metadata_stage='restricted'):
        return self._open(binding, 'fixture', metadata_stage)

    def _open(self, binding, transport_kind, metadata_stage):
        if ((self._context is not None and self._stage != 'CLOSED_VERIFIED')
                or type(binding) is not NativePhaseBinding or metadata_stage not in ('baseline', 'restricted')):
            _error('NATIVE_CONTEXT_ALREADY_BOUND_OR_INVALID')
        self._seal = self._pending = self._baseline_keys = self._config = None
        self._thread_id = self._turn_id = None
        self._turns = 0
        self._context = OwnedNativeContext(binding, uuid4().hex, transport_kind, _mint=_MINT)
        self._stage = 'OPEN_BASELINE' if metadata_stage == 'baseline' else 'OPEN_RESTRICTED'
        return self._context

    def start_native_phase(self, manager, binding, entry_path):
        """The issuer owns the exact launch, not a caller's process/JSON claim."""
        from app.runtime.processes import ProcessManager
        if type(manager) is not ProcessManager or type(binding) is not NativePhaseBinding:
            _error('NATIVE_MANAGED_PIPE_REQUIRED')
        if self._context is not None and self._stage != 'CLOSED_VERIFIED':
            _error('NATIVE_CONTEXT_ALREADY_BOUND_OR_INVALID')
        entry = Path(entry_path).resolve(strict=True)
        worker = Path(__file__).with_name('scoped_codex_worker.py').resolve(strict=True)
        if _sha(entry) != OFFICIAL_ENTRY_SHA256:
            _error('NATIVE_OFFICIAL_ENTRY_MISMATCH')
        worker_sha = _sha(worker)
        if worker_sha != WORKER_SOURCE_SHA256:
            _error('NATIVE_WORKER_SOURCE_PIN_MISMATCH')
        handle = manager.start(binding.task_id, binding.attempt_id,
            [sys._base_executable, str(worker)], binding.workspace, step_id=binding.request_id)
        self._launched = (manager, handle, binding, entry, worker_sha)
        return handle, self.bind_native_phase(manager, handle, binding, entry)

    def bind_native_phase(self, manager, handle, binding, entry_path):
        from app.runtime.processes import ProcessHandle, ProcessManager
        if type(manager) is not ProcessManager or type(handle) is not ProcessHandle or type(binding) is not NativePhaseBinding:
            _error('NATIVE_MANAGED_PIPE_REQUIRED')
        if (self._launched is None or self._launched[0] is not manager or self._launched[1] is not handle
                or self._launched[2] is not binding):
            _error('NATIVE_OWNED_LAUNCH_REQUIRED')
        if (handle.task_id, handle.attempt_id, handle.cwd.resolve()) != (binding.task_id, binding.attempt_id, binding.workspace):
            _error('NATIVE_MANAGED_BINDING_MISMATCH')
        worker = Path(__file__).with_name('scoped_codex_worker.py').resolve(strict=True)
        entry = Path(entry_path).resolve(strict=True)
        if _sha(entry) != OFFICIAL_ENTRY_SHA256:
            _error('NATIVE_OFFICIAL_ENTRY_MISMATCH')
        if (entry != self._launched[3] or _sha(worker) != self._launched[4]
                or self._launched[4] != WORKER_SOURCE_SHA256):
            _error('NATIVE_SOURCE_CHANGED')
        self._origin = (manager, handle, entry, worker, self._launched[4])
        self._check_live_origin()
        return self._open(binding, 'native', 'baseline')

    def _check_live_origin(self):
        if self._origin is None:
            _error('NATIVE_MANAGED_PIPE_REQUIRED')
        manager, handle, entry, worker, worker_sha = self._origin
        with manager._lock:
            if (manager._closed or not any(h is handle for h in manager._active.values()) or handle.pid <= 0
                    or handle._done.is_set() or handle._error is not None
                    or not handle._native.get('job') or not handle._native.get('process')):
                _error('NATIVE_LIVE_MANAGED_PIPE_REQUIRED')
        snapshot = manager.resource_snapshot()
        if snapshot.get('failed_cleanups') != 0 or snapshot.get('query_errors'):
            _error('NATIVE_LOCAL_CLEANUP_UNKNOWN')
        if _sha(entry) != OFFICIAL_ENTRY_SHA256 or _sha(worker) != worker_sha:
            _error('NATIVE_SOURCE_CHANGED')

    def _owned(self, context):
        if type(context) is not OwnedNativeContext or context is not self._context:
            _error('NATIVE_FOREIGN_CONTEXT')
        if self._stage in ('CLOSED', 'CLOSED_VERIFIED', 'REVOKED', 'UNSUBSCRIBED'):
            _error('NATIVE_CONTEXT_REVOKED')
        if context.transport_kind == 'native':
            self._check_live_origin()
        return context.binding

    def authorize_rpc(self, method, params, owned_context):
        try:
            return self._authorize_rpc(method, params, owned_context)
        except NativeScopeError:
            # Every attempted scope expansion is terminal for this private phase.
            if owned_context is self._context and self._stage != 'CLOSED_VERIFIED':
                self._seal = self._pending = None
                self._stage = 'REVOKED'
            raise

    def _authorize_rpc(self, method, params, owned_context):
        binding = self._owned(owned_context)
        if type(method) is not str or method not in _METHODS:
            _error('NATIVE_RPC_FORBIDDEN')
        if self._pending is not None:
            _error('NATIVE_RPC_REPLY_REQUIRED')
        cwd = str(binding.workspace)
        if method == 'initialize':
            if self._stage not in ('OPEN_BASELINE', 'OPEN_RESTRICTED', 'BASELINED'):
                _error('NATIVE_RPC_SEQUENCE_INVALID')
            expected = {'clientInfo': {'name': 'workbench_scoped_runtime', 'title': 'Scoped native runtime', 'version': '0.1.0'},
                'capabilities': {'experimentalApi': True}}
            if not _same(params, expected):
                _error('NATIVE_FIXED_PARAMS_REQUIRED')
        elif method == 'initialized':
            if self._stage not in ('INIT_BASELINE', 'INIT_RESTRICTED') or not _same(params, {}):
                _error('NATIVE_RPC_SEQUENCE_INVALID')
            self._stage = 'INITIALIZED_BASELINE' if self._stage == 'INIT_BASELINE' else 'INITIALIZED_RESTRICTED'
            return None
        elif method == 'config/read':
            if self._stage not in ('INITIALIZED_BASELINE', 'INITIALIZED_RESTRICTED', 'PREPARED'):
                _error('NATIVE_RPC_SEQUENCE_INVALID')
            if not _same(params, {'cwd': cwd, 'includeLayers': False}):
                _error('NATIVE_FIXED_PARAMS_REQUIRED')
        elif method == 'thread/start':
            if self._stage != 'CONFIGURED':
                _error('NATIVE_RPC_SEQUENCE_INVALID')
            expected = {'cwd': cwd, 'model': binding.model_id, 'modelProvider': binding.provider_id,
                'allowProviderModelFallback': False, 'approvalPolicy': 'never', 'sandbox': 'read-only',
                'ephemeral': True, 'environments': [], 'dynamicTools': [], 'experimentalRawEvents': True}
            if not _same(params, expected):
                _error('NATIVE_FIXED_PARAMS_REQUIRED')
        elif method == 'thread/read':
            if self._stage not in ('THREAD_STARTED', 'PREPARED', 'RECHECK_CONFIGURED'):
                _error('NATIVE_RPC_SEQUENCE_INVALID')
            if not _same(params, {'threadId': self._thread_id, 'includeTurns': False}):
                _error('NATIVE_FIXED_PARAMS_REQUIRED')
        elif method == 'turn/start':
            if self._stage != 'PREPARED' or self._seal is None or self._turns != 0:
                _error('NATIVE_SINGLE_PREPARED_TURN_REQUIRED')
            _keys(params, ('threadId', 'cwd', 'model', 'approvalPolicy', 'sandboxPolicy', 'effort', 'environments', 'input', 'outputSchema'))
            expected = {'threadId': self._thread_id, 'cwd': cwd, 'model': binding.model_id,
                'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False},
                'effort': 'low', 'environments': [], 'input': [{'type': 'text', 'text': binding.input_text, 'text_elements': []}]}
            if not all(_same(params[k], v) for k, v in expected.items()):
                _error('NATIVE_STICKY_TEXT_ONLY_TURN_REQUIRED')
            if type(params['outputSchema']) is not dict:
                _error('NATIVE_FIXED_PARAMS_REQUIRED')
            self._turns = 1
        elif method == 'turn/interrupt':
            if self._stage != 'TURN_ACTIVE' or not self._turn_id or not _same(params, {'threadId': self._thread_id, 'turnId': self._turn_id}):
                _error('NATIVE_OWNED_TURN_REQUIRED')
        elif method == 'thread/unsubscribe':
            if self._stage not in ('THREAD_STARTED', 'PREPARED', 'TURN_ACTIVE') or not _same(params, {'threadId': self._thread_id}):
                _error('NATIVE_OWNED_THREAD_REQUIRED')
        self._pending = (method, self._stage)
        return None

    def _config_result(self, result, context, baseline):
        _keys(result, ('controls', 'mcp_servers', 'configured_provider_id', 'configured_model_id'))
        servers = result['mcp_servers']
        if type(servers) is not dict or len(servers) > 128:
            _error('NATIVE_MCP_SNAPSHOT_INVALID')
        for name, server in servers.items():
            if type(name) is not str or not name or len(name) > 256:
                _error('NATIVE_MCP_SNAPSHOT_INVALID')
            _keys(server, ('enabled',))
            if type(server['enabled']) is not bool:
                _error('NATIVE_MCP_SNAPSHOT_INVALID')
            if not baseline and server['enabled'] is not False:
                _error('NATIVE_MCP_NOT_DISABLED')
        if baseline:
            self._baseline_keys = frozenset(servers)
            return
        if self._baseline_keys is not None and frozenset(servers) != self._baseline_keys:
            _error('NATIVE_MCP_KEY_SET_CHANGED')
        if context.transport_kind == 'native' and self._baseline_keys is None:
            _error('NATIVE_BASELINE_SNAPSHOT_REQUIRED')
        if not _same(result['controls'], _CONTROLS):
            _error('NATIVE_EFFECTIVE_CONTROLS_MISMATCH')
        if (result['configured_provider_id'] != context.binding.provider_id
                or result['configured_model_id'] not in (None, context.binding.model_id)):
            _error('NATIVE_CONFIGURED_ROUTE_MISMATCH')
        if self._config is not None and not _same(result, self._config):
            _error('NATIVE_EFFECTIVE_CONFIG_CHANGED')
        self._config = copy.deepcopy(result)

    def _thread_result(self, result, context, require_policy):
        _keys(result, ('thread',), ('approvalPolicy', 'sandbox', 'model', 'modelProvider'))
        thread = result['thread']
        _keys(thread, ('id', 'ephemeral', 'environments'), ('turns',))
        if (not _id(thread['id']) or thread['ephemeral'] is not True or not _same(thread['environments'], [])
                or ('turns' in thread and not _same(thread['turns'], []))):
            _error('NATIVE_EMPTY_EPHEMERAL_THREAD_REQUIRED')
        if self._thread_id is not None and thread['id'] != self._thread_id:
            _error('NATIVE_FOREIGN_THREAD')
        if ((require_policy or 'approvalPolicy' in result) and result.get('approvalPolicy') != 'never'
                or (require_policy or 'sandbox' in result)
                    and not _same(result.get('sandbox'), {'type': 'readOnly', 'networkAccess': False})):
            _error('NATIVE_READONLY_THREAD_REQUIRED')
        if ('model' in result and result['model'] != context.binding.model_id
                or 'modelProvider' in result and result['modelProvider'] != context.binding.provider_id):
            _error('NATIVE_CONFIGURED_ROUTE_MISMATCH')
        self._thread_id = thread['id']

    def observe_rpc_response(self, method, result, owned_context):
        self._owned(owned_context)
        if self._pending is None or method != self._pending[0]:
            _error('NATIVE_UNSOLICITED_RPC_RESPONSE')
        previous = self._pending[1]
        try:
            if method == 'initialize':
                if type(result) is not dict:
                    _error('NATIVE_RPC_RESULT_INVALID')
                self._stage = 'INIT_BASELINE' if previous == 'OPEN_BASELINE' else 'INIT_RESTRICTED'
            elif method == 'config/read':
                baseline = previous == 'INITIALIZED_BASELINE'
                self._config_result(result, owned_context, baseline)
                self._stage = 'BASELINED' if baseline else 'RECHECK_CONFIGURED' if previous == 'PREPARED' else 'CONFIGURED'
            elif method in ('thread/start', 'thread/read'):
                self._thread_result(result, owned_context, method == 'thread/start')
                self._stage = 'THREAD_STARTED' if method == 'thread/start' else 'PREPARED'
                if method == 'thread/read':
                    self._seal = (VerifiedScopeSeal(owned_context, self._thread_id, _mint=_MINT)
                        if owned_context.transport_kind == 'native' else FixtureScopeSeal(owned_context, _mint=_MINT))
            elif method == 'turn/start':
                _keys(result, ('turn',))
                _keys(result['turn'], ('id', 'status'))
                if not _id(result['turn']['id']) or result['turn']['status'] not in ('inProgress', 'in_progress', 'completed'):
                    _error('NATIVE_OWNED_TURN_REQUIRED')
                self._turn_id = result['turn']['id']
                self._stage = 'TURN_ACTIVE'
            elif method in ('turn/interrupt', 'thread/unsubscribe'):
                if type(result) is not dict:
                    _error('NATIVE_RPC_RESULT_INVALID')
                if method == 'thread/unsubscribe':
                    self._stage = 'UNSUBSCRIBED'
        except NativeScopeError:
            self._seal = None
            self._stage = 'REVOKED'
            raise
        finally:
            self._pending = None
        return self._seal

    def scope_seal(self, context):
        self._owned(context)
        if self._seal is None:
            _error('NATIVE_SCOPE_NOT_PREPARED')
        return self._seal

    def require_verified(self, entry_hash, control_policy_hash):
        if entry_hash != OFFICIAL_ENTRY_SHA256 or control_policy_hash != CONTROL_POLICY_SHA256:
            _error('NATIVE_SOURCE_POLICY_PIN_MISMATCH')
        if self._context is None or type(self._seal) is not VerifiedScopeSeal:
            _error('NATIVE_FIXTURE_OR_UNPREPARED_SCOPE')
        if self._stage == 'CLOSED_VERIFIED':
            self._check_closed_origin()
            return None
        self._owned(self._context)
        if self._stage not in ('PREPARED', 'TURN_ACTIVE') or (self._pending is not None
                and not (self._pending[0] == 'turn/start' and self._turns == 1)):
            _error('NATIVE_SCOPE_NOT_PREPARED')
        return None

    def close(self, context, cleanup_complete):
        if type(context) is not OwnedNativeContext or context is not self._context:
            _error('NATIVE_FOREIGN_CONTEXT')
        eligible = self._seal is not None and self._stage in ('PREPARED', 'TURN_ACTIVE', 'UNSUBSCRIBED')
        self._pending = None
        if cleanup_complete is True and eligible:
            try:
                if context.transport_kind == 'native':
                    self._check_closed_origin()
                self._stage = 'CLOSED_VERIFIED'
                return
            except NativeScopeError:
                self._seal = None
                self._stage = 'REVOKED'
                raise
        self._seal = None
        self._stage = 'CLOSED' if cleanup_complete is True else 'REVOKED'

    def _check_closed_origin(self):
        if self._origin is None:
            _error('NATIVE_MANAGED_PIPE_REQUIRED')
        manager, handle, entry, worker, worker_sha = self._origin
        snapshot = manager.resource_snapshot()
        if (not manager._closed or any(snapshot.get(k) != 0 for k in
                ('running', 'open_handles', 'temp_dirs', 'failed_cleanups')) or snapshot.get('query_errors')):
            _error('NATIVE_LOCAL_CLEANUP_UNKNOWN')
        if _sha(entry) != OFFICIAL_ENTRY_SHA256 or _sha(worker) != worker_sha:
            _error('NATIVE_SOURCE_CHANGED')
