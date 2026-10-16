"""Bounded local directory commits; real Windows sharing locks, no providers."""
import ctypes
from ctypes import wintypes
import errno
import hashlib
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest


def hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob('*') if path.is_file() and not path.name.endswith(('-wal', '-shm'))}


@pytest.fixture
def windows_handle():
    if os.name != 'nt':
        pytest.skip('Actual Windows share-delete regression')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handles = set()
    def acquire(path):
        handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        handles.add(handle)
        def release():
            if handle in handles:
                assert kernel.CloseHandle(handle)
                handles.remove(handle)
        return release
    yield acquire
    for handle in tuple(handles):
        assert kernel.CloseHandle(handle)
        handles.remove(handle)
    assert not handles


def test_windows_commit_retries_same_owned_directory_after_handle_release(client, tmp_path, monkeypatch, windows_handle):
    from app.storage.backup import create_backup, validate_backup
    root = client.app.state.settings.data_root
    before = hashes(root)
    original = Path.rename
    attempts = []
    def occupied_once(source, destination):
        attempts.append((source, Path(destination)))
        release = windows_handle(source/'workbench.sqlite3') if len(attempts)==1 else lambda: None
        try:
            return original(source, destination)
        finally:
            release()
    monkeypatch.setattr(Path, 'rename', occupied_once)
    committed = create_backup(root, tmp_path.parent/(tmp_path.name+'-backups'))
    assert validate_backup(committed)['verified'] is True
    assert len(attempts)==2 and attempts[0]==attempts[1]
    assert not attempts[0][0].exists() and committed==attempts[0][1]
    assert hashes(root)==before


@pytest.mark.parametrize('operation', ['import', 'restore'])
def test_import_and_restore_retry_only_the_same_verified_directory(client, tmp_path, monkeypatch, windows_handle, operation):
    from app.storage.backup import create_backup, export_backup, import_backup, validate_backup
    from app.storage.restore import restore_backup
    root = client.app.state.settings.data_root
    staging = tmp_path.parent/(tmp_path.name+'-backups')
    bundle = create_backup(root, staging)
    archive = export_backup(bundle)
    before = hashes(root)
    original = Path.rename
    attempts = []
    def occupied_once(source, destination):
        attempts.append((source, Path(destination)))
        release = windows_handle(source/'workbench.sqlite3') if len(attempts)==1 else lambda: None
        try:
            return original(source, destination)
        finally:
            release()
    monkeypatch.setattr(Path, 'rename', occupied_once)
    if operation=='import':
        assert validate_backup(import_backup(archive, staging))['verified'] is True
    else:
        result = restore_backup(bundle, root)
        assert result['verified'] and result['source_retained']
    assert len(attempts)==2 and attempts[0]==attempts[1] and not attempts[0][0].exists()
    assert hashes(root)==before


def test_nonsharing_commit_failure_cleans_owned_staging_without_touching_live_data(client, tmp_path, monkeypatch):
    from app.storage.backup import create_backup
    root = client.app.state.settings.data_root
    before = hashes(root)
    staging = tmp_path.parent/(tmp_path.name+'-backups')
    calls = []
    def denied(source, destination):
        calls.append((source, destination))
        raise sharing_error(87)
    monkeypatch.setattr(Path, 'rename', denied)
    with pytest.raises(OSError):
        create_backup(root, staging)
    assert len(calls)==1 and not list(staging.glob('.pending-*'))
    assert hashes(root)==before


def test_windows_commit_busy_is_bounded_and_retains_owned_pending(client, tmp_path, monkeypatch, windows_handle):
    from app.storage.backup import create_backup
    root = client.app.state.settings.data_root
    before = hashes(root)
    original = Path.rename
    attempts, releases, snapshots = [], [], []
    def occupied(source, destination):
        attempts.append((source, Path(destination)))
        if not releases:
            snapshots.append(hashes(source))
            releases.append(windows_handle(source/'workbench.sqlite3'))
        return original(source, destination)
    monkeypatch.setattr(Path, 'rename', occupied)
    try:
        with pytest.raises(OSError) as caught:
            create_backup(root, tmp_path.parent/(tmp_path.name+'-backups'))
        assert 1 < len(attempts) <= 5
        assert all(pair==attempts[0] for pair in attempts)
        assert getattr(caught.value, 'winerror', None)==5
        assert hashes(attempts[0][0])==snapshots[0] and not attempts[0][1].exists()
        assert hashes(root)==before
    finally:
        for release in releases:
            release()


def pending_case(tmp_path):
    parent = tmp_path/'staging'
    parent.mkdir()
    source, target = parent/('.pending-'+uuid4().hex), parent/('backup-'+uuid4().hex)
    source.mkdir()
    (source/'snapshot.bin').write_bytes(b'owned immutable snapshot')
    return source, target, parent


def sharing_error(code=5):
    error = PermissionError(errno.EACCES, 'PRIVATE_CANARY')
    if code is not None:
        error.winerror = code
    return error


