import json
import sqlite3

import pytest

from app.contracts.events import AgentEvent
from app.storage.database import Database, transaction
from app.runtime.outbox import Outbox, enqueue_event
from app.runtime.recovery import Recovery
from test_state_machine import initialize_runtime, current, create_revision_and_gate


def existing_remote(tmp_path):
    path = initialize_runtime(tmp_path,"EXECUTING")
    connection = Database(path).connect()
    connection.execute("UPDATE task_runs SET external_request_id='request-existing',external_execution_id='remote-existing',lease_expires_at='2000-01-01T00:00:00Z'")
    connection.close()
    return path


def event(sequence, kind="model.delta", **payload):
    return AgentEvent("task1","a1",sequence,kind,payload or {"text":"INTERNAL_ENGLISH"})


def audits(path):
    connection = Database(path).connect()
    try:
        return [dict(row) for row in connection.execute("SELECT * FROM outbox_events ORDER BY conversation_sequence")]
    finally:
        connection.close()


def test_recovery_queries_existing_remote_before_observing_and_never_creates_a_request(tmp_path):
    path = existing_remote(tmp_path)
    calls = []
    def query(row):
        calls.append(("query",row["external_execution_id"]))
        return "running"
    def observe(row):
        calls.append(("observe",row["external_execution_id"]))
    result = Recovery(path).recover(query, observe)
    assert calls == [("query","remote-existing"),("observe","remote-existing")]
    assert result[0]["remote_status"] == "running"
    assert current(path)["external_request_id"] == "request-existing"
    connection = Database(path).connect()
    assert connection.execute("SELECT count(*) FROM steps").fetchone()[0] == 0
    connection.close()


def test_unknown_remote_with_expired_lease_is_blocked_and_not_retried_after_restart(tmp_path):
    path = existing_remote(tmp_path)
    observations = []
    first = Recovery(path).recover(lambda row:"unknown", observations.append)
    second = Recovery(path).recover(lambda row:"unknown", observations.append)
    assert first[0]["decision"] == second[0]["decision"] == "blocked_unknown"
    assert current(path)["state"] == "BLOCKED"
    assert observations == []
    assert current(path)["external_request_id"] == "request-existing"
    assert all(row["public_event_json"] is None for row in audits(path))


def test_remote_query_exception_is_recorded_as_unknown_without_unverified_failure(tmp_path):
    path = existing_remote(tmp_path)
    def broken(row):
        raise ConnectionError("do not expose endpoint or credentials")
    result = Recovery(path).recover(broken)
    assert result[0]["decision"] == "blocked_unknown"
    assert current(path)["remote_status"] == "unknown"
    payload = json.loads(audits(path)[0]["internal_payload_json"])
    assert payload["query_error"] == "ConnectionError"
    assert "credentials" not in json.dumps(payload)


@pytest.mark.parametrize("verified", [True,False])
def test_remote_completion_enters_verification_or_blocks_but_never_publishes(tmp_path, verified):
    path = existing_remote(tmp_path)
    result = Recovery(path).recover(lambda row:"completed",verify_completed=lambda row:verified)
    assert result[0]["decision"] == ("verification_ready" if verified else "blocked_unverified_completion")
    assert current(path)["state"] == ("VALIDATING" if verified else "BLOCKED")
    assert Outbox(path).replay("c1") == []


def test_confirmed_remote_failure_marks_failed_preserving_request_reference(tmp_path):
    path = existing_remote(tmp_path)
    result = Recovery(path).recover(lambda row:"failed")
    assert result[0]["decision"] == "failed"
    assert current(path)["state"] == "FAILED"
    assert current(path)["external_execution_id"] == "remote-existing"


def test_provider_sequence_is_independent_of_api_accepted_and_pending_sequence(tmp_path):
    path = existing_remote(tmp_path)
    connection = Database(path).connect()
    with transaction(connection):
        enqueue_event(connection,"task1","a1","message.accepted",{},deduplication_key="api-accepted",
                      public_payload={"message_id":"m1","text":"用户问题","language":"zh-CN"})
        enqueue_event(connection,"task1","a1","response.pending",{},deduplication_key="api-pending",public_payload={"status":"pending"})
    connection.close()
    assert current(path)["last_sequence"] == 2
    one = Recovery(path).ingest(event(1),"1.0")
    two = Recovery(path).ingest(event(2),"1.0")
    assert one["applied_sequences"] == [1] and two["applied_sequences"] == [2]
    checkpoint = json.loads(current(path)["checkpoint_json"])
    assert checkpoint["provider_last_sequence"] == 2
    assert current(path)["last_sequence"] == 4
    assert len(Outbox(path).replay("c1")) == 2


