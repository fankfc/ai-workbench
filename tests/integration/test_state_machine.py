import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from app.storage.database import Database, transaction
from app.storage.migrations import migrate
from app.storage.blobs import BlobStore, store_artifact
from app.contracts.artifacts import ArtifactVersion
from app.runtime.state_machine import StateMachine, TransitionError, TRANSITIONS, register_release_gate


def initialize_runtime(tmp_path, state="RECEIVED"):
    path = tmp_path / "runtime.sqlite3"
    connection = Database(path).connect()
    migrate(connection)
    connection.execute("INSERT INTO conversations(id,title) VALUES('c1','会话')")
    connection.execute("""INSERT INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,identity_source,connection_version)
                       VALUES('p1','fake','gpt','gpt','local','verified','fixture','1')""")
    connection.execute("""INSERT INTO turns(id,conversation_id,task_id,provider_profile_id,client_request_id,user_text)
                       VALUES('t1','c1','task1','p1','request1','输入')""")
    connection.execute("""INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,state,route_snapshot_json)
                       VALUES('task1','a1','t1','p1',?,'{"id":"route1"}')""", (state,))
    connection.close()
    return path


def current(path):
    connection = Database(path).connect()
    try:
        return dict(connection.execute("SELECT * FROM task_runs WHERE task_id='task1' AND attempt_id='a1'").fetchone())
    finally:
        connection.close()


def create_revision_and_gate(path, revision_id="revision1", approval_id="approval1"):
    store = BlobStore(Path(path).parent / "blobs")
    data = b"approved source"
    digest = hashlib.sha256(data).hexdigest()
    connection = Database(path).connect()
    try:
        artifact = ArtifactVersion(id=revision_id, task_id="task1", artifact_kind="answer", language="zh-CN",
            immutable_uri=store.uri_for(digest), byte_sha256=digest, canonical_content_sha256=digest,
            source_version_id=None, origin_authors=["A"], canonical_issued_by="A", reviewed_by=["A"],
            rendered_by="system", a_response_ref="response1", dependencies=[])
        store_artifact(connection, store, data, artifact, attempt_id="a1", provenance={"source_role":"A"})
        connection.execute("UPDATE task_runs SET checkpoint_json=? WHERE task_id='task1'", (json.dumps({"current_revision_id": revision_id}),))
        with transaction(connection):
            gate_id = register_release_gate(connection, "task1", "a1", "1.0", revision_id, approval_id, "route1")
        return gate_id
    finally:
        connection.close()


def test_transition_commits_state_and_one_outbox_record(tmp_path):
    path = initialize_runtime(tmp_path)
    result = StateMachine(path).transition("task1", "a1", "RECEIVED", "INPUT_PREPARING", "1.0", {"reason":"start"})
    assert current(path)["state"] == "INPUT_PREPARING"
    assert result["event_id"]
    connection = Database(path).connect()
    try:
        rows = connection.execute("SELECT * FROM outbox_events").fetchall()
        assert len(rows) == 1 and rows[0]["kind"] == "task.state_changed"
        assert rows[0]["public_event_json"] is None
        assert json.loads(rows[0]["internal_payload_json"])["new_state"] == "INPUT_PREPARING"
    finally:
        connection.close()


@pytest.mark.parametrize("argument,replacement,error", [("attempt_id","old","ATTEMPT_NOT_FOUND"),
    ("contract_version","2.0","CONTRACT_VERSION_MISMATCH"), ("expected_state","EXECUTING","EXPECTED_STATE_MISMATCH"),
    ("new_state","PUBLISHED","ILLEGAL_TRANSITION")])
def test_transition_rejects_stale_or_illegal_input_without_state_change(tmp_path, argument, replacement, error):
    path = initialize_runtime(tmp_path)
    kwargs = dict(task_id="task1", attempt_id="a1", expected_state="RECEIVED", new_state="INPUT_PREPARING", contract_version="1.0")
    kwargs[argument] = replacement
    with pytest.raises(TransitionError, match=error):
        StateMachine(path).transition(**kwargs)
    assert current(path)["state"] == "RECEIVED"