@pytest.mark.parametrize('windows,code', [(False,5), (True,None), (True,87), (True,183)])
def test_commit_does_not_retry_other_platforms_or_unrelated_errors(tmp_path, monkeypatch, windows, code):
    from app.storage import directory_commit as module
    source, target, parent = pending_case(tmp_path)
    before = hashes(source)
    calls, waits = [], []
    error = sharing_error(code)
    def denied(path, destination):
        calls.append((path, destination))
        raise error
    monkeypatch.setattr(module, '_WINDOWS', windows)
    monkeypatch.setattr(Path, 'rename', denied)
    monkeypatch.setattr(module.time, 'sleep', waits.append)
    with pytest.raises(OSError) as caught:
        module.commit_owned_directory(source, target, parent)
    assert caught.value is error and len(calls)==1 and waits==[]
    assert hashes(source)==before and not target.exists()


@pytest.mark.parametrize('change', ['destination_appears', 'source_replaced'])
def test_commit_revalidates_ownership_and_destination_before_retry(tmp_path, monkeypatch, change):
    from app.storage import directory_commit as module
    source, target, parent = pending_case(tmp_path)
    original = Path.rename
    calls = []
    def denied(path, destination):
        calls.append((path, destination))
        raise sharing_error()
    def change_between_attempts(_):
        if change=='destination_appears':
            target.mkdir(); (target/'retained.bin').write_bytes(b'existing backup')
        else:
            original(source, parent/'retained-original')
            source.mkdir(); (source/'replacement.bin').write_bytes(b'foreign replacement')
    monkeypatch.setattr(module, '_WINDOWS', True)
    monkeypatch.setattr(Path, 'rename', denied)
    monkeypatch.setattr(module.time, 'sleep', change_between_attempts)
    with pytest.raises(module.DirectoryCommitBlocked):
        module.commit_owned_directory(source, target, parent)
    assert len(calls)==1
    if change=='destination_appears':
        assert (target/'retained.bin').read_bytes()==b'existing backup'
        assert (source/'snapshot.bin').read_bytes()==b'owned immutable snapshot'
    else:
        assert (parent/'retained-original'/'snapshot.bin').read_bytes()==b'owned immutable snapshot'
        assert (source/'replacement.bin').read_bytes()==b'foreign replacement' and not target.exists()


@pytest.mark.parametrize('invalid', ['unmanaged_name', 'other_parent', 'existing_target'])
def test_commit_refuses_unmanaged_scope_or_existing_destination(tmp_path, monkeypatch, invalid):
    from app.storage import directory_commit as module
    source, target, parent = pending_case(tmp_path)
    if invalid=='unmanaged_name':
        source = source.rename(parent/'ordinary-directory')
    elif invalid=='other_parent':
        target = tmp_path/'outside-destination'
    else:
        target.mkdir(); (target/'retained.bin').write_bytes(b'previous backup')
    before = hashes(tmp_path)
    def forbidden(*_):
        pytest.fail('unsafe commit must not reach rename')
    monkeypatch.setattr(Path, 'rename', forbidden)
    with pytest.raises(module.DirectoryCommitBlocked):
        module.commit_owned_directory(source, target, parent)
    assert hashes(tmp_path)==before


def test_commit_refuses_reparse_source_without_touching_original(tmp_path):
    if os.name!='nt':
        pytest.skip('Windows junction regression')
    from app.storage import directory_commit as module
    parent = tmp_path/'staging'; parent.mkdir()
    real = tmp_path/'retained'; real.mkdir(); (real/'source.bin').write_bytes(b'original')
    source, target = parent/('.pending-'+uuid4().hex), parent/('backup-'+uuid4().hex)
    result = subprocess.run(['cmd','/c','mklink','/J',str(source),str(real)], capture_output=True)
    assert result.returncode==0
    try:
        with pytest.raises(module.DirectoryCommitBlocked):
            module.commit_owned_directory(source, target, parent)
        assert (real/'source.bin').read_bytes()==b'original' and not target.exists()
    finally:
        source.rmdir()


@pytest.mark.parametrize('operation,status', [('create',409),('upload',422),('restore',409)])
def test_backup_api_busy_preserves_data_and_never_registers_or_freezes(client, tmp_path, monkeypatch, operation, status):
    from app.api import backups
    from app.storage.directory_commit import DirectoryCommitBusy
    before = hashes(client.app.state.settings.data_root)
    def busy(*_, **__):
        raise DirectoryCommitBusy(sharing_error())
    if operation=='create':
        monkeypatch.setattr(backups, 'create_backup', busy)
        response = client.post('/v1/backups', json={})
    elif operation=='upload':
        monkeypatch.setattr(backups, 'import_backup', busy)
        response = client.post('/v1/backups/import', content=b'PK fixture', headers={'Content-Type':'application/zip'})
    else:
        client.app.state.backup_refs['existing'] = tmp_path/'existing-backup'
        monkeypatch.setattr(backups, 'restore_backup', busy)
        response = client.post('/v1/backups/existing/restore', json={})
    assert response.status_code==status
    assert '占用' in response.json()['detail'] and '重试' in response.json()['detail']
    assert 'PRIVATE_CANARY' not in response.text and str(tmp_path) not in response.text
    assert client.app.state.storage_frozen is False and client.app.state.backup_restore_result is None
    assert set(client.app.state.backup_refs)==({'existing'} if operation=='restore' else set())
    assert hashes(client.app.state.settings.data_root)==before
