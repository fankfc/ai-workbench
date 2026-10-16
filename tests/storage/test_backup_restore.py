"""D051: real WAL snapshots and rejected restores preserve the live root."""
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest


def engines():
    from app.storage.backup import create_backup, validate_backup
    from app.storage.restore import restore_backup
    return create_backup, validate_backup, restore_backup


def tree_hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.name.endswith(('-wal', '-shm'))}


def test_snapshot_captures_committed_wal_and_only_referenced_blobs(client, tmp_path):
    create, validate, restore = engines()
    root = client.app.state.settings.data_root
    with closing(client.app.state.database.connect()) as keeper:
        keeper.execute('PRAGMA wal_autocheckpoint=0')
        cid = client.post('/v1/conversations', json={'title': '中文路径 WAL 快照'}).json()['id']
        uploaded = client.post(f'/v1/conversations/{cid}/attachments', content=b'referenced bytes',
                              headers={'Content-Type': 'application/octet-stream', 'X-Filename': 'source.txt'})
        assert uploaded.status_code == 201
        orphan = client.app.state.blobs.put(b'unreferenced temporary')
        (root / 'credentials.json').write_text('CREDENTIAL_CANARY')
        (root / 'cache').mkdir()
        (root / 'cache' / 'temporary.txt').write_text('CACHE_CANARY')
        bundle = create(root, tmp_path.parent / (tmp_path.name + '-备份'))
        report = validate(bundle)
        assert report['verified'] is True and report['schema_version'] == 4
        assert not (bundle / 'blobs' / orphan.sha256[:2] / orphan.sha256).exists()
        assert not any('CREDENTIAL_CANARY' in p.read_text(errors='ignore') for p in bundle.rglob('*') if p.is_file())
        assert not (bundle / 'cache').exists()
        result = restore(bundle, root)
        assert result['verified'] and result['source_retained'] and result['restart_required']
        restored = Path(result['destination'])
        with closing(sqlite3.connect(restored / 'workbench.sqlite3')) as c:
            assert c.execute('SELECT title FROM conversations WHERE id=?', (cid,)).fetchone()[0] == '中文路径 WAL 快照'
        assert result['credential_restored'] is False and result['reconnect_required'] is True
        assert root.exists()


@pytest.mark.parametrize('fault', ['hash', 'database', 'missing'])
def test_damaged_backup_never_modifies_live_data(client, tmp_path, fault):
    create, validate, restore = engines()
    root = client.app.state.settings.data_root
    cid = client.post('/v1/conversations', json={'title': '保留原数据'}).json()['id']
    uploaded = client.post(f'/v1/conversations/{cid}/attachments', content=b'persisted input',
                          headers={'Content-Type': 'application/octet-stream', 'X-Filename': 'source.txt'})
    assert uploaded.status_code == 201
    bundle = create(root, tmp_path.parent / (tmp_path.name + '-backups'))
    blob = next(p for p in (bundle / 'blobs').rglob('*') if p.is_file())
    if fault == 'hash': blob.write_bytes(b'corrupt')
    elif fault == 'missing': blob.unlink()
    else: (bundle / 'workbench.sqlite3').write_bytes(b'not sqlite')
    before = tree_hashes(root)
    with pytest.raises(ValueError): restore(bundle, root)
    assert tree_hashes(root) == before
    assert not list(root.parent.glob(root.name + '-restored-*'))


def test_disk_failure_and_copy_failure_keep_original(client, tmp_path, monkeypatch):
    create, validate, restore = engines()
    import app.storage.restore as module
    root = client.app.state.settings.data_root
    bundle = create(root, tmp_path.parent / (tmp_path.name + '-backups'))
    before = tree_hashes(root)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda p: type('Space', (), {'free': 0})())
    with pytest.raises(ValueError, match='SPACE'): restore(bundle, root)
    assert tree_hashes(root) == before


