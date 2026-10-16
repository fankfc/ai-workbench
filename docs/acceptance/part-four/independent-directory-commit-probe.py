"""Independent Windows commit boundaries; all handles and fixtures are owned."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'services/orchestrator'))
from app.storage import directory_commit as module


def run():
    if os.name != 'nt':
        raise RuntimeError('This probe requires actual Windows handles')
    report_root = Path(__file__).resolve().parent
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handles = set()

    def hold(path):
        value = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
        if value == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        handles.add(value)
        return value

    def release(value):
        if value in handles:
            if not kernel.CloseHandle(value):
                raise ctypes.WinError(ctypes.get_last_error())
            handles.remove(value)

    actual_rename, actual_sleep = Path.rename, module.time.sleep
    snapshot = b'owned immutable commit probe snapshot'
    fixture = TemporaryDirectory(prefix='independent-commit-', dir=report_root)
    root = Path(fixture.name).resolve()
    root.relative_to(report_root)
    results = []
    try:
        live = root / 'retained-live.bin'
        live.write_bytes(b'old live bytes stay untouched')
        for case in ('released', 'continuously_held', 'destination_appears', 'source_replaced'):
            parent = root / case
            parent.mkdir()
            source, target = parent / ('.pending-' + uuid4().hex), parent / ('backup-' + uuid4().hex)
            source.mkdir()
            (source / 'snapshot.bin').write_bytes(snapshot)
            handle = hold(source / 'snapshot.bin')
            attempts, waits = [], []

            def rename(path, destination):
                if path == source and Path(destination) == target:
                    attempts.append((path, Path(destination)))
                return actual_rename(path, destination)

            def wait(delay):
                waits.append(delay)
                if len(waits) == 1 and case != 'continuously_held':
                    release(handle)
                    if case == 'destination_appears':
                        target.mkdir()
                        (target / 'retained.bin').write_bytes(b'previous target bytes')
                    elif case == 'source_replaced':
                        actual_rename(source, parent / 'retained-original')
                        source.mkdir()
                        (source / 'replacement.bin').write_bytes(b'foreign replacement bytes')
                actual_sleep(delay)

            caught = None
            try:
                with patch.object(Path, 'rename', rename), patch.object(module.time, 'sleep', wait):
                    module.commit_owned_directory(source, target, parent)
            except OSError as error:
                caught = error
            finally:
                release(handle)
            if case == 'released':
                passed = caught is None and len(attempts) == 2 and not source.exists() and (target / 'snapshot.bin').read_bytes() == snapshot
            elif case == 'continuously_held':
                passed = isinstance(caught, module.DirectoryCommitBusy) and caught.winerror == 5 and len(attempts) == 5 and not target.exists() and (source / 'snapshot.bin').read_bytes() == snapshot
            elif case == 'destination_appears':
                passed = isinstance(caught, module.DirectoryCommitBlocked) and not isinstance(caught, module.DirectoryCommitBusy) and len(attempts) == 1 and (target / 'retained.bin').read_bytes() == b'previous target bytes' and (source / 'snapshot.bin').read_bytes() == snapshot
            else:
                passed = isinstance(caught, module.DirectoryCommitBlocked) and not isinstance(caught, module.DirectoryCommitBusy) and len(attempts) == 1 and not target.exists() and (source / 'replacement.bin').read_bytes() == b'foreign replacement bytes' and (parent / 'retained-original' / 'snapshot.bin').read_bytes() == snapshot
            results.append(dict(case=case, passed=passed, rename_attempts=len(attempts), delays=waits,
                outcome=type(caught).__name__ if caught is not None else 'committed',
                same_paths=all(pair == attempts[0] for pair in attempts), handles_remaining=len(handles),
                live_data_unchanged=live.read_bytes() == b'old live bytes stay untouched'))
    finally:
        for value in tuple(handles):
            release(value)
        root.resolve().relative_to(report_root)
        fixture.cleanup()
    return dict(platform=os.name, source_and_tests_modified=False, provider_model_calls=0,
        helper_sha256=hashlib.sha256((REPO / 'services/orchestrator/app/storage/directory_commit.py').read_bytes()).hexdigest(),
        results=results, fixture_removed=not root.exists(), handles_remaining=len(handles),
        limits='Preflight and retry-boundary checks; not a portable atomic no-replace or OS sandbox claim.')


if __name__ == '__main__':
    report = run()
    Path(__file__).with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    if not all(row['passed'] and row['live_data_unchanged'] for row in report['results']):
        raise SystemExit(1)