def test_outbox_insert_failure_rolls_back_state_change(tmp_path):
    path = initialize_runtime(tmp_path)
    connection = Database(path).connect()
    connection.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON outbox_events BEGIN SELECT RAISE(ABORT,'injected'); END")
    connection.close()
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        StateMachine(path).transition("task1", "a1", "RECEIVED", "INPUT_PREPARING", "1.0")
    assert current(path)["state"] == "RECEIVED"


@pytest.mark.parametrize("state", ["OUTPUT_PREPARING", "READY"])
def test_release_transition_requires_persisted_approval_not_payload_claim(tmp_path, state):
    path = initialize_runtime(tmp_path, state)
    with pytest.raises(TransitionError, match="RELEASE_GATE_REQUIRED"):
        StateMachine(path).transition("task1", "a1", state, "READY" if state == "OUTPUT_PREPARING" else "PUBLISHED", "1.0",
                                      {"approval_id":"pretend", "PASS":True})
    assert current(path)["state"] == state


def test_release_gate_binds_current_revision_and_allows_ready_then_published(tmp_path):
    path = initialize_runtime(tmp_path, "OUTPUT_PREPARING")
    gate_id = create_revision_and_gate(path)
    assert gate_id == "approval1"
    machine = StateMachine(path)
    machine.transition("task1", "a1", "OUTPUT_PREPARING", "READY", "1.0")
    machine.transition("task1", "a1", "READY", "PUBLISHED", "1.0")
    assert current(path)["state"] == "PUBLISHED"
    assert json.loads(current(path)["checkpoint_json"])["release_registry"]["approval_id"] == gate_id


@pytest.mark.parametrize("damage", ["revision", "check-result", "route-binding"])
def test_changed_current_revision_or_approval_evidence_blocks_published(tmp_path, damage):
    path = initialize_runtime(tmp_path, "READY")
    gate_id = create_revision_and_gate(path)
    connection = Database(path).connect()
    if damage == "revision":
        checkpoint = json.loads(current(path)["checkpoint_json"])
        checkpoint["current_revision_id"] = "revision2"
        connection.execute("UPDATE task_runs SET checkpoint_json=?", (json.dumps(checkpoint),))
    elif damage == "check-result":
        connection.execute("UPDATE checks SET result='fail' WHERE id=?", (gate_id,))
    else:
        details = json.loads(connection.execute("SELECT details_json FROM checks WHERE id=?", (gate_id,)).fetchone()[0])
        details["route_snapshot_id"] = "stale-route"
        connection.execute("UPDATE checks SET details_json=? WHERE id=?", (json.dumps(details), gate_id))
    connection.close()
    with pytest.raises(TransitionError, match="RELEASE_GATE"):
        StateMachine(path).transition("task1", "a1", "READY", "PUBLISHED", "1.0")
    assert current(path)["state"] == "READY"


def test_old_attempt_cannot_transition_or_register_approval(tmp_path):
    path = initialize_runtime(tmp_path, "EXECUTING")
    connection = Database(path).connect()
    connection.execute("""INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,attempt_number,state)
                       VALUES('task1','a2','t1','p1',2,'EXECUTING')""")
    with pytest.raises(TransitionError, match="STALE_ATTEMPT"):
        StateMachine(path).transition("task1", "a1", "EXECUTING", "VALIDATING", "1.0")
    with transaction(connection):
        with pytest.raises(TransitionError, match="STALE_ATTEMPT"):
            register_release_gate(connection, "task1", "a1", "1.0", "missing", "approval1", "route1")
    connection.close()