@pytest.mark.parametrize('member', ['../escape', 'C:/secret', 'blobs\\evil', 'tasks/t/a/input/CON.txt', 'tasks/t/a/input/name.'])
def test_untrusted_zip_paths_rejected_without_extraction(client, tmp_path, member):
    create, validate, restore = engines()
    from app.storage.backup import import_backup
    output = tmp_path.parent / (tmp_path.name + '-import')
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr(member, b'untrusted')
    with pytest.raises(ValueError): import_backup(payload.getvalue(), output)
    assert not (tmp_path.parent / 'escape').exists()


def test_link_and_extra_files_rejected(client, tmp_path):
    create, validate, restore = engines()
    root = client.app.state.settings.data_root
    bundle = create(root, tmp_path.parent / (tmp_path.name + '-backups'))
    (bundle / 'credentials.json').write_text('SECRET')
    with pytest.raises(ValueError): validate(bundle)


def test_api_exposes_opaque_ids_and_freezes_until_managed_restart(client, tmp_path):
    created = client.post('/v1/backups', json={})
    assert created.status_code == 201
    body = created.json()
    assert body['verified'] and 'path' not in body and 'destination' not in body
    assert client.post('/v1/backups', json={'path': 'C:/private'}).status_code == 422
    download = client.get('/v1/backups/' + body['backup_id'] + '/download')
    assert download.status_code == 200 and download.content.startswith(b'PK')
    imported = client.post('/v1/backups/import', content=download.content, headers={'Content-Type': 'application/zip'})
    assert imported.status_code == 201
    restored = client.post('/v1/backups/' + imported.json()['backup_id'] + '/restore', json={})
    assert restored.status_code == 200 and restored.json()['restart_required'] is True
    assert client.post('/v1/conversations', json={'title': '不能写旧目录'}).status_code == 409
    assert client.get('/v1/storage').status_code == 200


def test_api_bad_import_does_not_freeze_and_requires_authentication(client):
    assert client.post('/v1/backups/import', content=b'bad', headers={'Content-Type': 'application/zip'}).status_code == 422
    assert client.post('/v1/conversations', json={'title': '仍可写'}).status_code == 201
    assert client.post('/v1/backups', json={}, headers={'Authorization': 'Bearer wrong'}).status_code == 401


def test_incomplete_reference_is_rejected_even_with_an_updated_file_manifest(client, tmp_path):
    create, validate, restore = engines()
    root = client.app.state.settings.data_root
    cid = client.post('/v1/conversations', json={'title': 'References'}).json()['id']
    assert client.post(f'/v1/conversations/{cid}/attachments', content=b'input bytes',
                       headers={'Content-Type': 'application/octet-stream', 'X-Filename': 'source.txt'}).status_code == 201
    bundle = create(root, tmp_path.parent / (tmp_path.name + '-backups'))
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    item = next(item for item in manifest['files'] if item['path'].startswith('blobs/'))
    (bundle / item['path']).unlink()
    manifest['files'].remove(item)
    (bundle / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError): validate(bundle)


def test_restore_copy_error_rolls_back_staging_without_modifying_live_root(client, tmp_path, monkeypatch):
    create, validate, restore = engines()
    import app.storage.restore as module
    root = client.app.state.settings.data_root
    bundle = create(root, tmp_path.parent / (tmp_path.name + '-backups'))
    before = tree_hashes(root)
    def failure(*args): raise OSError('injected disk error')
    monkeypatch.setattr(module, 'copy_verified', failure)
    with pytest.raises(OSError): restore(bundle, root)
    assert tree_hashes(root) == before
    assert not list(root.parent.glob(root.name + '-restored-*'))


def test_zip_links_and_duplicate_case_paths_are_rejected(client, tmp_path):
    engines()
    import stat
    from app.storage.backup import import_backup
    payload = io.BytesIO()
    member = zipfile.ZipInfo('workbench.sqlite3')
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(payload, 'w') as archive: archive.writestr(member, b'outside-target')
    with pytest.raises(ValueError): import_backup(payload.getvalue(), tmp_path.parent / (tmp_path.name + '-import'))
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('workbench.sqlite3', b'one')
        archive.writestr('WORKBENCH.sqlite3', b'two')
    with pytest.raises(ValueError): import_backup(payload.getvalue(), tmp_path.parent / (tmp_path.name + '-import'))


