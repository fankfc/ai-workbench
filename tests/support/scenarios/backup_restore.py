"""D051 exercises product storage with real fake-provider bilingual outputs.

The former-schema fixture is populated from actual persisted pipeline records;
only external model messages and injected storage faults are substituted.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.storage.backup import create_backup, validate_backup, schema_chain, inspect_database, sha_file
from app.storage.restore import restore_backup
from app.storage.database import Database, transaction
from app.storage.migrations import migrate
from app.runtime.workspace import WorkspaceManager
from artifacts.seed_bundle import seed
from artifacts.helpers import prepare_bilingual
from app.documents.publish import BundlePublisher

OPTIONS_SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'fault': {'type': 'string', 'enum': ['none', 'missing_chinese_artifact', 'corrupt_database', 'hash_mismatch', 'disk_full', 'mixed_pair']},
    'provider_mode': {'const': 'fake'}}}
RESULT_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'required': ['restored_hashes', 'original_hashes', 'restore_state', 'source_untouched', 'credential_restored',
                 'schema_before', 'schema_after', 'files_verified', 'backup_size_bytes', 'elapsed_seconds',
                 'bilingual_formats', 'source_versions', 'paused_tasks', 'provider_boundary', 'reconnect_required', 'evidence_path'],
    'properties': {
        'restored_hashes': {'type': 'object', 'additionalProperties': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}},
        'original_hashes': {'type': 'object', 'additionalProperties': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}},
        'restore_state': {'enum': ['RESTORED', 'REJECTED']}, 'source_untouched': {'type': 'boolean'},
        'credential_restored': {'type': 'boolean'}, 'schema_before': {'type': 'integer'}, 'schema_after': {'type': ['integer', 'null']},
        'files_verified': {'type': 'integer', 'minimum': 0}, 'backup_size_bytes': {'type': 'integer', 'minimum': 0},
        'elapsed_seconds': {'type': 'number', 'minimum': 0}, 'bilingual_formats': {'type': 'array', 'items': {'type': 'string'}},
        'source_versions': {'type': 'integer', 'minimum': 0}, 'paused_tasks': {'type': 'integer', 'minimum': 0},
        'provider_boundary': {'const': 'fake'}, 'reconnect_required': {'type': 'boolean'}, 'evidence_path': {'type': 'string'}}}


def _former_schema_fixture(source, target):
    """Copy persisted v3 columns into the real known v3 schema, retaining bytes.

    This is fixture construction, not a production downgrade operation. No
    backup manifest/provenance check is waived by the storage engine.
    """
    target.mkdir()
    with closing(sqlite3.connect(source / 'workbench.sqlite3')) as reader, closing(Database(target / 'workbench.sqlite3').connect()) as c:
        migrate(c, schema_chain()[:3])
        triggers = c.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall()
        tables = [row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_version'")]
        c.execute('PRAGMA foreign_keys=OFF')
        with transaction(c):
            for name, _ in triggers: c.execute('DROP TRIGGER "' + name + '"')
            for table in tables:
                columns = [r[1] for r in c.execute('PRAGMA table_info("' + table + '")')]
                names = ','.join('"' + value + '"' for value in columns)
                rows = reader.execute('SELECT ' + names + ' FROM "' + table + '"').fetchall()
                c.executemany('INSERT INTO "' + table + '"(' + names + ') VALUES(' + ','.join('?' for _ in columns) + ')', rows)
            for _, sql in triggers: c.execute(sql)
        c.execute('PRAGMA foreign_keys=ON')
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
    for area in ('blobs', 'evidence', 'tasks'):
        if (source / area).is_dir(): shutil.copytree(source / area, target / area)
    assert inspect_database(target / 'workbench.sqlite3') == 3


def _live_hashes(root):
    with closing(Database(root / 'workbench.sqlite3').connect()) as c:
        logical = hashlib.sha256('\n'.join(c.iterdump()).encode()).hexdigest()
    return {'database_logical_sha256': logical, **{p.relative_to(root).as_posix(): sha_file(p)
        for p in root.rglob('*') if p.is_file() and not p.name.startswith('workbench.sqlite3')}}


def run(root: Path, options: dict) -> dict:
    started = time.monotonic()
    working = Path(root).resolve() / ('b' + uuid4().hex[:6]); working.mkdir(parents=True)
    modern, former = working / 'n', working / '中文'
    token = 'qa-backup-scenario-only'
    first = seed(modern, token, ['markdown', 'pdf'])
    # A new full canonical output gives immutable original/translation versions,
    # preserving the prior historical bundle and its exact old pairing.
    with TestClient(create_app(AppSettings(modern, token, 'fake', False)), headers={'Authorization': 'Bearer ' + token}) as client:
        with closing(client.app.state.database.connect()) as c:
            task = dict(c.execute('SELECT * FROM task_runs').fetchone())
        ctx = dict(client=client, cid=first['cid'], task=task['task_id'], attempt=task['attempt_id'], turn=task['turn_id'], route=json.loads(task['route_snapshot_json']))
        ready = prepare_bilingual(ctx, '# Report\n\nJanuary 30. February 50. Increase 20.\n')
        publisher = BundlePublisher(client.app.state.database.path, modern / 'evidence')
        second = publisher.stage(ctx['task'], ctx['attempt'], '1.0', ready['source'], ['markdown', 'pdf'], title='Report v2', translation_revision_id=ready['translation'], review_check_id=ready['review'])
        ready['machine'].transition(ctx['task'], ctx['attempt'], 'OUTPUT_PREPARING', 'READY', '1.0')
        publisher.publish(second, answer_releaser=ready['answer'].publish_in_transaction)
        paused = client.post(f'/v1/conversations/{ctx["cid"]}/turns', json={'text': '保留暂停任务材料。', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'paused'}).json()['task_id']
        with closing(client.app.state.database.connect()) as c:
            c.execute("UPDATE task_runs SET state='PAUSED' WHERE task_id=?", (paused,))
            attempt = c.execute('SELECT attempt_id FROM task_runs WHERE task_id=?', (paused,)).fetchone()[0]
        WorkspaceManager(modern).create(paused, attempt).ingest_source('中文材料.txt', '暂停任务原始材料'.encode())
    _former_schema_fixture(modern, former)
    (former / 'credentials.json').write_text('CREDENTIAL_RECONNECT_CANARY', encoding='utf-8')
    bundle = create_backup(former, working / 'b')
    verified = validate_backup(bundle)
    artifact_hashes = {name: digest for name, digest in verified['hashes'].items() if name != 'workbench.sqlite3'}
    before = _live_hashes(former)
    fault = options.get('fault', 'none')
    if fault == 'missing_chinese_artifact':
        with closing(sqlite3.connect(bundle / 'workbench.sqlite3')) as c:
            digest = c.execute("SELECT a.byte_sha256 FROM delivery_bundle_artifacts m JOIN artifact_revisions a ON a.id=m.artifact_id WHERE m.language='zh-CN' LIMIT 1").fetchone()[0]
        (bundle / 'blobs' / digest[:2] / digest).unlink()
    elif fault == 'corrupt_database': (bundle / 'workbench.sqlite3').write_bytes(b'injected corruption')
    elif fault == 'hash_mismatch':
        name = next(name for name in artifact_hashes if name.startswith('blobs/'))
        (bundle / name).write_bytes(b'injected hash mismatch')
    elif fault == 'mixed_pair':
        # Re-sign the file-level manifest so only the real bundle pairing gate
        # detects the mismatch. The engine never trusts ZIP hashes alone.
        with closing(sqlite3.connect(bundle / 'workbench.sqlite3')) as c:
            c.execute('DROP TRIGGER bundle_artifacts_immutable')
            c.execute("UPDATE delivery_bundle_artifacts SET artifact_pair_id='mixed-v1-v2' WHERE language='zh-CN'")
            # Restore the exact known trigger from a pristine v3 schema.
            with closing(sqlite3.connect(':memory:', isolation_level=None)) as pristine:
                migrate(pristine, schema_chain()[:3])
                sql = pristine.execute("SELECT sql FROM sqlite_master WHERE name='bundle_artifacts_immutable'").fetchone()[0]
            c.execute(sql); c.commit()
        manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
        item = next(item for item in manifest['files'] if item['path'] == 'workbench.sqlite3')
        item.update(sha256=sha_file(bundle / 'workbench.sqlite3'), size_bytes=(bundle / 'workbench.sqlite3').stat().st_size)
        (bundle / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    restored_hashes, state, schema_after, result = {}, 'REJECTED', None, None
    if fault == 'disk_full':
        import app.storage.restore as restore_module
        from unittest.mock import patch
        with patch.object(restore_module.shutil, 'disk_usage', return_value=type('Space', (), {'free': 0})()):
            try: result = restore_backup(bundle, former)
            except ValueError: pass
    else:
        try: result = restore_backup(bundle, former)
        except ValueError: pass
    if result is not None:
        destination = Path(result['destination'])
        restored_hashes = {name: sha_file(destination / name) for name in artifact_hashes}
        schema_after = result['schema_version']
        with TestClient(create_app(AppSettings(destination, token, 'fake', False)), headers={'Authorization': 'Bearer ' + token}) as reopened:
            assert len(reopened.get(f'/v1/conversations/{first["cid"]}/bundles').json()['items']) == 2
            assert all(not view['available'] for view in reopened.get('/v1/settings').json()['connections'])
        assert not (destination / 'credentials.json').exists()
        state = 'RESTORED'
    with closing(sqlite3.connect(former / 'workbench.sqlite3')) as c:
        source_versions = c.execute('SELECT COUNT(*) FROM a_document_responses').fetchone()[0]
        paused_tasks = c.execute("SELECT COUNT(*) FROM task_runs WHERE state='PAUSED'").fetchone()[0]
    evidence = working / 'restore-report.json'
    output = dict(restored_hashes=restored_hashes, original_hashes=artifact_hashes, restore_state=state,
        source_untouched=_live_hashes(former) == before, credential_restored=False, schema_before=3,
        schema_after=schema_after, files_verified=verified['files_verified'], backup_size_bytes=verified['size_bytes'],
        elapsed_seconds=time.monotonic()-started, bilingual_formats=['markdown', 'pdf'], source_versions=source_versions,
        paused_tasks=paused_tasks, provider_boundary='fake', reconnect_required=True, evidence_path=str(evidence))
    evidence.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return output
