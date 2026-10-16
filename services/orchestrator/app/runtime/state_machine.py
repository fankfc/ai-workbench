"""Persisted state transitions and release approval references."""
from pathlib import Path
from contextlib import closing
import json
import uuid

from app.storage.database import Database, transaction
from .outbox import enqueue_event


class TransitionError(ValueError):
    pass


NORMAL_PATH = ("RECEIVED", "INPUT_PREPARING", "PLANNING", "EXECUTING", "VALIDATING", "REVIEWING", "OUTPUT_PREPARING", "READY", "PUBLISHED")
BRANCHES = {"NEEDS_INPUT", "REPAIRING", "BLOCKED", "PAUSED", "FAILED", "CANCELLED"}
TRANSITIONS = {before: frozenset({after} | BRANCHES) for before, after in zip(NORMAL_PATH,NORMAL_PATH[1:])}
TRANSITIONS.update({
    "CREATED": frozenset({"RECEIVED", "FAILED", "CANCELLED"}),
    "NEEDS_INPUT": frozenset({"INPUT_PREPARING","PLANNING","BLOCKED","PAUSED","FAILED","CANCELLED"}),
    "REPAIRING": frozenset({"EXECUTING","VALIDATING","REVIEWING","OUTPUT_PREPARING","NEEDS_INPUT","BLOCKED","PAUSED","FAILED","CANCELLED"}),
    "BLOCKED": frozenset({"INPUT_PREPARING","PLANNING","EXECUTING","VALIDATING","NEEDS_INPUT","PAUSED","FAILED","CANCELLED"}),
    "PAUSED": frozenset({"INPUT_PREPARING","PLANNING","EXECUTING","VALIDATING","REVIEWING","OUTPUT_PREPARING","NEEDS_INPUT","BLOCKED","FAILED","CANCELLED"}),
    "FAILED": frozenset(), "CANCELLED": frozenset(), "PUBLISHED": frozenset(),
})


class StateMachine:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def transition(self, task_id, attempt_id, expected_state, new_state, contract_version, payload=None):
        if payload is not None and not isinstance(payload, dict):
            raise TransitionError("TRANSITION_PAYLOAD_INVALID")
        with closing(Database(self.database_path).connect()) as connection:
            with transaction(connection):
                row = require_current_attempt(connection, task_id, attempt_id, contract_version)
                if row["state"] != expected_state:
                    raise TransitionError("EXPECTED_STATE_MISMATCH")
                if row["cancel_requested"] or row["state"] == "CANCELLED":
                    if new_state != "CANCELLED":
                        raise TransitionError("CANCELLED_FENCE")
                if new_state not in TRANSITIONS.get(expected_state, frozenset()):
                    raise TransitionError("ILLEGAL_TRANSITION")
                checkpoint = checkpoint_for(row)
                if new_state in {"READY", "PUBLISHED"}:
                    validate_release_gate(connection, row, checkpoint)
                cancel_requested = row["cancel_requested"]
                pending_remote = row["cancel_pending_remote"]
                if new_state == "CANCELLED":
                    checkpoint.pop("release_registry", None)
                    cancel_requested = 1
                    pending_remote = int(row["external_stop_confirmed"] != 1 and bool(row["external_request_id"] or row["external_execution_id"]))
                connection.execute("""UPDATE task_runs SET state=?,checkpoint_json=?,cancel_requested=?,cancel_pending_remote=?,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                    completed_at=CASE WHEN ? IN ('CANCELLED','FAILED','PUBLISHED') THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE completed_at END
                    WHERE task_id=? AND attempt_id=?""", (new_state,_json(checkpoint),cancel_requested,pending_remote,new_state,task_id,attempt_id))
                event = enqueue_event(connection,task_id,attempt_id,"task.state_changed",
                    {"expected_state":expected_state,"new_state":new_state,"contract_version":contract_version,"details":payload or {}},
                    deduplication_key="state:"+uuid.uuid4().hex)
                return {"task_id":task_id,"attempt_id":attempt_id,"state":new_state,**{key:event[key] for key in ("event_id","sequence","conversation_sequence")}}