def test_hardlinked_backup_database_is_rejected(client, tmp_path):
    create, validate, restore = engines()
    import os
    bundle = create(client.app.state.settings.data_root, tmp_path.parent / (tmp_path.name + '-backups'))
    original = bundle / 'workbench.sqlite3'
    linked = tmp_path / 'outside-link'
    os.link(original, linked)
    try:
        with pytest.raises(ValueError): validate(bundle)
    finally: linked.unlink()


def test_directory_junction_is_rejected_without_reading_target(client, tmp_path):
    create, validate, restore = engines()
    import os
    import subprocess
    if os.name != 'nt': pytest.skip('Windows junction regression')
    from app.storage.backup import reject_links
    target = tmp_path / 'target'
    target.mkdir()
    junction = tmp_path / 'linked'
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(target)], capture_output=True)
    assert result.returncode == 0
    try:
        with pytest.raises(ValueError, match='LINK'): reject_links(junction / 'file')
    finally: junction.rmdir()


def test_backup_refuses_running_workers_and_embedded_provider_credentials(client, tmp_path):
    create, validate, restore = engines()
    root = client.app.state.settings.data_root
    with closing(client.app.state.database.connect()) as c:
        c.execute("UPDATE provider_profiles SET provider_json='{" + '"api_key":"CANARY_SECRET"' + "}'")
    with pytest.raises(ValueError, match='CREDENTIAL'): create(root, tmp_path.parent / (tmp_path.name + '-backups'))
    with closing(client.app.state.database.connect()) as c: c.execute("UPDATE provider_profiles SET provider_json='{}'")
    cid = client.post('/v1/conversations', json={'title': 'Pending worker'}).json()['id']
    assert client.post(f'/v1/conversations/{cid}/turns', json={'text': 'test', 'client_request_id': 'request', 'provider_profile_id': 'fake-gpt'}).status_code == 202
    with closing(client.app.state.database.connect()) as c: c.execute("UPDATE task_runs SET lease_owner='active-worker',state='EXECUTING'")
    assert client.post('/v1/backups', json={}).status_code == 409


def test_derived_translation_cache_is_excluded_and_live_history_is_preserved(client, tmp_path):
    create, validate, restore = engines()
    root = client.app.state.settings.data_root
    cached = client.app.state.blobs.put(b'derived cache bytes')
    with closing(client.app.state.database.connect()) as c:
        c.execute('INSERT INTO translation_cache(cache_key,source_sha256,target_ref,target_sha256,blocks_json,qa_json,glossary_version,dependency_json) VALUES(?,?,?,?,?,?,?,?)',
                  ('derived', cached.sha256, 'blob:sha256:' + cached.sha256, cached.sha256, '{}', '{}', 'fixture', '{}'))
    bundle = create(root, tmp_path.parent / (tmp_path.name + '-backups'))
    with closing(sqlite3.connect(bundle / 'workbench.sqlite3')) as c:
        assert c.execute('SELECT COUNT(*) FROM translation_cache').fetchone()[0] == 0
    with closing(client.app.state.database.connect()) as c:
        assert c.execute('SELECT COUNT(*) FROM translation_cache').fetchone()[0] == 1
    assert not (bundle / 'blobs' / cached.sha256[:2] / cached.sha256).exists()


@pytest.mark.parametrize('context,tamper', [(context, tamper)
    for context in ['contract', 'planning', 'materials', 'language', 'profile', 'step', 'check', 'artifact']
    for tamper in ['remove_all', 'rewrite_source_hash'] if (context, tamper) != ('profile', 'rewrite_source_hash')])
