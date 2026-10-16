"""Immutable bytes, persisted DAG versions and release fences on real SQLite."""
import hashlib
import json
from contextlib import closing

import pytest

from app.contracts.artifacts import ArtifactVersion
from app.runtime.dependencies import DependencyGraph
from app.storage.blobs import BlobStore, read_artifact, store_artifact
from app.storage.database import Database, transaction
from app.storage.migrations import migrate
from app.storage.revisions import activate_revision, is_current_revision, snapshot_fence, require_publication_fence


@pytest.fixture
def storage(tmp_path):
    database = Database(tmp_path / "workbench.sqlite3")
    connection = database.connect()
    migrate(connection)
    connection.execute("INSERT INTO conversations(id,title) VALUES('c','fixture')")
    connection.execute("INSERT INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,connection_version) VALUES('p','fake-gpt','gpt-fixture','gpt','test','verified','1')")
    connection.execute("INSERT INTO turns(id,conversation_id,task_id,provider_profile_id,client_request_id,user_text) VALUES('turn','c','t','p','r','fixture')")
    connection.execute("INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id) VALUES('t','a','turn','p')")
    store = BlobStore(tmp_path / "blobs")
    yield database, connection, store
    connection.close()


def add(connection, store, logical, revision, dependencies=None, source=None):
    dependencies = dependencies or {}
    data = (revision + " bytes\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    value = ArtifactVersion(id=revision, task_id="t", artifact_kind=logical, language="zh-CN", immutable_uri="blob:sha256:" + digest, byte_sha256=digest, canonical_content_sha256=digest, source_version_id=source, origin_authors=["B"], canonical_issued_by="B", reviewed_by=[], rendered_by="B", a_response_ref=None, dependencies=[{"artifact_version_id": value, "relationship": "derived_from"} for value in dependencies.values()])
    store_artifact(connection, store, data, value, attempt_id="a", provenance={"test_only": True})
    return activate_revision(connection, store, "t", "a", logical, revision, dependencies)


def chain(connection, store):
    add(connection, store, "data", "data-v1")
    add(connection, store, "code", "code-v1", {"data": "data-v1"})
    add(connection, store, "result", "result-v1", {"code": "code-v1"})
    add(connection, store, "figure", "figure-v1", {"result": "result-v1"})
    add(connection, store, "report", "report-v1", {"figure": "figure-v1"})
    add(connection, store, "translation", "translation-v1", {"report": "report-v1"}, source="report-v1")
    add(connection, store, "independent", "independent-v1")


def test_dag_rejects_self_dependency_and_cycle():
    graph = DependencyGraph()
    graph.register("data", "d1", {})
    graph.register("report", "r1", {"data": "d1"})
    with pytest.raises(ValueError, match="DEPENDENCY_CYCLE"):
        graph.register("data", "d2", {"report": "r1"})
    with pytest.raises(ValueError, match="DEPENDENCY_SELF_REFERENCE"):
        graph.register("data", "d2", {"data": "d1"})
    assert graph.is_current("d1")


def test_data_change_stales_all_descendants_and_keeps_independent(storage):
    _, connection, store = storage
    chain(connection, store)
    result = add(connection, store, "data", "data-v2")
    assert set(result["invalidated_revision_ids"]) == {"data-v1", "code-v1", "result-v1", "figure-v1", "report-v1", "translation-v1"}
    assert is_current_revision(connection, "t", "a", "data-v2")
    assert is_current_revision(connection, "t", "a", "independent-v1")
    assert not is_current_revision(connection, "t", "a", "report-v1")
    assert read_artifact(connection, store, "data-v1") == b"data-v1 bytes\n"


def test_missing_dependency_version_is_rejected_before_activation(storage):
    _, connection, store = storage
    add(connection, store, "data", "data-v1")
    add(connection, store, "data", "data-v2")
    with pytest.raises(ValueError, match="DEPENDENCY_VERSION_NOT_CURRENT"):
        add(connection, store, "code", "code-v1", {"data": "data-v1"})


def test_graph_survives_reopen_and_old_bytes_remain_viewable(storage):
    database, connection, store = storage
    chain(connection, store)
    add(connection, store, "data", "data-v2")
    with closing(database.connect()) as reopened:
        assert not is_current_revision(reopened, "t", "a", "report-v1")
        assert is_current_revision(reopened, "t", "a", "independent-v1")
        assert read_artifact(reopened, store, "figure-v1") == b"figure-v1 bytes\n"


def test_old_pass_approval_and_translation_unit_are_marked_stale(storage):
    _, connection, store = storage
    chain(connection, store)
    for check_id, revision, kind in [("qa", "figure-v1", "validation.code"), ("approval", "report-v1", "release.approval"), ("independent-qa", "independent-v1", "validation.document")]:
        connection.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version) VALUES(?,'t','a',?,?,'pass','1')", (check_id, revision, kind))
    digest = connection.execute("SELECT byte_sha256 FROM artifact_revisions WHERE id='report-v1'").fetchone()[0]
    connection.execute("INSERT INTO translation_units(id,task_id,attempt_id,turn_id,job_id,block_id,source_version_id,source_locator,source_sha256,source_language,target_language,glossary_version,policy_version,purpose,budget_id,status,target_ref,target_sha256) VALUES('u','t','a','turn','j','b','report-v1','all',?,'en','zh-CN','1','1','display','b','READY','target',?)", (digest,digest))
    checkpoint = json.loads(connection.execute("SELECT checkpoint_json FROM task_runs WHERE task_id='t'").fetchone()[0])
    checkpoint["current_revision_id"] = "report-v1"
    connection.execute("UPDATE task_runs SET checkpoint_json=? WHERE task_id='t'", (json.dumps(checkpoint),))
    add(connection, store, "data", "data-v2")
    assert json.loads(connection.execute("SELECT details_json FROM checks WHERE id='approval'").fetchone()[0])["stale"] is True
    assert json.loads(connection.execute("SELECT details_json FROM checks WHERE id='qa'").fetchone()[0])["stale"] is True
    assert json.loads(connection.execute("SELECT details_json FROM checks WHERE id='independent-qa'").fetchone()[0]).get("stale") is not True
    assert connection.execute("SELECT status FROM translation_units WHERE id='u'").fetchone()[0] == "STALE"
    assert json.loads(connection.execute("SELECT checkpoint_json FROM task_runs WHERE task_id='t'").fetchone()[0])["publication_blocked"] is True


