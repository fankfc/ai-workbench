"""Real SQLite and filesystem behavior; all workspaces are isolated."""
import errno
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import time

import pytest

from app.storage.database import Database, transaction
from app.storage.migrations import Migration, MigrationError, migrate
from app.storage.blobs import BlobError, BlobStore, read_artifact, store_artifact
from app.contracts.artifacts import ArtifactVersion
import app.storage.blobs as blobs_module


SCHEMA_PATH = Path(__file__).parents[2] / "services/orchestrator/app/storage/schema/0001_initial.sql"


def test_connection_sets_row_factory_foreign_keys_wal_and_timeout(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3", busy_timeout_ms=83).connect()
    try:
        assert connection.row_factory is sqlite3.Row
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 83
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.isolation_level is None
    finally:
        connection.close()


def test_connection_creates_parent_directory(tmp_path):
    connection = Database(tmp_path / "nested" / "metadata.sqlite3").connect()
    connection.close()
    assert (tmp_path / "nested" / "metadata.sqlite3").exists()


def test_transaction_rolls_back_on_interruption(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    try:
        with pytest.raises(KeyboardInterrupt):
            with transaction(connection):
                connection.execute("INSERT INTO sample VALUES (1)")
                raise KeyboardInterrupt
        assert connection.execute("SELECT count(*) FROM sample").fetchone()[0] == 0
        with transaction(connection):
            connection.execute("INSERT INTO sample VALUES (2)")
        assert connection.execute("SELECT id FROM sample").fetchone()[0] == 2
    finally:
        connection.close()


def test_transaction_rejects_nested_boundary(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    try:
        with transaction(connection):
            with pytest.raises(ValueError, match="TRANSACTION_ALREADY_ACTIVE"):
                with transaction(connection):
                    pass
    finally:
        connection.close()


def test_initial_migration_is_repeatable_and_builds_ten_domain_tables(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    try:
        initial = [Migration(1, SCHEMA_PATH.stem, SCHEMA_PATH.read_text(encoding='utf-8'))]
        assert migrate(connection, initial) == 1
        assert migrate(connection, initial) == 1
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names == {"schema_version", "conversations", "turns", "task_runs", "steps",
                         "provider_profiles", "artifact_revisions", "translation_units", "checks",
                         "usage_entries", "outbox_events"}
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_sequential_upgrade_reopens_old_database_without_losing_rows(tmp_path):
    path = tmp_path / "old.sqlite3"
    first = Migration(1, "old", "CREATE TABLE records(id TEXT PRIMARY KEY, text TEXT); INSERT INTO records VALUES ('r1','保留');")
    old = Database(path).connect()
    assert migrate(old, [first]) == 1
    old.close()
    reopened = Database(path).connect()
    try:
        second = Migration(2, "upgrade", "ALTER TABLE records ADD COLUMN state TEXT DEFAULT 'SAVED';")
        assert migrate(reopened, [first, second]) == 2
        row = reopened.execute("SELECT * FROM records").fetchone()
        assert tuple(row) == ("r1", "保留", "SAVED")
        assert reopened.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 2
    finally:
        reopened.close()


def test_failed_upgrade_rolls_back_every_pending_migration(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    first = Migration(1, "old", "CREATE TABLE records(id INTEGER); INSERT INTO records VALUES(7);")
    assert migrate(connection, [first]) == 1
    try:
        with pytest.raises(sqlite3.OperationalError):
            migrate(connection, [first, Migration(2, "good", "ALTER TABLE records ADD COLUMN value TEXT;"),
                                  Migration(3, "bad", "INSERT INTO missing_table VALUES(1);")])
        assert connection.execute("SELECT version FROM schema_version").fetchall()[0][0] == 1
        assert [row[1] for row in connection.execute("PRAGMA table_info(records)")] == ["id"]
        assert connection.execute("SELECT id FROM records").fetchone()[0] == 7
        assert not connection.in_transaction
    finally:
        connection.close()


def test_initial_failed_migration_leaves_no_metadata_or_partial_tables(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            migrate(connection, [Migration(1, "bad", "CREATE TABLE records(id INTEGER); INSERT INTO absent VALUES(1);")])
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    finally:
        connection.close()


def test_migration_rejects_transaction_control_without_leaking_ddl(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    try:
        with pytest.raises(MigrationError, match="TRANSACTION_CONTROL"):
            migrate(connection, [Migration(1, "bad", "CREATE TABLE records(id INTEGER); COMMIT;")])
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    finally:
        connection.close()


def test_migration_rejects_missing_version_and_newer_unknown_schema(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    first = Migration(1, "initial", "CREATE TABLE records(id INTEGER);")
    try:
        with pytest.raises(MigrationError, match="CONTIGUOUS"):
            migrate(connection, [Migration(2, "gap", "CREATE TABLE records(id INTEGER);")])
        assert migrate(connection, [first, Migration(2, "second", "ALTER TABLE records ADD COLUMN state TEXT;")]) == 2
        with pytest.raises(MigrationError, match="NEWER_SCHEMA"):
            migrate(connection, [first])
        assert [row[1] for row in connection.execute("PRAGMA table_info(records)")] == ["id", "state"]
    finally:
        connection.close()


def test_migration_rejects_changed_applied_hash(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    try:
        first = Migration(1, "initial", "CREATE TABLE records(id INTEGER);")
        assert migrate(connection, [first]) == 1
        with pytest.raises(MigrationError, match="MIGRATION_CHANGED"):
            migrate(connection, [Migration(1, "initial", "CREATE TABLE records(id TEXT);")])
        assert [row[2] for row in connection.execute("PRAGMA table_info(records)")] == ["INTEGER"]
    finally:
        connection.close()


def test_migration_rejects_unversioned_nonempty_database(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    connection.execute("CREATE TABLE records(id INTEGER)")
    connection.execute("INSERT INTO records VALUES(7)")
    try:
        with pytest.raises(MigrationError, match="UNVERSIONED_DATABASE"):
            migrate(connection)
        assert connection.execute("SELECT id FROM records").fetchone()[0] == 7
    finally:
        connection.close()


def test_blob_roundtrip_uses_content_hash_and_preserves_existing_bytes(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    original = b"immutable original\x00\xff"
    ref = store.put(original)
    assert ref.sha256 == hashlib.sha256(original).hexdigest()
    assert ref.size_bytes == len(original)
    path = store.path_for(ref.sha256)
    before = path.stat().st_mtime_ns
    assert store.put(original) == ref
    assert path.stat().st_mtime_ns == before
    assert store.read(ref.sha256) == original
    assert store.verify(ref.sha256) == ref
    assert list(path.parent.glob("*.tmp")) == []


def test_blob_existing_content_with_wrong_hash_is_rejected_not_overwritten(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    original = b"expected"
    digest = hashlib.sha256(original).hexdigest()
    destination = store.path_for(digest)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"corrupted")
    with pytest.raises(BlobError, match="BLOB_HASH_MISMATCH"):
        store.put(original)
    assert destination.read_bytes() == b"corrupted"


def test_blob_read_refuses_missing_content(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    with pytest.raises(BlobError, match="BLOB_MISSING"):
        store.read("a" * 64)


@pytest.mark.parametrize("digest", ["../secret", "A" * 64, "a" * 63, "a" * 65])
def test_blob_paths_reject_non_sha256_names(tmp_path, digest):
    with pytest.raises(BlobError, match="INVALID_BLOB_HASH"):
        BlobStore(tmp_path / "blobs").path_for(digest)


@pytest.fixture
def storage(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3", busy_timeout_ms=30).connect()
    assert migrate(connection, [Migration(1, SCHEMA_PATH.stem, SCHEMA_PATH.read_text(encoding='utf-8'))]) == 1
    connection.execute("INSERT INTO conversations(id,title) VALUES('c1','会话')")
    connection.execute("""INSERT INTO provider_profiles(id,adapter,model_id,family,connection_id,
                       identity_status,identity_source,connection_version)
                       VALUES('p1','fake','fake-gpt','gpt','local','verified','fixture','1')""")
    connection.execute("""INSERT INTO turns(id,conversation_id,task_id,provider_profile_id,client_request_id,user_text)
                       VALUES('t1','c1','task1','p1','request1','用户输入')""")
    connection.execute("""INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id)
                       VALUES('task1','a1','t1','p1')""")
    store = BlobStore(tmp_path / "blobs")
    yield connection, store
    connection.close()


def artifact_for(store, data=b"source bytes", **changes):
    digest = hashlib.sha256(data).hexdigest()
    values = dict(id="artifact1", task_id="task1", artifact_kind="source", language="en",
                  immutable_uri=store.uri_for(digest), byte_sha256=digest,
                  canonical_content_sha256=digest, source_version_id=None,
                  origin_authors=["user"], canonical_issued_by="user", reviewed_by=[],
                  rendered_by="storage", a_response_ref=None, dependencies=[])
    values.update(changes)
    return ArtifactVersion(**values)


def manually_register(connection, store, data=b"source bytes", **changes):
    artifact = artifact_for(store, data, **changes)
    store.put(data)
    connection.execute("""INSERT INTO artifact_revisions(id,task_id,attempt_id,artifact_kind,language,
        immutable_uri,byte_sha256,canonical_content_sha256,size_bytes,origin_authors_json,
        canonical_issued_by,reviewed_by_json,rendered_by,dependencies_json,provenance_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (artifact.id, artifact.task_id, "a1", artifact.artifact_kind,
        artifact.language, artifact.immutable_uri, artifact.byte_sha256, artifact.canonical_content_sha256,
        len(data), '["user"]', artifact.canonical_issued_by, '[]', artifact.rendered_by, '[]', '{}'))
    return artifact


def test_artifact_transaction_records_provenance_dependencies_and_source_request(storage):
    connection, store = storage
    source = manually_register(connection, store, id="source0")
    data = b"derived bytes"
    artifact = artifact_for(store, data, source_version_id=source.id,
                            dependencies=[{"artifact_version_id": source.id, "relationship": "derived-from"}])
    provenance = {"source_role": "A", "origin": "provider", "version": "1"}
    request = {"provider_id": "p1", "external_request_id": "external-1"}
    ref = store_artifact(connection, store, data, artifact, attempt_id="a1", provenance=provenance, source_request=request)
    assert ref is not None
    row = connection.execute("SELECT * FROM artifact_revisions WHERE id='artifact1'").fetchone()
    assert row["byte_sha256"] == ref.sha256
    assert row["source_version_id"] == source.id
    assert json.loads(row["provenance_json"]) == provenance
    assert json.loads(row["source_request_json"]) == request
    assert json.loads(row["dependencies_json"])[0]["artifact_version_id"] == source.id
    assert read_artifact(connection, store, artifact.id) == data


@pytest.mark.parametrize("field,value", [("byte_sha256", "a" * 64), ("immutable_uri", "blob:sha256:" + "a" * 64)])
def test_artifact_rejects_hash_or_uri_not_matching_actual_bytes(storage, field, value):
    connection, store = storage
    artifact = artifact_for(store, **{field: value})
    with pytest.raises(BlobError, match="ARTIFACT_BLOB_REFERENCE_MISMATCH"):
        store_artifact(connection, store, b"source bytes", artifact, attempt_id="a1", provenance={})
    assert connection.execute("SELECT count(*) FROM artifact_revisions").fetchone()[0] == 0


def test_artifact_rejects_dependency_that_does_not_exist(storage):
    connection, store = storage
    artifact = artifact_for(store, dependencies=[{"artifact_version_id": "missing", "relationship": "source"}])
    with pytest.raises(BlobError, match="ARTIFACT_DEPENDENCY_MISSING"):
        store_artifact(connection, store, b"source bytes", artifact, attempt_id="a1", provenance={})
    assert connection.execute("SELECT count(*) FROM artifact_revisions").fetchone()[0] == 0


@pytest.mark.parametrize("failure", [OSError(errno.ENOSPC, "disk full"), KeyboardInterrupt("write interrupted")], ids=["disk-full", "interrupted"])
def test_artifact_fsync_failure_never_registers_a_visible_revision(storage, monkeypatch, failure):
    connection, store = storage
    artifact = artifact_for(store)
    def fail(_descriptor):
        raise failure
    monkeypatch.setattr(blobs_module.os, "fsync", fail)
    with pytest.raises(type(failure)):
        store_artifact(connection, store, b"source bytes", artifact, attempt_id="a1", provenance={})
    assert not connection.in_transaction
    assert connection.execute("SELECT count(*) FROM artifact_revisions").fetchone()[0] == 0
    assert not store.path_for(artifact.byte_sha256).exists()
    assert list(store.root.rglob("*.tmp")) == []


def test_artifact_partial_write_failure_leaves_no_reference_or_temporary_file(storage, monkeypatch):
    connection, store = storage
    factory = blobs_module.tempfile.NamedTemporaryFile
    class InterruptedFile:
        def __init__(self, handle):
            self.handle = handle
            self.name = handle.name
        def __enter__(self):
            self.handle.__enter__()
            return self
        def __exit__(self, *args):
            return self.handle.__exit__(*args)
        def write(self, data):
            self.handle.write(data[:3])
            self.handle.flush()
            raise OSError(errno.ENOSPC, "partial write")
    def interrupted(*args, **kwargs):
        return InterruptedFile(factory(*args, **kwargs))
    monkeypatch.setattr(blobs_module.tempfile, "NamedTemporaryFile", interrupted)
    artifact = artifact_for(store)
    with pytest.raises(OSError, match="partial write"):
        store_artifact(connection, store, b"source bytes", artifact, attempt_id="a1", provenance={})
    assert connection.execute("SELECT count(*) FROM artifact_revisions").fetchone()[0] == 0
    assert not store.path_for(artifact.byte_sha256).exists()
    assert list(store.root.rglob("*.tmp")) == []


def test_artifact_link_failure_never_registers_or_leaks_temporary_files(storage, monkeypatch):
    connection, store = storage
    def fail(_source, _destination):
        raise OSError(errno.EIO, "link failure")
    monkeypatch.setattr(blobs_module.os, "link", fail)
    with pytest.raises(OSError, match="link failure"):
        store_artifact(connection, store, b"source bytes", artifact_for(store), attempt_id="a1", provenance={})
    assert connection.execute("SELECT count(*) FROM artifact_revisions").fetchone()[0] == 0
    assert list(store.root.rglob("*.tmp")) == []


def test_artifact_duplicate_id_rolls_back_registration_without_changing_original(storage):
    connection, store = storage
    original = manually_register(connection, store)
    data = b"new bytes"
    with pytest.raises(sqlite3.IntegrityError):
        store_artifact(connection, store, data, artifact_for(store, data), attempt_id="a1", provenance={})
    assert not connection.in_transaction
    row = connection.execute("SELECT byte_sha256 FROM artifact_revisions").fetchone()
    assert row[0] == original.byte_sha256
    assert store.read(original.byte_sha256) == b"source bytes"
    assert store.read(hashlib.sha256(data).hexdigest()) == data  # Safe unreferenced complete blob.


def test_artifact_write_under_database_lock_times_out_without_starting_blob(storage, tmp_path):
    connection, store = storage
    second = Database(tmp_path / "metadata.sqlite3", busy_timeout_ms=30).connect()
    try:
        with transaction(connection):
            started = time.monotonic()
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                store_artifact(second, store, b"source bytes", artifact_for(store), attempt_id="a1", provenance={})
            assert 0.015 <= time.monotonic() - started < 2
        assert connection.execute("SELECT count(*) FROM artifact_revisions").fetchone()[0] == 0
        assert not store.root.exists()
    finally:
        second.close()


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_artifact_read_rejects_missing_or_corrupted_registered_content(storage, damage):
    connection, store = storage
    artifact = manually_register(connection, store)
    path = store.path_for(artifact.byte_sha256)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"corruption")
    with pytest.raises(BlobError, match="BLOB_MISSING" if damage == "missing" else "BLOB_HASH_MISMATCH"):
        read_artifact(connection, store, artifact.id)


def test_artifact_read_refuses_unknown_database_reference(storage):
    connection, store = storage
    with pytest.raises(BlobError, match="ARTIFACT_NOT_FOUND"):
        read_artifact(connection, store, "unknown")


def test_artifact_external_connection_cannot_see_registration_before_fsync(storage, monkeypatch, tmp_path):
    connection, store = storage
    observer = Database(tmp_path / "metadata.sqlite3").connect()
    original_fsync = blobs_module.os.fsync
    observations = []
    def observed(descriptor):
        observations.append(observer.execute("SELECT count(*) FROM artifact_revisions").fetchone()[0])
        return original_fsync(descriptor)
    monkeypatch.setattr(blobs_module.os, "fsync", observed)
    try:
        store_artifact(connection, store, b"source bytes", artifact_for(store), attempt_id="a1", provenance={})
        assert observations == [0]
        assert observer.execute("SELECT count(*) FROM artifact_revisions").fetchone()[0] == 1
    finally:
        observer.close()


def test_schema_rejects_duplicate_turn_request_within_conversation(storage):
    connection, _store = storage
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        connection.execute("""INSERT INTO turns(id,conversation_id,task_id,provider_profile_id,client_request_id,user_text)
                           VALUES('t2','c1','task2','p1','request1','重复')""")
    assert connection.execute("SELECT count(*) FROM turns").fetchone()[0] == 1


def test_schema_allows_same_client_request_in_different_conversation(storage):
    connection, _store = storage
    connection.execute("INSERT INTO conversations(id,title) VALUES('c2','第二个会话')")
    connection.execute("""INSERT INTO turns(id,conversation_id,task_id,provider_profile_id,client_request_id,user_text)
                       VALUES('t2','c2','task2','p1','request1','独立输入')""")
    assert connection.execute("SELECT count(*) FROM turns").fetchone()[0] == 2


def test_schema_rejects_duplicate_task_attempt_and_external_request(storage):
    connection, _store = storage
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        connection.execute("""INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id)
                           VALUES('task1','a1','t1','p1')""")
    connection.execute("UPDATE task_runs SET external_request_id='provider-request' WHERE task_id='task1'")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        connection.execute("""INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,external_request_id)
                           VALUES('task1','a2','t1','p1','provider-request')""")


def insert_event(connection, event_id="e1", sequence=1, conversation_sequence=1, **changes):
    values = dict(conversation_id="c1", turn_id="t1", task_id="task1", attempt_id="a1",
                  kind="response.pending", public_event_json='{"status":"pending"}', deduplication_key=event_id)
    values.update(changes)
    connection.execute("""INSERT INTO outbox_events(event_id,conversation_id,turn_id,task_id,attempt_id,
                       sequence,conversation_sequence,kind,public_event_json,deduplication_key)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""", (event_id, values["conversation_id"], values["turn_id"],
                       values["task_id"], values["attempt_id"], sequence, conversation_sequence,
                       values["kind"], values["public_event_json"], values["deduplication_key"]))


@pytest.mark.parametrize("sequence,conversation_sequence,key", [(1,2,"e2"), (2,1,"e2"), (2,2,"e1")])
def test_schema_rejects_duplicate_event_stream_cursor_or_deduplication_key(storage, sequence, conversation_sequence, key):
    connection, _store = storage
    insert_event(connection)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        insert_event(connection, "e2", sequence, conversation_sequence, deduplication_key=key)
    assert connection.execute("SELECT count(*) FROM outbox_events").fetchone()[0] == 1


@pytest.mark.parametrize("column,value", [("task_id","absent"), ("attempt_id","absent"), ("conversation_id","absent"), ("turn_id","absent")])
def test_schema_rejects_outbox_foreign_reference_mismatch(storage, column, value):
    connection, _store = storage
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_event(connection, **{column: value})


def test_schema_rejects_internal_event_as_public_record(storage):
    connection, _store = storage
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        insert_event(connection, kind="model.delta", public_event_json='{"text":"INTERNAL"}')
    insert_event(connection, kind="model.delta", public_event_json=None)
    assert connection.execute("SELECT public_event_json FROM outbox_events").fetchone()[0] is None


@pytest.mark.parametrize("statement", [
    "UPDATE turns SET route_snapshot_json='{}' WHERE id='t1'",
    "UPDATE task_runs SET contract_version='2.0' WHERE task_id='task1'",
    "UPDATE artifact_revisions SET byte_sha256='" + "a" * 64 + "' WHERE id='artifact1'",
    "UPDATE outbox_events SET public_event_json='{}' WHERE event_id='e1'",
])
def test_schema_prevents_changing_frozen_records(storage, statement):
    connection, store = storage
    manually_register(connection, store)
    insert_event(connection)
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
        connection.execute(statement)
    connection.execute("UPDATE task_runs SET state='EXECUTING',lease_owner='local' WHERE task_id='task1'")
    connection.execute("UPDATE outbox_events SET delivery_state='DELIVERED',delivery_attempts=1 WHERE event_id='e1'")


def test_schema_rejects_invalid_json_and_usage_deduplicates_request_metric(storage):
    connection, _store = storage
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        connection.execute("UPDATE provider_profiles SET provider_json='bad' WHERE id='p1'")
    sql = """INSERT INTO usage_entries(id,task_id,attempt_id,provider_profile_id,external_request_id,metric,quantity,unit)
             VALUES(?,'task1','a1','p1','request-1','tokens',10,'token')"""
    connection.execute(sql, ("u1",))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        connection.execute(sql, ("u2",))


def test_migration_sql_parser_handles_trigger_and_semicolons_inside_strings(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    try:
        sql = """-- Leading comment
        CREATE TABLE records(id INTEGER, text TEXT);
        CREATE TRIGGER records_no_delete BEFORE DELETE ON records BEGIN
            SELECT RAISE(ABORT,'keep; records');
        END;
        INSERT INTO records VALUES(1,'value;inside'); -- final comment
        """
        assert migrate(connection, [Migration(1, "with-trigger", sql)]) == 1
        assert connection.execute("SELECT text FROM records").fetchone()[0] == "value;inside"
        with pytest.raises(sqlite3.IntegrityError, match="keep; records"):
            connection.execute("DELETE FROM records")
    finally:
        connection.close()


def test_migration_checks_deferred_foreign_keys_and_rolls_back(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    try:
        sql = """CREATE TABLE parents(id INTEGER PRIMARY KEY);
        CREATE TABLE children(parent_id INTEGER REFERENCES parents(id) DEFERRABLE INITIALLY DEFERRED);
        INSERT INTO children VALUES(7);"""
        with pytest.raises(MigrationError, match="FOREIGN_KEY_CHECK_FAILED"):
            migrate(connection, [Migration(1, "invalid-fk", sql)])
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    finally:
        connection.close()


def populate_domain_tables(connection, store):
    source = manually_register(connection, store)
    connection.execute("""INSERT INTO steps(id,task_id,attempt_id,step_key,role,provider_profile_id,external_request_id)
                       VALUES('s1','task1','a1','author','A','p1','external-1')""")
    connection.execute("""INSERT INTO translation_units(id,task_id,attempt_id,turn_id,job_id,block_id,source_version_id,
                       source_locator,source_sha256,source_language,target_language,glossary_version,policy_version,purpose,budget_id)
                       VALUES('tr1','task1','a1','t1','job1','block1',?,'paragraph:1',?,'en','zh-CN','g1','p1','delivery','b1')""",
                       (source.id, source.byte_sha256))
    connection.execute("""INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version)
                       VALUES('check1','task1','a1',?,'source-hash','pass','1')""", (source.id,))
    connection.execute("""INSERT INTO usage_entries(id,task_id,attempt_id,step_id,provider_profile_id,external_request_id,metric,quantity,unit)
                       VALUES('u1','task1','a1','s1','p1','external-1','tokens',7,'token')""")
    insert_event(connection)
    return source


def test_real_schema_upgrade_preserves_domain_counts_foreign_keys_and_blob_hash(storage, tmp_path):
    connection, store = storage
    source = populate_domain_tables(connection, store)
    names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='schema_version'")]
    before = {name: connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in names}
    assert all(count == 1 for count in before.values())
    connection.close()
    reopened = Database(tmp_path / "metadata.sqlite3").connect()
    try:
        first = Migration(1, SCHEMA_PATH.stem, SCHEMA_PATH.read_text(encoding="utf-8"))
        second = Migration(2, "additive-fixture", "ALTER TABLE conversations ADD COLUMN archive_note TEXT;")
        assert migrate(reopened, [first, second]) == 2
        after = {name: reopened.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in names}
        assert after == before
        assert reopened.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert reopened.execute("PRAGMA foreign_key_check").fetchall() == []
        assert hashlib.sha256(read_artifact(reopened, store, source.id)).hexdigest() == source.byte_sha256
    finally:
        reopened.close()


def test_migration_accepts_empty_sql_statements_and_comments(tmp_path):
    connection = Database(tmp_path / "metadata.sqlite3").connect()
    try:
        assert migrate(connection, [Migration(1, "empty-statements", "; /* comment */; CREATE TABLE records(id INTEGER); ;")]) == 1
        assert connection.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    finally:
        connection.close()


def test_task_external_request_identity_can_be_assigned_once_but_cannot_be_replaced(storage):
    connection, _store = storage
    connection.execute("UPDATE task_runs SET external_request_id='request-started' WHERE task_id='task1'")
    with pytest.raises(sqlite3.IntegrityError, match="EXTERNAL_REQUEST_IMMUTABLE"):
        connection.execute("UPDATE task_runs SET external_request_id='replacement' WHERE task_id='task1'")
    with pytest.raises(sqlite3.IntegrityError, match="EXTERNAL_REQUEST_IMMUTABLE"):
        connection.execute("UPDATE task_runs SET external_request_id=NULL WHERE task_id='task1'")
    assert connection.execute("SELECT external_request_id FROM task_runs").fetchone()[0] == "request-started"


def test_simultaneous_blob_writes_never_replace_existing_content(tmp_path, monkeypatch):
    store = BlobStore(tmp_path / "blobs")
    barrier = Barrier(2)
    factory = blobs_module.tempfile.NamedTemporaryFile
    def simultaneous(*args, **kwargs):
        handle = factory(*args, **kwargs)
        barrier.wait(timeout=5)
        return handle
    monkeypatch.setattr(blobs_module.tempfile, "NamedTemporaryFile", simultaneous)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(store.put, b"same concurrent bytes") for _ in range(2)]
        refs = [future.result(timeout=10) for future in futures]
    assert refs[0] == refs[1]
    assert store.read(refs[0].sha256) == b"same concurrent bytes"
    assert len(list(store.root.rglob("*" + refs[0].sha256))) == 1
    assert list(store.root.rglob("*.tmp")) == []


def test_process_exit_before_database_commit_keeps_blob_but_rolls_back_revision(storage, tmp_path):
    connection, store = storage
    script = """
import os, sys
from contextlib import contextmanager
from app.storage.database import Database
from app.storage.blobs import BlobStore, store_artifact
from app.contracts.artifacts import ArtifactVersion
import app.storage.blobs as module
@contextmanager
def interrupted_transaction(connection):
    connection.execute('BEGIN IMMEDIATE')
    yield connection
    os._exit(78)
module.transaction = interrupted_transaction
connection = Database(sys.argv[1]).connect()
store = BlobStore(sys.argv[2])
artifact = ArtifactVersion.model_validate_json(sys.argv[3])
store_artifact(connection, store, b'source bytes', artifact, attempt_id='a1', provenance={})
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "metadata.sqlite3"), str(store.root),
                             artifact_for(store).model_dump_json()], capture_output=True, text=True, timeout=20)
    assert result.returncode == 78, result.stderr
    assert connection.execute("SELECT count(*) FROM artifact_revisions").fetchone()[0] == 0
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.read(artifact_for(store).byte_sha256) == b"source bytes"