def test_sequence_1_2_2_1_3_applies_only_once_and_persists_duplicate_audit(tmp_path):
    path = existing_remote(tmp_path)
    decisions = [Recovery(path).ingest(event(seq),"1.0") for seq in (1,2,2,1,3)]
    assert [item["decision"] for item in decisions] == ["accepted","accepted","duplicate","duplicate","accepted"]
    assert [seq for item in decisions for seq in item["applied_sequences"]] == [1,2,3]
    assert json.loads(current(path)["checkpoint_json"])["provider_last_sequence"] == 3
    assert len(audits(path)) == 5


def test_sequence_gap_and_out_of_order_completion_are_buffered_across_restart(tmp_path):
    path = existing_remote(tmp_path)
    gap = Recovery(path).ingest(event(3,"provider.completed",PASS=True),"1.0")
    assert gap["decision"] == "gap" and gap["applied_sequences"] == []
    assert current(path)["state"] == "EXECUTING"
    assert json.loads(current(path)["checkpoint_json"])["provider_last_sequence"] == 0
    assert Recovery(path).ingest(event(1),"1.0")["applied_sequences"] == [1]
    drained = Recovery(path).ingest(event(2),"1.0")
    assert drained["applied_sequences"] == [2,3]
    assert current(path)["state"] == "VALIDATING"
    checkpoint = json.loads(current(path)["checkpoint_json"])
    assert checkpoint["provider_event_buffer"] == {}
    assert checkpoint["provider_completion_pending"] is True
    assert Outbox(path).replay("c1") == []


def test_mismatched_duplicate_sequence_is_rejected_and_audited(tmp_path):
    path = existing_remote(tmp_path)
    Recovery(path).ingest(event(1,text="first"),"1.0")
    result = Recovery(path).ingest(event(1,text="different"),"1.0")
    assert result["decision"] == "duplicate_conflict" and result["applied_sequences"] == []
    assert json.loads(current(path)["checkpoint_json"])["provider_last_sequence"] == 1
    assert audits(path)[-1]["kind"] == "recovery.event_rejected"


@pytest.mark.parametrize("fault", ["old-attempt","old-contract","old-route"])
def test_old_attempt_contract_or_route_cannot_accept_pass_or_overwrite_state(tmp_path, fault):
    path = existing_remote(tmp_path)
    connection = Database(path).connect()
    if fault == "old-attempt":
        connection.execute("""INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,attempt_number,state)
                           VALUES('task1','a2','t1','p1',2,'EXECUTING')""")
    connection.close()
    record = event(1,"provider.completed",PASS=True,**({"route_snapshot_id":"old-route"} if fault == "old-route" else {}))
    result = Recovery(path).ingest(record,"old-contract" if fault == "old-contract" else "1.0")
    assert result["decision"] == {"old-attempt":"stale_attempt","old-contract":"contract_mismatch","old-route":"route_mismatch"}[fault]
    assert result["applied_sequences"] == [] and current(path)["state"] == "EXECUTING"
    assert Outbox(path).replay("c1") == []


def test_cancelled_completion_is_audited_without_publication_or_new_observation(tmp_path):
    path = existing_remote(tmp_path)
    connection = Database(path).connect()
    connection.execute("UPDATE task_runs SET state='CANCELLED',cancel_requested=1,cancel_pending_remote=1")
    connection.close()
    incoming = Recovery(path).ingest(event(1,"provider.completed",PASS=True),"1.0")
    observed = []
    reconciled = Recovery(path).recover(lambda row:"completed",observed.append,lambda row:True)
    assert incoming["decision"] == "cancelled" and incoming["applied_sequences"] == []
    assert reconciled[0]["decision"] == "cancelled_remote_stopped"
    assert current(path)["state"] == "CANCELLED" and current(path)["external_stop_confirmed"] == 1
    assert current(path)["cancel_pending_remote"] == 0
    assert observed == [] and Outbox(path).replay("c1") == []


def test_ingest_rollback_keeps_sequence_checkpoint_and_state_unchanged(tmp_path):
    path = existing_remote(tmp_path)
    connection = Database(path).connect()
    connection.execute("CREATE TRIGGER audit_failure BEFORE INSERT ON outbox_events BEGIN SELECT RAISE(ABORT,'fault'); END")
    connection.close()
    with pytest.raises(sqlite3.IntegrityError,match="fault"):
        Recovery(path).ingest(event(1),"1.0")
    assert json.loads(current(path)["checkpoint_json"]).get("provider_last_sequence",0) == 0
    assert current(path)["state"] == "EXECUTING"


def test_stable_provider_key_duplicate_does_not_apply_again(tmp_path):
    path = existing_remote(tmp_path)
    first = Recovery(path).ingest(event(1,provider_event_id="stable-1",text="first"),"1.0")
    second = Recovery(path).ingest(event(2,provider_event_id="stable-1",text="first"),"1.0")
    assert first["applied_sequences"] == [1]
    assert second["decision"] == "duplicate" and second["applied_sequences"] == []
    assert json.loads(current(path)["checkpoint_json"])["provider_last_sequence"] == 2


