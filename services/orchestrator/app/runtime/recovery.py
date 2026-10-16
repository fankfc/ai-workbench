"""Reconcile existing remote work and persist provider event decisions."""
from pathlib import Path
from contextlib import closing
from dataclasses import asdict, is_dataclass
import hashlib
import json
import uuid

from app.contracts.events import InternalEventRecord
from app.storage.database import Database, transaction
from .outbox import enqueue_event
from .state_machine import require_current_attempt, checkpoint_for, route_id_for, TransitionError, TRANSITIONS


class Recovery:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def recover(self, query_remote, observe=None, verify_completed=None, *, resume_publications=False, provider_mode=None):
        with closing(Database(self.database_path).connect()) as connection:
            unfinished = [dict(row) for row in connection.execute("""SELECT * FROM task_runs
                WHERE state NOT IN ('PUBLISHED','FAILED','CANCELLED') OR (state='CANCELLED' AND cancel_pending_remote=1)
                ORDER BY task_id,attempt_number DESC""")]
            snapshots = []
            for row in unfinished:
                try:
                    require_current_attempt(connection,row["task_id"],row["attempt_id"])
                    snapshots.append(_remote_context(connection,row))
                except TransitionError:
                    pass
        results = []
        for snapshot in snapshots:
            try:
                checkpoint_for(snapshot)
            except (ValueError, TypeError):
                # A corrupt task must not prevent every other conversation
                # from opening, including on subsequent restarts. Keep its
                # original diagnostic bytes and never query/restart a model.
                with closing(Database(self.database_path).connect()) as connection, transaction(connection):
                    try:
                        row = require_current_attempt(connection, snapshot['task_id'], snapshot['attempt_id'])
                    except TransitionError:
                        results.append(dict(task_id=snapshot['task_id'], attempt_id=snapshot['attempt_id'],
                            decision='stale_attempt', state=snapshot['state'], remote_status=snapshot['remote_status']))
                        continue
                    state = row['state']
                    decision = 'terminal_preserved' if state in {'PUBLISHED', 'FAILED', 'CANCELLED'} else 'local_recovery_deferred'
                    if state not in {'PUBLISHED', 'FAILED', 'CANCELLED'} and row['lease_owner'] is None:
                        state, decision = 'BLOCKED', 'blocked_invalid_checkpoint'
                        connection.execute("UPDATE task_runs SET state='BLOCKED' WHERE task_id=? AND attempt_id=?",
                            (row['task_id'], row['attempt_id']))
                        enqueue_event(connection, row['task_id'], row['attempt_id'], 'request.failed',
                            {'error_code': 'VALIDATION_FAILED'}, deduplication_key='invalid-checkpoint:' + row['attempt_id'])
                    result = dict(task_id=row['task_id'], attempt_id=row['attempt_id'], state=state,
                        decision=decision, remote_status=row['remote_status'])
                    _audit(connection, row, 'recovery.invalid_checkpoint', result)
                results.append(result)
                continue
            if resume_publications and snapshot['state'] == 'READY' and not snapshot['cancel_requested']:
                from .startup_publication import resume_staged_publication
                result = resume_staged_publication(self.database_path, snapshot, provider_mode)
                with closing(Database(self.database_path).connect()) as connection, transaction(connection):
                    _audit(connection, snapshot, 'recovery.local_publication', result)
                results.append(result)
                continue
            if (not snapshot.get("has_active_external_request") and not snapshot["external_request_id"]
                    and not snapshot["external_execution_id"]):
                with closing(Database(self.database_path).connect()) as connection:
                    with transaction(connection):
                        row = require_current_attempt(connection,snapshot["task_id"],snapshot["attempt_id"],snapshot["contract_version"])
                        result = {"task_id":row["task_id"],"attempt_id":row["attempt_id"],"remote_status":row["remote_status"],
                                  "decision":"local_pending","state":row["state"]}
                        _audit(connection,row,"recovery.local_pending",result)
                results.append(result)
                continue
            query_error = snapshot.get("remote_context_error")
            if query_error is None and snapshot.get("has_active_external_request") and not snapshot["external_request_id"] and not snapshot["external_execution_id"]:
                query_error = "REMOTE_EXECUTION_REFERENCE_MISSING"
            if query_error is not None:
                status = "unknown"
            else:
                try:
                    response = query_remote(snapshot)
                    status = response.get("status") if isinstance(response,dict) else response
                    if status not in {"running","completed","failed","unknown"}:
                        status = "unknown"
                except Exception as error:
                    status = "unknown"
                    query_error = type(error).__name__
            verified = False
            verification_error = None
            # Recheck before invoking any completion observer/verifier callback.
            with closing(Database(self.database_path).connect()) as connection:
                try:
                    current = _remote_context(connection,require_current_attempt(connection,snapshot["task_id"],snapshot["attempt_id"],snapshot["contract_version"]))
                except TransitionError:
                    current = None
            if (current is not None and not current["cancel_requested"] and current["state"] not in {"FAILED","PUBLISHED"}
                    and _remote_key(current) == _remote_key(snapshot) and not current.get("remote_context_error")
                    and status == "completed" and verify_completed is not None):
                try:
                    verified = verify_completed(current) is True
                except Exception as error:
                    verification_error = type(error).__name__
            with closing(Database(self.database_path).connect()) as connection:
                with transaction(connection):
                    try:
                        row = require_current_attempt(connection,snapshot["task_id"],snapshot["attempt_id"],snapshot["contract_version"])
                    except TransitionError:
                        result = {"task_id":snapshot["task_id"],"attempt_id":snapshot["attempt_id"],"remote_status":status,"decision":"stale_attempt"}
                        _audit(connection,snapshot,"recovery.remote_status",result)
                        results.append(result)
                        continue
                    current_context = _remote_context(connection,row)
                    if _remote_key(current_context) != _remote_key(snapshot):
                        result = {"task_id":row["task_id"],"attempt_id":row["attempt_id"],"remote_status":row["remote_status"],
                                  "decision":"external_reference_changed","state":row["state"]}
                        _audit(connection,row,"recovery.remote_status",result)
                        results.append(result)
                        continue
                    if row["state"] in {"FAILED","PUBLISHED"}:
                        result = {"task_id":row["task_id"],"attempt_id":row["attempt_id"],"remote_status":status,
                                  "decision":"terminal_preserved","state":row["state"]}
                        _audit(connection,row,"recovery.remote_status",result)
                        results.append(result)
                        continue
                    checkpoint = checkpoint_for(row)
                    state = row["state"]
                    pending = row["cancel_pending_remote"]
                    stopped = row["external_stop_confirmed"]
                    if row["cancel_requested"] or state == "CANCELLED":
                        state = "CANCELLED"
                        checkpoint.pop("release_registry",None)
                        if status in {"completed","failed"}:
                            stopped, pending, decision = 1, 0, "cancelled_remote_stopped"
                        else:
                            pending, decision = 1, "cancelled_remote_pending"
                    elif status == "unknown":
                        if state != "BLOCKED":
                            checkpoint["recovery_resume_state"] = state
                        state, decision = "BLOCKED", "blocked_unknown"
                        checkpoint.pop("release_registry",None)
                    elif status == "failed":
                        state, decision = "FAILED", "failed"
                        checkpoint.pop("release_registry",None)
                    elif status == "completed":
                        if verified:
                            if state not in {"VALIDATING","REVIEWING","OUTPUT_PREPARING","READY"}:
                                state = "VALIDATING"
                            decision = "verification_ready"
                        else:
                            checkpoint["recovery_resume_state"] = state
                            state, decision = "BLOCKED", "blocked_unverified_completion"
                            checkpoint.pop("release_registry",None)
                        checkpoint["provider_completion_pending"] = True
                    else:
                        if state in {"BLOCKED","PAUSED"}:
                            resume = checkpoint.get("recovery_resume_state","EXECUTING")
                            if resume not in TRANSITIONS[state] or resume in {"READY","PUBLISHED"}:
                                resume = "EXECUTING"
                            state = resume
                        decision = "observe_running"
                    checkpoint["recovery_decision"] = decision
                    connection.execute("""UPDATE task_runs SET state=?,remote_status=?,cancel_pending_remote=?,external_stop_confirmed=?,checkpoint_json=?,
                        updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE task_id=? AND attempt_id=?""",
                        (state,status,pending,stopped,_json(checkpoint),row["task_id"],row["attempt_id"]))
                    result = {"task_id":row["task_id"],"attempt_id":row["attempt_id"],"remote_status":status,"decision":decision,"state":state,
                              "query_error":query_error,"verification_error":verification_error}
                    _audit(connection,row,"recovery.remote_status",result)
                    refreshed = dict(connection.execute("SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?", (row["task_id"],row["attempt_id"])).fetchone())
            if decision == "observe_running" and observe is not None:
                with closing(Database(self.database_path).connect()) as connection:
                    try:
                        observed_row = _remote_context(connection,require_current_attempt(connection,refreshed["task_id"],refreshed["attempt_id"],refreshed["contract_version"]))
                    except TransitionError:
                        observed_row = None
                if (observed_row is not None and not observed_row["cancel_requested"] and observed_row["state"] not in {"CANCELLED","FAILED","PUBLISHED"}
                        and _remote_key(observed_row) == _remote_key(snapshot) and not observed_row.get("remote_context_error")):
                    observe(observed_row)
            results.append(result)
        return results

    def ingest(self, event, contract_version):
        record = InternalEventRecord.model_validate(asdict(event) if is_dataclass(event) else event)
        value = record.model_dump()
        sequence = record.sequence
        with closing(Database(self.database_path).connect()) as connection:
            with transaction(connection):
                row = connection.execute("SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?", (record.task_id,record.attempt_id)).fetchone()
                if row is None:
                    raise TransitionError("ATTEMPT_NOT_FOUND")
                try:
                    require_current_attempt(connection,record.task_id,record.attempt_id)
                    decision = None
                except TransitionError:
                    decision = "stale_attempt"
                if decision is None and row["contract_version"] != contract_version:
                    decision = "contract_mismatch"
                if decision is None and record.payload.get("route_snapshot_id",route_id_for(row)) != route_id_for(row):
                    decision = "route_mismatch"
                if decision is None and (row["cancel_requested"] or row["state"] == "CANCELLED"):
                    decision = "cancelled"
                if decision is None and row["state"] in {"FAILED","PUBLISHED"}:
                    decision = "terminal"
                if decision is not None:
                    _audit(connection,row,"recovery.event_rejected",{"decision":decision,"provider_sequence":sequence,"provider_kind":record.kind})
                    return {"decision":decision,"applied_sequences":[]}
                checkpoint = checkpoint_for(row)
                last = checkpoint.setdefault("provider_last_sequence",0)
                history = checkpoint.setdefault("provider_event_history",{})
                buffer = checkpoint.setdefault("provider_event_buffer",{})
                stable_keys = checkpoint.setdefault("provider_stable_keys",{})
                fingerprint = _fingerprint(value)
                semantic = _fingerprint({"kind":record.kind,"payload":record.payload})
                stable = record.payload.get("provider_event_id")
                applied = []
                if str(sequence) in history:
                    decision = "duplicate" if history[str(sequence)] == fingerprint else "duplicate_conflict"
                elif isinstance(stable,str) and stable in stable_keys:
                    decision = "duplicate" if stable_keys[stable] == semantic else "duplicate_conflict"
                    if decision == "duplicate" and sequence > last:
                        previous = buffer.get(str(sequence))
                        if previous is not None and _fingerprint(previous) != fingerprint:
                            decision = "duplicate_conflict"
                        else:
                            # Keep a no-effect event at every future sequence;
                            # otherwise a duplicate arriving before a gap closes
                            # leaves following completion permanently buffered.
                            buffer[str(sequence)] = value
                elif sequence <= last:
                    decision = "disorder"
                elif sequence > last + 1:
                    previous = buffer.get(str(sequence))
                    if previous is not None and _fingerprint(previous) != fingerprint:
                        decision = "duplicate_conflict"
                    elif previous is not None:
                        decision = "duplicate"
                    else:
                        buffer[str(sequence)] = value
                        decision = "gap"
                else:
                    decision = "accepted"
                    buffer[str(sequence)] = value
                if decision in {"accepted","duplicate"}:
                    applied = _drain_provider_buffer(connection,row,checkpoint)
                if decision != "accepted":
                    _audit(connection,row,"recovery.event_rejected" if decision in {"duplicate_conflict","disorder"} else "recovery.event_audit",
                           {"decision":decision,"provider_sequence":sequence,"provider_kind":record.kind,"expected_provider_sequence":last+1})
                connection.execute("UPDATE task_runs SET checkpoint_json=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE task_id=? AND attempt_id=?",
                                   (_json(checkpoint),record.task_id,record.attempt_id))
                return {"decision":decision,"applied_sequences":applied,"provider_last_sequence":checkpoint["provider_last_sequence"]}