def test_rehashed_archive_must_preserve_database_declared_task_inputs(client, tmp_path, context, tamper):
    """Neither the archive file list nor its source manifest is authoritative."""
    from app.runtime.workspace import WorkspaceManager
    from support.contracts import make_contract
    from app.contracts.artifacts import ArtifactVersion
    from app.storage.blobs import store_artifact
    create, validate, restore = engines()
    root = client.app.state.settings.data_root
    cid = client.post('/v1/conversations', json={'title': 'Paused source closure'}).json()['id']
    task = client.post(f'/v1/conversations/{cid}/turns', json={'text': 'retain source', 'client_request_id': 'source', 'provider_profile_id': 'fake-gpt'}).json()['task_id']
    with closing(client.app.state.database.connect()) as c:
        row = dict(c.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone())
    attempt = row['attempt_id']
    original = b'irreplaceable complete input'
    digest = hashlib.sha256(original).hexdigest()
    workspace = WorkspaceManager(root).create(task, attempt)
    workspace.ingest_source('material.txt', original)
    ref = 'input/material.txt'
    checkpoint = json.loads(row['checkpoint_json'])
    if context == 'contract':
        contract = make_contract(task, attempt, json.loads(row['route_snapshot_json'])['id'])
        contract['inputs'] = [{'id': 'SOURCE-1', 'ref': ref, 'sha256': digest}]
        checkpoint['task_contract'] = contract
    elif context == 'planning': checkpoint['a_planning'] = {'status': 'completed', 'source_hashes': {ref: digest}}
    elif context == 'materials': checkpoint['input_materials'] = [{'source_ref': ref, 'source_sha256': digest, 'parsed': True}]
    elif context == 'language': checkpoint['language_context'] = {'sources': [{'ref': ref, 'sha256': digest}]}
    elif context == 'profile':
        checkpoint['a_planning'] = {'status': 'needs_input'}
        checkpoint['task_profile'] = {'inputs': {'source_refs': [ref]}}
    with closing(client.app.state.database.connect()) as c:
        c.execute("UPDATE task_runs SET state='PAUSED',checkpoint_json=? WHERE task_id=?", (json.dumps(checkpoint), task))
        if context == 'step':
            c.execute("INSERT INTO steps(id,task_id,attempt_id,step_key,role,state,request_json) VALUES('source-step',?,?,'source-step','A','COMPLETED',?)", (task, attempt, json.dumps({'sources': [{'ref': ref, 'sha256': digest}]})))
        elif context == 'check':
            c.execute("INSERT INTO checks(id,task_id,attempt_id,check_kind,result,check_version,details_json) VALUES('source-check',?,?,'source.capture','pass','1.0',?)", (task, attempt, json.dumps({'source_ref': ref, 'source_sha256': digest})))
        elif context == 'artifact':
            data = b'pending derived artifact'; artifact_hash = hashlib.sha256(data).hexdigest()
            artifact = ArtifactVersion(id='pending-artifact', task_id=task, artifact_kind='document', language='en',
                immutable_uri=client.app.state.blobs.uri_for(artifact_hash), byte_sha256=artifact_hash,
                canonical_content_sha256=artifact_hash, source_version_id=None, origin_authors=['C'],
                canonical_issued_by='C', reviewed_by=[], rendered_by='C', a_response_ref=None, dependencies=[])
            store_artifact(c, client.app.state.blobs, data, artifact, attempt_id=attempt,
                provenance={'source_ref': ref, 'source_sha256': digest}, source_request={'input_refs': [ref]})
    bundle = create(root, tmp_path.parent / (tmp_path.name + '-backups'))
    assert validate(bundle)['verified'] is True
    relative = workspace.root.relative_to(root).as_posix()
    source_name, source_manifest = relative + '/' + ref, relative + '/.source-manifest.json'
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if tamper == 'remove_all':
        (bundle / source_name).unlink(); (bundle / source_manifest).unlink()
        manifest['files'] = [f for f in manifest['files'] if f['path'] not in {source_name, source_manifest}]
    else:
        changed = b'resigned replacement bytes'
        (bundle / source_name).write_bytes(changed)
        (bundle / source_manifest).write_text(json.dumps({ref: hashlib.sha256(changed).hexdigest()}), encoding='utf-8')
        for item in manifest['files']:
            if item['path'] in {source_name, source_manifest}:
                content = (bundle / item['path']).read_bytes()
                item.update(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    before = tree_hashes(root)
    with pytest.raises(ValueError): validate(bundle)
    with pytest.raises(ValueError): restore(bundle, root)
    assert tree_hashes(root) == before
    assert not list(root.parent.glob(root.name + '-restored-*'))
