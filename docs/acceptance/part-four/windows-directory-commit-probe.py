"""Actual Windows handle/share behavior in an owned disposable fixture tree."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report_root = Path(__file__).resolve().parent
    if os.name != 'nt':
        return dict(platform=os.name, executed=False, reason='Windows API unavailable')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    invalid = ctypes.c_void_p(-1).value
    handles = set()
    def hold(path):
        # GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, OPEN_EXISTING.
        handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
        if handle == invalid:
            raise ctypes.WinError(ctypes.get_last_error())
        handles.add(handle)
        return handle
    def release(handle):
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())
        handles.remove(handle)
    def attempt(source, target):
        try:
            source.rename(target)
            return dict(renamed=True)
        except OSError as error:
            return dict(renamed=False, error_type=type(error).__name__, errno=error.errno,
                winerror=getattr(error, 'winerror', None))
    results = []
    # Verify the cleanup target before TemporaryDirectory can recursively remove it.
    fixture = TemporaryDirectory(prefix='directory-commit-', dir=report_root)
    root = Path(fixture.name).resolve()
    root.relative_to(report_root)
    try:
        live = root/'live'
        live.mkdir()
        original = live/'retained.bin'
        original.write_bytes(b'original live data must remain unchanged')
        live_hash = digest(original)
        for name, release_after_attempt in [('held_then_released', True), ('continuously_held', False)]:
            parent = root/name
            parent.mkdir()
            pending, committed = parent/'.pending-fixture', parent/'backup-fixture'
            pending.mkdir()
            source = pending/'workbench.sqlite3'
            source.write_bytes(b'local immutable snapshot fixture')
            snapshot_hash = digest(source)
            handle = hold(source)
            held_results = []
            try:
                for _ in range(1 if release_after_attempt else 3):
                    held_results.append(attempt(pending, committed))
                retained_while_held = pending.is_dir() and not committed.exists() and digest(source)==snapshot_hash
            finally:
                release(handle)
            after_release = attempt(pending, committed) if release_after_attempt else None
            stored = committed/'workbench.sqlite3' if committed.exists() else source
            results.append(dict(case=name, held_attempts=held_results,
                source_retained_while_held=retained_while_held, after_release=after_release,
                snapshot_bytes_unchanged=digest(stored)==snapshot_hash,
                live_data_unchanged=digest(original)==live_hash, handles_remaining=len(handles)))
        parent = root/'existing_target'
        parent.mkdir()
        pending, committed = parent/'.pending-fixture', parent/'backup-fixture'
        pending.mkdir(); committed.mkdir()
        (pending/'snapshot.bin').write_bytes(b'pending snapshot')
        (committed/'retained.bin').write_bytes(b'existing backup')
        source_hash, target_hash = digest(pending/'snapshot.bin'), digest(committed/'retained.bin')
        refused = attempt(pending, committed)
        results.append(dict(case='existing_target', attempt=refused,
            source_unchanged=digest(pending/'snapshot.bin')==source_hash,
            existing_target_unchanged=digest(committed/'retained.bin')==target_hash,
            live_data_unchanged=digest(original)==live_hash))
    finally:
        for handle in tuple(handles):
            release(handle)
        root.resolve().relative_to(report_root)
        fixture.cleanup()
    return dict(platform=os.name, executed=True, source_and_tests_modified=False,
        provider_or_model_calls=0, external_scanner_cause='not_established',
        results=results, handles_remaining=len(handles), fixture_removed=not root.exists())


if __name__ == '__main__':
    print(json.dumps(main(), ensure_ascii=True, indent=2))