def _drain_provider_buffer(connection,row,checkpoint):
    buffer = checkpoint["provider_event_buffer"]
    history = checkpoint["provider_event_history"]
    stable_keys = checkpoint["provider_stable_keys"]
    applied = []
    state = row["state"]
    while str(checkpoint["provider_last_sequence"] + 1) in buffer:
        sequence = checkpoint["provider_last_sequence"] + 1
        event = buffer.pop(str(sequence))
        semantic = _fingerprint({"kind":event["kind"],"payload":event["payload"]})
        key = event["payload"].get("provider_event_id")
        if isinstance(key,str) and key in stable_keys:
            if stable_keys[key] != semantic:
                buffer[str(sequence)] = event
                _audit(connection,row,"recovery.event_rejected",{"decision":"duplicate_conflict","provider_sequence":sequence})
                break
        else:
            if isinstance(key,str):
                stable_keys[key] = semantic
            _audit(connection,row,"provider.event_accepted",{"provider_sequence":sequence,"provider_kind":event["kind"],"provider_payload":event["payload"]})
            applied.append(sequence)
            if event["kind"] == "provider.completed":
                checkpoint["provider_completion_pending"] = True
                if state == "EXECUTING":
                    state = "VALIDATING"
                    connection.execute("UPDATE task_runs SET state=? WHERE task_id=? AND attempt_id=?", (state,row["task_id"],row["attempt_id"]))
            elif event["kind"] == "provider.error":
                checkpoint.pop("release_registry",None)
                state = "FAILED"
                connection.execute("UPDATE task_runs SET state=? WHERE task_id=? AND attempt_id=?", (state,row["task_id"],row["attempt_id"]))
        history[str(sequence)] = _fingerprint(event)
        checkpoint["provider_last_sequence"] = sequence
        if state == "FAILED":
            break
    return applied