def register_release_gate(connection, task_id, attempt_id, contract_version, artifact_version_id, approval_id, route_snapshot_id):
    if not connection.in_transaction:
        raise TransitionError("RELEASE_GATE_TRANSACTION_REQUIRED")
    row = require_current_attempt(connection,task_id,attempt_id,contract_version)
    from app.operations.controller import assert_publication_allowed
    try:
        assert_publication_allowed(connection, row)
    except ValueError as error:
        raise TransitionError(str(error)) from error
    if row["cancel_requested"] or row["state"] in {"CANCELLED","FAILED","PUBLISHED"}:
        raise TransitionError("CANCELLED_OR_TERMINAL_RELEASE")
    checkpoint = checkpoint_for(row)
    if checkpoint.get("stale") or checkpoint.get("publication_blocked"):
        raise TransitionError("RELEASE_GATE_STALE")
    if checkpoint.get("current_revision_id") != artifact_version_id:
        raise TransitionError("RELEASE_GATE_REVISION_MISMATCH")
    if (not isinstance(approval_id,str) or not approval_id.strip() or not isinstance(route_snapshot_id,str)
            or not route_snapshot_id.strip() or route_id_for(row) != route_snapshot_id):
        raise TransitionError("RELEASE_GATE_ROUTE_OR_APPROVAL_INVALID")
    artifact = connection.execute("SELECT * FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?",
                                  (artifact_version_id,task_id,attempt_id)).fetchone()
    if artifact is None:
        raise TransitionError("RELEASE_GATE_ARTIFACT_MISSING")
    details = dict(approval_id=approval_id,task_id=task_id,attempt_id=attempt_id,contract_version=contract_version,
                   artifact_version_id=artifact_version_id,byte_sha256=artifact["byte_sha256"],route_snapshot_id=route_snapshot_id)
    existing = connection.execute("SELECT * FROM checks WHERE id=?", (approval_id,)).fetchone()
    if existing is not None:
        if existing["check_kind"] != "release.approval" or existing["result"] != "pass" or json.loads(existing["details_json"]) != details:
            raise TransitionError("RELEASE_GATE_APPROVAL_CONFLICT")
    else:
        connection.execute("""INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json)
                            VALUES(?,?,?,?,'release.approval','pass',?,?)""",
                           (approval_id,task_id,attempt_id,artifact_version_id,contract_version,_json(details)))
    checkpoint["release_registry"] = {"check_id":approval_id,"approval_id":approval_id,"artifact_version_id":artifact_version_id,
                                     "content_version_id":artifact_version_id,"route_snapshot_id":route_snapshot_id}
    connection.execute("UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?", (_json(checkpoint),task_id,attempt_id))
    return approval_id


def require_current_attempt(connection, task_id, attempt_id, contract_version=None):
    row = connection.execute("SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?", (task_id,attempt_id)).fetchone()
    if row is None:
        raise TransitionError("ATTEMPT_NOT_FOUND")
    latest = connection.execute("SELECT attempt_id FROM task_runs WHERE task_id=? ORDER BY attempt_number DESC,created_at DESC,attempt_id DESC LIMIT 1", (task_id,)).fetchone()[0]
    if latest != attempt_id:
        raise TransitionError("STALE_ATTEMPT")
    if contract_version is not None and row["contract_version"] != contract_version:
        raise TransitionError("CONTRACT_VERSION_MISMATCH")
    return row


def checkpoint_for(row):
    value = json.loads(row["checkpoint_json"])
    if not isinstance(value, dict):
        raise TransitionError("CHECKPOINT_INVALID")
    return value


def route_id_for(row):
    route = json.loads(row["route_snapshot_json"])
    return route.get("id") if isinstance(route,dict) else None


def validate_release_gate(connection, row, checkpoint):
    from app.operations.controller import assert_publication_allowed
    try:
        assert_publication_allowed(connection, row)
    except ValueError as error:
        raise TransitionError(str(error)) from error
    if checkpoint.get("stale") or checkpoint.get("publication_blocked"):
        raise TransitionError("RELEASE_GATE_STALE")
    registry = checkpoint.get("release_registry")
    if (not isinstance(registry,dict) or not registry.get("check_id") or not registry.get("approval_id")
            or not route_id_for(row)):
        raise TransitionError("RELEASE_GATE_REQUIRED")
    check = connection.execute("SELECT * FROM checks WHERE id=?", (registry["check_id"],)).fetchone()
    artifact_id = checkpoint.get("current_revision_id")
    artifact = connection.execute("SELECT * FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?",
                                  (artifact_id,row["task_id"],row["attempt_id"])).fetchone()
    if check is None or artifact is None or check["check_kind"] != "release.approval" or check["result"] != "pass":
        raise TransitionError("RELEASE_GATE_INVALID")
    expected = dict(approval_id=registry["approval_id"],task_id=row["task_id"],attempt_id=row["attempt_id"],
                    contract_version=row["contract_version"],artifact_version_id=artifact_id,
                    byte_sha256=artifact["byte_sha256"],route_snapshot_id=route_id_for(row))
    if (json.loads(check["details_json"]) != expected or registry.get("artifact_version_id") != artifact_id
            or registry.get("route_snapshot_id") != route_id_for(row)
            or check["artifact_version_id"] != artifact_id or check["task_id"] != row["task_id"]
            or check["attempt_id"] != row["attempt_id"] or check["check_version"] != row["contract_version"]):
        raise TransitionError("RELEASE_GATE_BINDING_MISMATCH")


def _json(value):
    return json.dumps(value,ensure_ascii=False,separators=(",",":"),allow_nan=False)
