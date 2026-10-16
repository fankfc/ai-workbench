"""Independent local schedules only; no installed CLI, auth, or model calls."""
import asyncio
import argparse
from contextlib import closing
import ctypes
from ctypes import wintypes
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time

from app.providers.phase_bridge import PhaseCapture
from app.providers.scoped_codex_runtime import ScopedCodexError, ScopedCodexRuntime
from app.providers import scoped_codex_worker as worker


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('review_fixture_contract', ROOT/'tests/contracts/test_scoped_codex_runtime.py')
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)
PATHS = [ROOT/'services/orchestrator/app/providers'/name for name in (
    'scoped_codex_runtime.py', 'scoped_codex_worker.py', 'native_scope.py')]


def hashes():
    return {str(path.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in PATHS}


def make_runtime(directory, scenario='pass', factory=None):
    peer = directory/'local_review_peer.py'
    # An explicit synthetic local marker confirms that the valid receipt was
    # actually emitted by this fixture. It contains no logs or provider data.
    source = FIXTURE.PEER.replace("def emit(v): print(json.dumps(v),flush=True)",
        "def emit(v):\n    if v.get('method')=='rawResponse/completed': Path('fixture-receipt.json').write_text(json.dumps(v['params']['usage']))\n    print(json.dumps(v),flush=True)")
    source = source.replace("elif method=='thread/start': result={'thread':thread(),'approvalPolicy':'never','sandbox':{'type':'readOnly','networkAccess':False}}",
        "elif method=='thread/start':\n        result={'thread':thread(),'approvalPolicy':'never','sandbox':{'type':'readOnly','networkAccess':False}}\n        if scenario=='thread_route_change': result.update(model='wrong-model',modelProvider='foreign-route')")
    peer.write_text(source, encoding='utf-8')
    command = lambda: [sys._base_executable, str(peer), str(Path(worker.__file__).parent), scenario]
    return ScopedCodexRuntime(FIXTURE.selected(), ledger_path=directory/'leases.sqlite3',
        workspace_root=directory, entry_manifest=directory/'never-read-native-manifest.json',
        worker_factory=factory or command, timeout_seconds=8), command


async def collect(runtime, request='first', events=None):
    events = [] if events is None else events
    async for event in runtime.invoke_text('fixed synthetic input', task_id='task', attempt_id='attempt',
            request_id=request, phase='planning', workspace=runtime.workspace_root, output_schema=FIXTURE.SCHEMA):
        events.append(event)
    return events


def states(directory):
    with closing(sqlite3.connect(directory/'leases.sqlite3')) as connection:
        return [dict(request=request, state=state) for request, state in connection.execute(
            'SELECT request,state FROM scoped_invocations ORDER BY request')]


def count_turns(directory):
    path = directory/'fixture-turns.txt'
    return len(path.read_text().splitlines()) if path.exists() else 0


async def boot_failure(directory):
    runtime, valid_factory = make_runtime(directory, factory=lambda: [])
    errors = []
    try:
        try:
            await collect(runtime)
        except ScopedCodexError as error:
            errors.append(error.reason_code)
        runtime._factory = valid_factory
        try:
            await collect(runtime, 'second')
        except ScopedCodexError as error:
            errors.append(error.reason_code)
        return dict(errors=errors, states=states(directory), fixture_turns=count_turns(directory),
            submitted_model_turns=runtime.diagnostics['submitted_model_turns'])
    finally:
        runtime.close()


async def ledger_handle_lifetime(directory):
    runtime, _ = make_runtime(directory)
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    def exclusively_readable():
        handle = api.CreateFileW(str(runtime.ledger_path), 0x80000000, 0, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            return dict(success=False, windows_error=ctypes.get_last_error())
        api.CloseHandle(handle)
        return dict(success=True, windows_error=0)
    runtime._claim('task', 'attempt', 'first')
    cleanup = runtime.close()
    before_gc = exclusively_readable()
    gc.collect()
    after_gc = exclusively_readable()
    return dict(exclusive_read_after_runtime_close=before_gc, exclusive_read_after_gc=after_gc,
        reported_cleanup_complete=cleanup.cleanup_complete, fixture_turns=count_turns(directory))


async def trailing_usage(directory):
    runtime, _ = make_runtime(directory, 'trailing_error')
    events = []
    error_code = None
    try:
        try:
            await collect(runtime, events=events)
        except ScopedCodexError as error:
            error_code = error.reason_code
        usage = json.loads((directory/'fixture-receipt.json').read_text())
        return dict(error=error_code, fixture_emitted_total_tokens=usage['totalTokens'],
            yielded_event_types=[type(event).__name__ for event in events],
            yielded_usage_receipts=sum(len(event.usage_receipts) for event in events if isinstance(event, PhaseCapture)),
            states=states(directory), cleanup_complete=runtime.last_cleanup.cleanup_complete)
    finally:
        runtime.close()


async def explicit_thread_route_change(directory):
    from app.providers.native_scope import NativeScopeEnforcer
    runtime, _ = make_runtime(directory, 'thread_route_change')
    runtime._enforcer = NativeScopeEnforcer()
    events = []
    error_code = None
    try:
        try:
            await collect(runtime, events=events)
        except ScopedCodexError as error:
            error_code = error.reason_code
        return dict(error=error_code, fixture_returned_changed_thread_model=True,
            fixture_returned_changed_thread_provider=True, fixture_turns=count_turns(directory),
            yielded_capture=any(isinstance(event, PhaseCapture) for event in events),
            cleanup_complete=runtime.last_cleanup.cleanup_complete)
    finally:
        runtime.close()


async def cancellation_before_parent_consumes_submitted(directory):
    runtime, _ = make_runtime(directory, 'hang')
    authorized_turn = threading.Event()
    release_write = threading.Event()
    original_authorize, original_write = runtime._authorize, runtime._write
    def authorize(packet, boot):
        original_authorize(packet, boot)
        if packet.get('method') == 'turn/start': authorized_turn.set()
    def delayed_write(packet):
        original_write(packet)
        # Delay only the return of a completed local pipe write. The worker is
        # free to send its request; this models valid thread scheduling delay.
        if authorized_turn.is_set() and packet.get('allow') is True:
            release_write.wait(timeout=5)
    runtime._authorize, runtime._write = authorize, delayed_write
    task = asyncio.create_task(collect(runtime))
    try:
        deadline = time.monotonic()+5
        while count_turns(directory) == 0 and time.monotonic() < deadline:
            await asyncio.sleep(.001)
        if count_turns(directory) != 1:
            raise RuntimeError('LOCAL_FIXTURE_NOT_SUBMITTED')
        observed_before_cancel = runtime.diagnostics['submitted_model_turns']
        cleanup = await runtime.cancel('task', 'attempt')
        release_write.set()
        try:
            await task
        except ScopedCodexError as error:
            error_code = error.reason_code
        else:
            error_code = None
        first_states = states(directory)
        runtime.close()
        fresh, _ = make_runtime(directory)
        try:
            await collect(fresh, 'second')
            second_allowed = True
        except ScopedCodexError:
            second_allowed = False
        finally:
            fresh.close()
        return dict(error=error_code, fixture_turns_before_cancel=1,
            parent_observed_submissions_before_cancel=observed_before_cancel,
            states_after_cancel=first_states, next_request_allowed=second_allowed,
            total_fixture_turns=count_turns(directory), cleanup_complete=cleanup.cleanup_complete)
    finally:
        release_write.set()
        if not task.done():
            await runtime.cancel('task', 'attempt')
            try:
                await task
            except ScopedCodexError:
                pass
        runtime.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--postfix', action='store_true')
    args = parser.parse_args()
    before = hashes()
    results = {}
    for name, probe in [('boot_failure', boot_failure), ('ledger_handle_lifetime', ledger_handle_lifetime), ('trailing_usage', trailing_usage),
                        ('thread_route_change', explicit_thread_route_change),
                        ('cancel_submission_race', cancellation_before_parent_consumes_submitted)]:
        with tempfile.TemporaryDirectory(prefix='scoped-review-') as temporary:
            results[name] = await probe(Path(temporary))
            # sqlite Connection context managers commit but do not close.
            # Collect source-held cycles before fixture directory teardown.
            gc.collect()
    output = dict(real_provider_starts=0, actual_external_model_submissions=0,
        production_files_changed_by_reviewer=False, source_hashes_before=before,
        source_hashes_after=hashes(), results=results)
    target = Path(__file__).with_name('scoped-runtime-independent-postfix.json' if args.postfix
        else 'scoped-runtime-independent-before.json')
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