def test_buffered_error_prevents_later_buffered_completion_from_resurrecting_failed_task(tmp_path):
    path = existing_remote(tmp_path)
    Recovery(path).ingest(event(2,"provider.error",reason_code="failed"),"1.0")
    Recovery(path).ingest(event(3,"provider.completed",PASS=True),"1.0")
    accepted = Recovery(path).ingest(event(1),"1.0")
    assert accepted["applied_sequences"] == [1,2]
    assert current(path)["state"] == "FAILED"
    late = Recovery(path).ingest(event(3,"provider.completed",PASS=True),"1.0")
    assert late["decision"] == "terminal" and current(path)["state"] == "FAILED"


def test_stable_key_duplicate_that_closes_gap_drains_buffered_next_event(tmp_path):
    path = existing_remote(tmp_path)
    Recovery(path).ingest(event(1,provider_event_id="stable-1",text="first"),"1.0")
    Recovery(path).ingest(event(3,"provider.completed",PASS=True),"1.0")
    closing = Recovery(path).ingest(event(2,provider_event_id="stable-1",text="first"),"1.0")
    assert closing["decision"] == "duplicate" and closing["applied_sequences"] == [3]
    assert current(path)["state"] == "VALIDATING"
    assert json.loads(current(path)["checkpoint_json"])["provider_last_sequence"] == 3


def test_cancel_during_remote_query_fences_completion_verifier_callback(tmp_path):
    path = existing_remote(tmp_path)
    verified = []
    def query_then_cancel(row):
        connection = Database(path).connect()
        connection.execute("UPDATE task_runs SET state='CANCELLED',cancel_requested=1,cancel_pending_remote=1")
        connection.close()
        return "completed"
    result = Recovery(path).recover(query_then_cancel,verify_completed=lambda row:verified.append(row) or True)
    assert verified == []
    assert result[0]["decision"] == "cancelled_remote_stopped"
    assert current(path)["state"] == "CANCELLED"


def test_disorder_without_legacy_payload_history_is_audited_not_applied(tmp_path):
    path = existing_remote(tmp_path)
    connection = Database(path).connect()
    connection.execute("UPDATE task_runs SET checkpoint_json='{" + '"provider_last_sequence":5' + "}'")
    connection.close()
    result = Recovery(path).ingest(event(3),"1.0")
    assert result["decision"] == "disorder" and result["applied_sequences"] == []
    assert json.loads(audits(path)[-1]["internal_payload_json"])["decision"] == "disorder"


@pytest.mark.parametrize("state", ["RECEIVED","PLANNING","EXECUTING"])
def test_unstarted_local_task_is_preserved_without_remote_query_or_new_request(tmp_path,state):
    path = initialize_runtime(tmp_path,state)
    called = []
    result = Recovery(path).recover(lambda row:called.append("query") or "unknown",lambda row:called.append("observe"))
    assert result[0]["decision"] == "local_pending"
    assert current(path)["state"] == state and called == []
    assert current(path)["external_request_id"] is None


@pytest.mark.parametrize("terminal", ["FAILED","PUBLISHED"])
def test_terminal_transition_during_remote_query_prevents_verifier_and_state_resurrection(tmp_path,terminal):
    path = existing_remote(tmp_path)
    calls = []
    def query(row):
        connection = Database(path).connect()
        connection.execute("UPDATE task_runs SET state=?", (terminal,))
        connection.close()
        return "completed"
    recovered = Recovery(path).recover(query,verify_completed=lambda row:calls.append(row["state"]) or True)
    assert current(path)["state"] == terminal
    assert calls == [] and recovered[0]["decision"] == "terminal_preserved"


def test_terminal_transition_inside_verifier_is_preserved_by_final_transaction(tmp_path):
    path = existing_remote(tmp_path)
    def verify(row):
        connection = Database(path).connect()
        connection.execute("UPDATE task_runs SET state='FAILED'")
        connection.close()
        return True
    result = Recovery(path).recover(lambda row:"completed",verify_completed=verify)
    assert current(path)["state"] == "FAILED" and result[0]["decision"] == "terminal_preserved"


def test_duplicate_stable_key_arriving_before_gap_closes_is_kept_as_noop_sequence(tmp_path):
    path = existing_remote(tmp_path)
    records = [event(1,provider_event_id="stable",text="first"), event(3,provider_event_id="stable",text="first"),
               event(4,"provider.completed",result="done"),event(2,text="second")]
    outcomes = [Recovery(path).ingest(record,"1.0") for record in records]
    assert [seq for outcome in outcomes for seq in outcome["applied_sequences"]] == [1,2,4]
    checkpoint = json.loads(current(path)["checkpoint_json"])
    assert checkpoint["provider_last_sequence"] == 4 and checkpoint["provider_event_buffer"] == {}
    assert current(path)["state"] == "VALIDATING"