def test_cancel_fence_blocks_late_transitions_and_clears_release_registry(tmp_path):
    path = initialize_runtime(tmp_path, "READY")
    create_revision_and_gate(path)
    machine = StateMachine(path)
    machine.transition("task1", "a1", "READY", "CANCELLED", "1.0")
    row = current(path)
    assert row["cancel_requested"] == 1
    assert "release_registry" not in json.loads(row["checkpoint_json"])
    with pytest.raises(TransitionError, match="CANCELLED"):
        machine.transition("task1", "a1", "CANCELLED", "PUBLISHED", "1.0")


def test_entire_normal_path_uses_the_persisted_gate_at_release(tmp_path):
    path = initialize_runtime(tmp_path)
    states = ["RECEIVED","INPUT_PREPARING","PLANNING","EXECUTING","VALIDATING","REVIEWING","OUTPUT_PREPARING","READY","PUBLISHED"]
    for before, after in zip(states, states[1:]):
        if after == "READY":
            create_revision_and_gate(path)
        assert after in TRANSITIONS[before]
        StateMachine(path).transition("task1","a1",before,after,"1.0")
    assert current(path)["state"] == "PUBLISHED"


def test_release_gate_refuses_missing_frozen_route_identifier(tmp_path):
    path = initialize_runtime(tmp_path,"OUTPUT_PREPARING")
    create_revision_and_gate(path)
    connection = Database(path).connect()
    connection.execute("DROP TRIGGER task_identity_immutable")
    connection.execute("UPDATE task_runs SET route_snapshot_json='{}'")
    try:
        with transaction(connection):
            with pytest.raises(TransitionError,match="ROUTE"):
                register_release_gate(connection,"task1","a1","1.0","revision1","approval2",None)
    finally:
        connection.close()


@pytest.mark.parametrize("marker", ["stale","publication_blocked"])
def test_stale_or_publication_blocked_checkpoint_prevents_reapproval_and_ready(tmp_path,marker):
    path = initialize_runtime(tmp_path,"OUTPUT_PREPARING")
    create_revision_and_gate(path)
    connection = Database(path).connect()
    checkpoint = json.loads(current(path)["checkpoint_json"])
    checkpoint[marker] = True
    connection.execute("UPDATE task_runs SET checkpoint_json=?", (json.dumps(checkpoint),))
    try:
        with transaction(connection):
            with pytest.raises(TransitionError,match="STALE"):
                register_release_gate(connection,"task1","a1","1.0","revision1","approval2","route1")
        with pytest.raises(TransitionError,match="STALE"):
            StateMachine(path).transition("task1","a1","OUTPUT_PREPARING","READY","1.0")
    finally:
        connection.close()


@pytest.mark.parametrize("branch", ["NEEDS_INPUT","REPAIRING","BLOCKED","PAUSED","FAILED","CANCELLED"])
def test_explicit_exception_branches_are_persisted_with_one_state_event(tmp_path,branch):
    path = initialize_runtime(tmp_path,"EXECUTING")
    StateMachine(path).transition("task1","a1","EXECUTING",branch,"1.0")
    assert current(path)["state"] == branch
    connection = Database(path).connect()
    assert connection.execute("SELECT count(*) FROM outbox_events").fetchone()[0] == 1
    connection.close()


@pytest.mark.parametrize("before,after", [(before,after) for before in sorted(TRANSITIONS) for after in sorted(TRANSITIONS[before])])
def test_each_declared_legal_edge_commits_valid_state_and_a_single_event(tmp_path,before,after):
    path = initialize_runtime(tmp_path,before)
    if after in {"READY","PUBLISHED"}:
        create_revision_and_gate(path)
    result = StateMachine(path).transition("task1","a1",before,after,"1.0")
    assert result["state"] == current(path)["state"] == after
    connection = Database(path).connect()
    try:
        row = connection.execute("SELECT * FROM outbox_events").fetchone()
        assert row["event_id"] == result["event_id"]
        assert json.loads(row["internal_payload_json"])["expected_state"] == before
        assert connection.execute("SELECT count(*) FROM outbox_events").fetchone()[0] == 1
    finally:
        connection.close()
