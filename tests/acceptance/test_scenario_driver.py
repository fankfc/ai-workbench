import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from support.manifest import create_manifest, validate_manifest


def test_driver_requires_real_evidence(probe):
    r = probe('driver_contract', fault='deleted_evidence')
    assert r['service_pid'] > 0
    assert r['root_isolated'] is True
    assert r['manifest_valid'] is False
    assert r['process_cleaned'] is True


def test_three_runs_are_isolated_and_have_same_business_result(probe):
    results = [probe('driver_contract') for _ in range(3)]
    assert len({r['run_id'] for r in results}) == 3
    assert all(r['manifest_valid'] and r['process_cleaned'] for r in results)
    assert all(r['task_state'] == 'PUBLISHED' and r['answer_count'] == 1 for r in results)


@pytest.mark.parametrize('case,options', [('unknown_case', {}), ('driver_contract', {'unexpected': 1})])
def test_unknown_case_and_options_are_infrastructure_failures(tmp_path, case, options):
    r = subprocess.run([sys.executable, 'tests/support/scenario_driver.py', case,
                        '--root', str(tmp_path), '--options', json.dumps(options)],
                       capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert r.returncode == 2
    assert not r.stdout.strip()


def test_driver_refuses_non_test_directory(tmp_path):
    original = tmp_path / 'user.txt'
    original.write_text('preserve me', encoding='utf-8')
    r = subprocess.run([sys.executable, 'tests/support/scenario_driver.py', 'driver_contract',
                        '--root', str(tmp_path), '--options', '{}'],
                       capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert r.returncode != 0
    assert original.read_text(encoding='utf-8') == 'preserve me'
    assert list(tmp_path.iterdir()) == [original]


def test_manifest_detects_tampering_and_path_escape(tmp_path):
    path = tmp_path / 'evidence.txt'
    path.write_text('actual evidence', encoding='utf-8')
    manifest = create_manifest(tmp_path, [path], build_id='fixture-build')
    assert validate_manifest(tmp_path, manifest)['valid'] is True
    path.write_text('tampered', encoding='utf-8')
    assert validate_manifest(tmp_path, manifest)['valid'] is False
    manifest['files'][0]['path'] = '../outside.txt'
    assert validate_manifest(tmp_path, manifest)['valid'] is False


@pytest.mark.parametrize('case,options', [
    ('driver_contract', {}),
    ('backend_normal', {'provider_mode': 'fake'}),
    ('fault_matrix', {}),
    ('local_performance', {'history_tasks': 4}),
    ('feedback_bundle', {}),
    ('retention_glossary', {}),
    ('incident_rollback', {}),
])
def test_archive_manifest_is_valid_after_actual_cli_process_exits(tmp_path, case, options):
    completed = subprocess.run(
        [sys.executable, 'tests/support/scenario_driver.py', case, '--root', str(tmp_path),
         '--options', json.dumps(options)],
        capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((tmp_path / 'run-manifest.json').read_text(encoding='utf-8'))
    checked = validate_manifest(tmp_path, manifest)
    assert checked['valid'], checked['issues']
    database_entries = [entry for entry in manifest['files']
                        if entry['path'].endswith('.sqlite3')]
    assert database_entries
    assert not any(entry['path'].endswith(('.sqlite3-wal', '.sqlite3-shm'))
                   for entry in manifest['files'])
    if case == 'driver_contract':
        assert any(entry['path'] == 'service-leases.sqlite3' for entry in database_entries)
    for entry in database_entries:
        with closing(sqlite3.connect(tmp_path / entry['path'])) as connection:
            assert connection.execute('PRAGMA quick_check').fetchone() == ('ok',)
    assert validate_manifest(tmp_path, manifest)['valid']


def test_archive_checkpoints_all_sqlite_headers_and_preserves_committed_wal_rows(tmp_path):
    from support.scenario_driver import archive_files

    databases = [tmp_path / 'workbench.sqlite3', tmp_path / 'nested' / 'leases.sqlite3',
                 tmp_path / 'unusual.ledger']
    connections = []
    try:
        for database in databases:
            database.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(database)
            connections.append(connection)
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('CREATE TABLE evidence (value TEXT)')
            connection.execute("INSERT INTO evidence VALUES ('committed in WAL')")
            connection.commit()
            assert database.with_name(database.name + '-wal').stat().st_size > 0
        unrelated = tmp_path / 'source-wal'
        unrelated.write_text('ordinary evidence', encoding='utf-8')
        files = archive_files(tmp_path)
        assert all(database in files for database in databases)
        assert unrelated in files
        assert not any(path.name.endswith(('-wal', '-shm')) and path != unrelated for path in files)
        manifest = create_manifest(tmp_path, files)
    finally:
        for connection in connections:
            connection.close()
    assert validate_manifest(tmp_path, manifest)['valid']
    for database in databases:
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute('SELECT value FROM evidence').fetchall() == [('committed in WAL',)]
    assert validate_manifest(tmp_path, manifest)['valid']


def test_archive_refuses_busy_checkpoint_without_hiding_unmerged_wal(tmp_path):
    from support.scenario_driver import archive_files

    database = tmp_path / 'active.sqlite3'
    with closing(sqlite3.connect(database)) as writer, closing(sqlite3.connect(database)) as reader:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE evidence (value TEXT)')
        writer.commit()
        reader.execute('BEGIN')
        reader.execute('SELECT * FROM evidence').fetchall()
        writer.execute("INSERT INTO evidence VALUES ('must survive')")
        writer.commit()
        with pytest.raises(RuntimeError, match='QA_SQLITE_CHECKPOINT_BUSY'):
            archive_files(tmp_path)
        assert not (tmp_path / 'run-manifest.json').exists()
        assert database.with_name(database.name + '-wal').stat().st_size > 0
        reader.rollback()
        files = archive_files(tmp_path)
        manifest = create_manifest(tmp_path, files)
    assert validate_manifest(tmp_path, manifest)['valid']
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute('SELECT value FROM evidence').fetchall() == [('must survive',)]


@pytest.mark.parametrize('linked_file', ['database', 'wal'])
def test_archive_rejects_hardlinks_before_mutating_any_sqlite_file(tmp_path, linked_file):
    from support.scenario_driver import archive_files

    root = tmp_path / 'qa'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    database = (outside if linked_file == 'database' else root) / 'active.sqlite3'
    with closing(sqlite3.connect(database)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE evidence (value TEXT)')
        writer.execute("INSERT INTO evidence VALUES ('outside bytes must survive')")
        writer.commit()
        wal = database.with_name(database.name + '-wal')
        if linked_file == 'database':
            os.link(database, root / 'alias.sqlite3')
        else:
            os.link(wal, outside / 'alias-wal')
        originals = {database: database.read_bytes(), wal: wal.read_bytes()}
        with pytest.raises(ValueError, match='QA_EVIDENCE_HARDLINK_DENIED'):
            archive_files(root)
        assert all(path.read_bytes() == data for path, data in originals.items())
        assert not (root / 'run-manifest.json').exists()