def set_active_remote_step(path,step_id="remote-step",request_id="real-current-request",execution_id="real-current-execution"):
    connection = Database(path).connect()
    try:
        connection.execute("""INSERT OR IGNORE INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,connection_version)
            VALUES('p2','fake','fixture-glm','glm','beta-connection','unknown','test-only')""")
        reference = dict(step_id=step_id,provider_profile_id="p2",role="B",external_request_id=request_id,
                         external_execution_id=execution_id,accepted=True,status="running" if request_id or execution_id else "unknown")
        connection.execute("""INSERT INTO steps(id,task_id,attempt_id,step_key,role,state,provider_profile_id,external_request_id,
            external_execution_id,checkpoint_json) VALUES(?,'task1','a1',?,'B','RUNNING','p2',?,?,?)""",
                           (step_id,step_id,"local-call-"+step_id,execution_id,json.dumps({"remote_execution":reference})))
        checkpoint = json.loads(connection.execute("SELECT checkpoint_json FROM task_runs WHERE task_id='task1'").fetchone()[0])
        checkpoint["active_external_request"] = reference
        connection.execute("UPDATE task_runs SET checkpoint_json=? WHERE task_id='task1'",(json.dumps(checkpoint),))
        return reference
    finally:
        connection.close()


def test_recovery_queries_and_observes_current_step_profile_instead_of_frozen_a_and_first_request(tmp_path):
    path = existing_remote(tmp_path)
    reference = set_active_remote_step(path)
    calls = []
    def capture(action,row):
        calls.append((action,row["provider_profile_id"],row["external_request_id"],row["external_execution_id"],
                      row["task_provider_profile_id"],row["active_external_request"]["step_id"]))
        return "running"
    Recovery(path).recover(lambda row:capture("query",row),lambda row:capture("observe",row))
    assert calls == [(action,"p2",reference["external_request_id"],reference["external_execution_id"],"p1",reference["step_id"])
                     for action in ("query","observe")]
    assert current(path)["provider_profile_id"] == "p1"
    assert current(path)["external_request_id"] == "request-existing"


@pytest.mark.parametrize("stale_main_references",[False,True])
def test_accepted_current_step_without_refs_blocks_unknown_without_querying_stale_main_ids(tmp_path,stale_main_references):
    path = existing_remote(tmp_path) if stale_main_references else initialize_runtime(tmp_path,"EXECUTING")
    set_active_remote_step(path,request_id=None,execution_id=None)
    calls = []
    result = Recovery(path).recover(lambda row:calls.append(row) or "running")
    assert calls == [] and current(path)["state"] == "BLOCKED"
    assert result[0]["decision"] == "blocked_unknown"
    assert result[0]["query_error"] == "REMOTE_EXECUTION_REFERENCE_MISSING"


@pytest.mark.parametrize("damage",["missing-step","wrong-profile","step-snapshot-mismatch"])
def test_invalid_current_step_binding_blocks_without_remote_callback(tmp_path,damage):
    path = existing_remote(tmp_path)
    reference = set_active_remote_step(path)
    connection = Database(path).connect()
    try:
        checkpoint = json.loads(current(path)["checkpoint_json"])
        if damage == "missing-step":
            checkpoint["active_external_request"]["step_id"] = "missing"
        elif damage == "wrong-profile":
            checkpoint["active_external_request"]["provider_profile_id"] = "p1"
        else:
            connection.execute("UPDATE steps SET checkpoint_json='{}' WHERE id=?",(reference["step_id"],))
        connection.execute("UPDATE task_runs SET checkpoint_json=?",(json.dumps(checkpoint),))
    finally:
        connection.close()
    calls = []
    result = Recovery(path).recover(lambda row:calls.append(row) or "completed",verify_completed=lambda row:True)
    assert calls == [] and current(path)["state"] == "BLOCKED"
    assert result[0]["query_error"] == "REMOTE_EXECUTION_BINDING_INVALID"


def test_current_step_change_during_remote_query_rejects_old_completion(tmp_path):
    path = existing_remote(tmp_path)
    set_active_remote_step(path,step_id="step-old")
    verified = []
    def query(row):
        set_active_remote_step(path,step_id="step-new",request_id="request-new",execution_id="execution-new")
        return "completed"
    result = Recovery(path).recover(query,verify_completed=lambda row:verified.append(row) or True)
    assert verified == [] and current(path)["state"] == "EXECUTING"
    assert result[0]["decision"] == "external_reference_changed"
    assert json.loads(current(path)["checkpoint_json"])["active_external_request"]["step_id"] == "step-new"