def _audit(connection,row,kind,payload):
    return enqueue_event(connection,row["task_id"],row["attempt_id"],kind,payload,deduplication_key="audit:"+uuid.uuid4().hex)


def _remote_context(connection,row):
    """Keep the A route frozen while observing the current A/B invocation."""
    context = dict(row)
    context["task_provider_profile_id"] = row["provider_profile_id"]
    context["has_active_external_request"] = False
    try:
        active = checkpoint_for(row).get("active_external_request")
        if active is None:
            return context  # Legacy attempts retain their task-level association.
        context["has_active_external_request"] = True
        if not isinstance(active,dict) or active.get("accepted") is not True or active.get("status") not in {"running","completed","unknown"}:
            raise ValueError("INVALID_ACTIVE_REMOTE_REFERENCE")
        for key in ("step_id","provider_profile_id","role"):
            if not isinstance(active.get(key),str) or not active[key].strip():
                raise ValueError("INVALID_ACTIVE_REMOTE_REFERENCE")
        for key in ("external_request_id","external_execution_id"):
            if active.get(key) is not None and (not isinstance(active[key],str) or not active[key].strip()):
                raise ValueError("INVALID_ACTIVE_REMOTE_REFERENCE")
        step = connection.execute("SELECT * FROM steps WHERE id=? AND task_id=? AND attempt_id=?",
                                  (active["step_id"],row["task_id"],row["attempt_id"])).fetchone()
        if (step is None or step["provider_profile_id"] != active["provider_profile_id"] or step["role"] != active["role"]
                or step["contract_version"] != row["contract_version"] or step["external_execution_id"] != active.get("external_execution_id")
                or json.loads(step["checkpoint_json"]).get("remote_execution") != active):
            raise ValueError("INVALID_ACTIVE_REMOTE_BINDING")
        context["active_external_request"] = dict(active)
        context["provider_profile_id"] = active["provider_profile_id"]
        context["external_request_id"] = active.get("external_request_id")
        context["external_execution_id"] = active.get("external_execution_id")
    except (ValueError,TypeError,KeyError,AttributeError):
        context["has_active_external_request"] = True
        context["remote_context_error"] = "REMOTE_EXECUTION_BINDING_INVALID"
    return context


def _remote_key(context):
    active = context.get("active_external_request",{})
    return (bool(context.get("has_active_external_request")),active.get("step_id"),context["provider_profile_id"],
            context["external_request_id"],context["external_execution_id"],context.get("remote_context_error"))


def _json(value):
    return json.dumps(value,ensure_ascii=False,separators=(",",":"),sort_keys=True,allow_nan=False)


def _fingerprint(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()