def test_mixed_new_source_and_old_translation_cannot_enter_ready(storage):
    _, connection, store = storage
    add(connection, store, "source", "source-v2")
    add(connection, store, "translation", "translation-v2", {"source": "source-v2"}, source="source-v2")
    add(connection, store, "source", "source-v3")
    with pytest.raises(ValueError, match="REVISION_NOT_CURRENT"):
        snapshot_fence(connection, "t", "a", ["source-v3", "translation-v2"])


def test_upstream_change_between_validation_and_publish_blocks_old_fence(storage):
    database, connection, store = storage
    chain(connection, store)
    fence = snapshot_fence(connection, "t", "a", ["report-v1"])
    with closing(database.connect()) as competing:
        add(competing, store, "data", "data-v2")
    with transaction(connection):
        with pytest.raises(ValueError, match="PUBLICATION_VERSION_CHANGED"):
            require_publication_fence(connection, "t", "a", fence)


def test_publication_fence_requires_write_transaction(storage):
    _, connection, store = storage
    add(connection, store, "data", "data-v1")
    fence = snapshot_fence(connection, "t", "a", ["data-v1"])
    with pytest.raises(ValueError, match="PUBLICATION_TRANSACTION_REQUIRED"):
        require_publication_fence(connection, "t", "a", fence)
    with transaction(connection):
        require_publication_fence(connection, "t", "a", fence)


def test_rebuilt_branch_gets_new_pass_while_old_pass_stays_stale(storage):
    _, connection, store = storage
    add(connection, store, "data", "data-v1")
    add(connection, store, "code", "code-v1", {"data": "data-v1"})
    add(connection, store, "data", "data-v2")
    add(connection, store, "code", "code-v2", {"data": "data-v2"})
    assert is_current_revision(connection, "t", "a", "code-v2")
    assert not is_current_revision(connection, "t", "a", "code-v1")


def test_same_revision_cannot_be_rebound_to_different_dependencies():
    graph = DependencyGraph()
    graph.register("data", "d1", {})
    graph.register("independent", "i1", {})
    with pytest.raises(ValueError, match="REVISION_BINDING_CHANGED"):
        graph.register("data", "d1", {"independent": "i1"})


def test_same_revision_cannot_be_current_under_two_logical_nodes():
    graph = DependencyGraph()
    graph.register("data", "d1", {})
    with pytest.raises(ValueError, match="REVISION_LOGICAL_ID_CONFLICT"):
        graph.register("other", "d1", {})


def test_translation_job_qa_is_stale_even_without_artifact_column(storage):
    _, connection, store = storage
    add(connection, store, "source", "source-v1")
    digest = connection.execute("SELECT byte_sha256 FROM artifact_revisions WHERE id='source-v1'").fetchone()[0]
    connection.execute("INSERT INTO translation_units(id,task_id,attempt_id,turn_id,job_id,block_id,source_version_id,source_locator,source_sha256,source_language,target_language,glossary_version,policy_version,purpose,budget_id) VALUES('u','t','a','turn','j','b','source-v1','all',?,'en','zh-CN','1','1','display','b')", (digest,))
    connection.execute("INSERT INTO checks(id,task_id,attempt_id,job_id,check_kind,result,check_version) VALUES('translation-qa','t','a','j','translation.qa','pass','1')")
    add(connection, store, "source", "source-v2")
    details = json.loads(connection.execute("SELECT details_json FROM checks WHERE id='translation-qa'").fetchone()[0])
    assert details.get("stale") is True


def test_unregistered_artifact_is_never_current(storage):
    _, connection, store = storage
    assert not is_current_revision(connection, "t", "a", "missing")


def test_failed_activation_does_not_partially_change_graph(storage):
    _, connection, store = storage
    add(connection, store, "data", "data-v1")
    before = connection.execute("SELECT checkpoint_json FROM task_runs WHERE task_id='t'").fetchone()[0]
    with pytest.raises(ValueError, match="REVISION_NOT_FOUND"):
        activate_revision(connection,store,"t","a","data","unknown",{})
    assert connection.execute("SELECT checkpoint_json FROM task_runs WHERE task_id='t'").fetchone()[0] == before
