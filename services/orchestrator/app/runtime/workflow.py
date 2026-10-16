"""A contract -> B candidate -> mechanical checks -> A review, durably.

Publication is a separate trusted service. No provider completion owns PASS.
External same-user CLI execution and Claude formal output remain blocked until
their required supported scope/language/provenance gates are available.
"""
from __future__ import annotations

import asyncio
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
from pathlib import Path
import uuid

from app.contracts.artifacts import ArtifactDependency, ArtifactVersion
from app.contracts.events import AgentEvent
from app.contracts.providers import AgentRequest, ProviderIdentity,ProviderContract
from app.contracts.tasks import ReviewDecision, contract_digest, evaluate_review, validate_contract
from app.storage.blobs import BlobStore, store_artifact
from app.storage.database import Database, transaction
from app.storage.revisions import activate_revision, is_current_revision
from app.usage.ledger import UsageLedger
from .outbox import enqueue_event
from .dependencies import DependencyGraph
from .repair import RepairTracker
from .state_machine import StateMachine, TRANSITIONS, checkpoint_for, require_current_attempt

_COMPLETION_KINDS = frozenset({"model.completed", "provider.completed"})


@dataclass(frozen=True)
class WorkflowResult:
    state: str
    current_revision_id: str | None = None
    review_check_id: str | None = None
    quality_repairs: int = 0
    connection_retries: int = 0
    translation_retries: int = 0
    reason_codes: tuple[str, ...] = ()
    evidence_root: str = ""


@dataclass(frozen=True)
class CandidateContext:
    contract: object
    workspace: object
    revision_id: str
    artifact_path: Path
    byte_sha256: str
    content: bytes


class _Stop(Exception):
    def __init__(self, state, reasons):
        self.state, self.reasons = state, tuple(reasons)


class _ConnectionFailure(Exception):
    pass


class WorkflowConflict(ValueError):
    pass


class WorkflowBusy(RuntimeError):
    pass


class Workflow:
    def __init__(self, database_path, workspace_manager, adapter, validator, reviewer, budget_port,
                 ledger=None, *, estimated_tokens=None, profile_ids=None,translation_service=None):
        self.database_path = Path(database_path)
        self.database = Database(self.database_path)
        self.workspaces = workspace_manager
        self.adapter, self.validator, self.reviewer = adapter, validator, reviewer
        self.budget_port = budget_port
        self.ledger = ledger or UsageLedger(self.database_path)
        self.estimates = dict(estimated_tokens or {})
        self.profile_ids = dict(profile_ids or {"A": "fake-gpt", "B": "fake-glm"})
        self.store = BlobStore(self.database_path.parent / "blobs")
        self.machine = StateMachine(self.database_path)
        self.translation_service=translation_service
        if translation_service is not None and Path(translation_service.database_path).resolve()!=self.database_path.resolve():
            raise ValueError('LANGUAGE_SERVICE_DATABASE_MISMATCH')
        self._locks = {}
        self._owners = {}

    def _row(self, contract):
        with closing(self.database.connect()) as connection:
            return dict(require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version))

    def _guard(self, contract):
        row = self._row(contract)
        self._guard_row(row, contract)
        return row

    def _guard_row(self, row, contract):
        if row["state"] in {"FAILED", "PUBLISHED"}:
            raise _Stop(row["state"], ["TERMINAL_STATE_FENCE"])
        if row["cancel_requested"] or row["state"] == "CANCELLED":
            raise _Stop("CANCELLED", ["CANCELLED_FENCE"])
        if checkpoint_for(row).get('identity_changed'):
            raise _Stop('PAUSED',['MODEL_IDENTITY_CHANGED'])
        if row["lease_owner"] != self._owners.get((contract.task_id, contract.attempt_id)):
            raise WorkflowBusy("WORKFLOW_BUSY")
        active = checkpoint_for(row).get("active_external_request", {})
        if active.get("status") == "unknown" and row["external_stop_confirmed"] != 1:
            raise _Stop("BLOCKED", ["UNKNOWN_REMOTE"])

    @staticmethod
    def _initial_workflow(contract):
        return {"contract_sha256": contract_digest(contract), "candidate_history": [],
            "current_revision_id": None, "review_check_id": None, "reviews": [], "takeover_leases": [],
            "repair": RepairTracker().snapshot(), "reason_codes": []}

    def _claim(self, contract):
        owner = "workflow:" + uuid.uuid4().hex
        with closing(self.database.connect()) as connection, transaction(connection):
            row = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
            checkpoint = checkpoint_for(row)
            previous = checkpoint.get("workflow")
            if isinstance(previous, dict) and previous.get("contract_sha256") != contract_digest(contract):
                raise WorkflowConflict("WORKFLOW_CONTRACT_DIGEST_MISMATCH")
            if row["lease_owner"] is not None:
                raise WorkflowBusy("WORKFLOW_BUSY")
            if row["state"] != "RECEIVED":
                return None, dict(row)
            checkpoint["workflow"] = self._initial_workflow(contract)
            checkpoint["task_contract"] = contract.model_dump(mode="json")
            connection.execute("UPDATE task_runs SET lease_owner=?,lease_expires_at=?,checkpoint_json=? WHERE task_id=? AND attempt_id=?",
                (owner, (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
                 json.dumps(checkpoint, ensure_ascii=False, allow_nan=False), contract.task_id, contract.attempt_id))
        return owner, None

    def _release_owner(self, contract, owner):
        with closing(self.database.connect()) as connection, transaction(connection):
            connection.execute("UPDATE task_runs SET lease_owner=NULL,lease_expires_at=NULL WHERE task_id=? AND attempt_id=? AND lease_owner=?",
                               (contract.task_id, contract.attempt_id, owner))

    def _existing_result(self, contract, row):
        checkpoint = checkpoint_for(row)
        previous = checkpoint.get("workflow", {})
        repairs = previous.get("repair", {})
        workspace = self.workspaces.create(contract.task_id, contract.attempt_id)
        return WorkflowResult(row["state"], previous.get("current_revision_id"), previous.get("review_check_id"),
            repairs.get("quality_repairs", 0), repairs.get("connection_retries", 0), repairs.get("translation_retries", 0),
            tuple(previous.get("reason_codes", [])), str(workspace.area("evidence")))

    def _transition(self, contract, state, payload=None):
        row = self._guard(contract)
        self.machine.transition(contract.task_id, contract.attempt_id, row["state"], state,
                                contract.contract_version, payload)

    def _checkpoint(self, contract, workflow, **extra):
        with closing(self.database.connect()) as connection, transaction(connection):
            row = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
            if not self._owns_or_cancelled(row, contract):
                raise WorkflowBusy("WORKFLOW_BUSY")
            checkpoint = checkpoint_for(row)
            checkpoint["workflow"] = workflow
            checkpoint.update(extra)
            connection.execute("UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?",
                (json.dumps(checkpoint, ensure_ascii=False, allow_nan=False), contract.task_id, contract.attempt_id))

    def _owns_or_cancelled(self, row, contract):
        owner = self._owners.get((contract.task_id, contract.attempt_id))
        if owner is None:
            return False
        if row["lease_owner"] == owner:
            return True
        # API cancellation revokes the task lease. The original owner may only
        # preserve its cancelled audit; a new owner or any new start is denied.
        return (row["lease_owner"] is None and bool(row["cancel_requested"])
                and checkpoint_for(row).get("workflow", {}).get("contract_sha256") == contract_digest(contract))

    @staticmethod
    def _public_error_code(reasons):
        if any("CLAUDE" in reason or "LANGUAGE" in reason for reason in reasons):
            return "LANGUAGE_GATE_MISSING"
        if any("BUDGET" in reason or reason in {"UNKNOWN_USAGE", "ESTIMATE_REQUIRED"} for reason in reasons):
            return "BUDGET_EXHAUSTED"
        if any("PROVIDER" in reason or "CONNECTION" in reason or "SCOPE_ENFORCEMENT" in reason
               or reason == "UNKNOWN_REMOTE" for reason in reasons):
            return "PROVIDER_UNAVAILABLE"
        return "VALIDATION_FAILED"

    def _stop(self, contract, workflow, state):
        """Commit a stop checkpoint, state, and safe public signal together."""
        with closing(self.database.connect()) as connection, transaction(connection):
            row = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
            if not self._owns_or_cancelled(row, contract):
                raise WorkflowBusy("WORKFLOW_BUSY")
            if row["cancel_requested"] or row["state"] == "CANCELLED":
                state = "CANCELLED"
            checkpoint = checkpoint_for(row)
            checkpoint["workflow"] = workflow
            pending_remote = row["cancel_pending_remote"]
            if state == "CANCELLED":
                checkpoint.pop("release_registry", None)
                accepted = checkpoint.get("active_external_request", {}).get("accepted") is True
                pending_remote = int(row["external_stop_confirmed"] != 1 and
                    (accepted or bool(row["external_request_id"] or row["external_execution_id"])))
            if row["state"] not in {"CANCELLED", "FAILED", "PUBLISHED"} and row["state"] != state:
                if state not in TRANSITIONS.get(row["state"], frozenset()):
                    raise ValueError("ILLEGAL_WORKFLOW_STOP")
                cancel_requested = int(state == "CANCELLED") or row["cancel_requested"]
                connection.execute("""UPDATE task_runs SET state=?,cancel_requested=?,cancel_pending_remote=?,
                    completed_at=CASE WHEN ? IN ('FAILED','CANCELLED') THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE completed_at END,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE task_id=? AND attempt_id=?""",
                    (state, cancel_requested, pending_remote, state, contract.task_id, contract.attempt_id))
                enqueue_event(connection, contract.task_id, contract.attempt_id, "task.state_changed",
                    {"expected_state": row["state"], "new_state": state, "contract_version": contract.contract_version},
                    deduplication_key=f"workflow-stop-state:{contract.task_id}:{contract.attempt_id}:{state}")
            connection.execute("UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?",
                (json.dumps(checkpoint, ensure_ascii=False, allow_nan=False), contract.task_id, contract.attempt_id))
            if state == "CANCELLED" and row["state"] not in {"FAILED", "PUBLISHED"}:
                connection.execute("UPDATE task_runs SET cancel_pending_remote=? WHERE task_id=? AND attempt_id=?",
                    (pending_remote, contract.task_id, contract.attempt_id))
            if state == "NEEDS_INPUT" and not checkpoint.get('clarification_release'):
                enqueue_event(connection, contract.task_id, contract.attempt_id, "input.required",
                    {"prompt_code": "missing_input"},
                    deduplication_key=f"workflow-feedback:{contract.task_id}:{contract.attempt_id}:missing_input")
            elif state in {"BLOCKED", "FAILED"}:
                code = self._public_error_code(workflow["reason_codes"])
                enqueue_event(connection, contract.task_id, contract.attempt_id, "request.failed",
                    {"error_code": code},
                    deduplication_key=f"workflow-feedback:{contract.task_id}:{contract.attempt_id}:{state}:{code}")

    def _observe(self, contract, kind, payload, key=None):
        with closing(self.database.connect()) as connection, transaction(connection):
            return enqueue_event(connection, contract.task_id, contract.attempt_id, kind, payload,
                deduplication_key=key or (kind + ":" + uuid.uuid4().hex))

    def _profile(self, role, route):
        profile_id = self.profile_ids.get(role)
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM provider_profiles WHERE id=? AND enabled=1", (profile_id,)).fetchone()
        if row is None:
            raise _Stop("BLOCKED", ["PROVIDER_PROFILE_MISSING"])
        if not route.get("test_only") and row["identity_status"] != "verified":
            raise _Stop("BLOCKED", ["PROVIDER_IDENTITY_UNVERIFIED"])
        if role == "A" and row["family"] == "glm":
            raise _Stop("BLOCKED", ["GLM_CANNOT_BE_A"])
        return profile_id, ProviderIdentity(row["adapter"], row["model_id"], row["family"], row["connection_id"]), dict(row)

    def _remote_started(self, contract, step_id, profile_id, role, payload):
        """Bind adapter-accepted remote IDs before asking for another stream event."""
        names = ("external_request_id", "external_execution_id")
        remote = {name: value if isinstance(value := payload.get(name), str)
            and value.strip() and len(value) <= 512 else None for name in names}
        valid = any(remote.values()) and all(payload.get(name) is None or remote[name] is not None for name in names)
        remote.update(step_id=step_id, provider_profile_id=profile_id, role=role,
            accepted=True, status="running" if valid else "unknown")
        with closing(self.database.connect()) as connection, transaction(connection):
            row = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
            if not self._owns_or_cancelled(row, contract):
                raise WorkflowBusy("WORKFLOW_BUSY")
            step = connection.execute("SELECT * FROM steps WHERE id=? AND task_id=? AND attempt_id=?",
                (step_id, contract.task_id, contract.attempt_id)).fetchone()
            if step is None:
                raise ValueError("PROVIDER_STARTED_STEP_MISSING")
            audit = json.loads(step["checkpoint_json"])
            previous = audit.get("remote_execution")
            if previous and any(previous.get(key) != remote[key] for key in names):
                raise ValueError("PROVIDER_STARTED_ID_CHANGED")
            audit["remote_execution"] = remote
            connection.execute("UPDATE steps SET external_execution_id=?,checkpoint_json=? WHERE id=?",
                (remote["external_execution_id"], json.dumps(audit, ensure_ascii=False), step_id))
            checkpoint = checkpoint_for(row)
            checkpoint["active_external_request"] = remote
            if row["external_request_id"] is None and remote["external_request_id"] is not None:
                connection.execute("UPDATE task_runs SET external_request_id=? WHERE task_id=? AND attempt_id=?",
                    (remote["external_request_id"], contract.task_id, contract.attempt_id))
            connection.execute("""UPDATE task_runs SET external_execution_id=?,remote_status=?,
                external_stop_confirmed=NULL,checkpoint_json=? WHERE task_id=? AND attempt_id=?""",
                (remote["external_execution_id"], remote["status"], json.dumps(checkpoint, ensure_ascii=False), contract.task_id, contract.attempt_id))
        return remote

    def _finish_request(self, contract, step_id, status, audit, remote=None, remote_status=None):
        with closing(self.database.connect()) as connection, transaction(connection):
            step = connection.execute("SELECT checkpoint_json FROM steps WHERE id=?", (step_id,)).fetchone()
            checkpoint = json.loads(step[0])
            checkpoint.update(audit)
            if remote is not None:
                checkpoint["remote_execution"] = {**remote, "status": remote_status}
            connection.execute("""UPDATE steps SET state=?,
                completed_at=CASE WHEN ? IN ('UNKNOWN_REMOTE','CANCEL_PENDING_REMOTE') THEN NULL
                ELSE strftime('%Y-%m-%dT%H:%M:%fZ','now') END,checkpoint_json=? WHERE id=?""",
                (status, status, json.dumps(checkpoint, ensure_ascii=False), step_id))
            if remote is not None:
                row = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
                task_checkpoint = checkpoint_for(row)
                if task_checkpoint.get("active_external_request", {}).get("step_id") != step_id:
                    raise ValueError("ACTIVE_REMOTE_STEP_CHANGED")
                task_checkpoint["active_external_request"] = {**remote, "status": remote_status}
                connection.execute("UPDATE task_runs SET remote_status=?,checkpoint_json=? WHERE task_id=? AND attempt_id=?",
                    (remote_status, json.dumps(task_checkpoint, ensure_ascii=False), contract.task_id, contract.attempt_id))

    def _dependencies(self, contract):
        if not contract.dependencies:
            return {}
        if len(set(contract.dependencies)) != len(contract.dependencies):
            raise _Stop("BLOCKED", ["DUPLICATE_CONTRACT_DEPENDENCY"])
        with closing(self.database.connect()) as connection:
            row = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
            checkpoint = checkpoint_for(row)
            if "dependency_graph" not in checkpoint:
                raise _Stop("BLOCKED", ["DEPENDENCY_GRAPH_MISSING"])
            graph = DependencyGraph(checkpoint["dependency_graph"])
            upstream = {}
            for revision_id in contract.dependencies:
                artifact = connection.execute("SELECT * FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?",
                    (revision_id, contract.task_id, contract.attempt_id)).fetchone()
                if artifact is None:
                    raise _Stop("BLOCKED", ["DEPENDENCY_MISSING_OR_FOREIGN"])
                if not is_current_revision(connection, contract.task_id, contract.attempt_id, revision_id):
                    raise _Stop("BLOCKED", ["DEPENDENCY_STALE"])
                logical_ids = [logical for logical, node in graph.nodes.items() if node["revision_id"] == revision_id]
                if len(logical_ids) != 1 or logical_ids[0] == "answer":
                    raise _Stop("BLOCKED", ["DEPENDENCY_LOGICAL_BINDING_INVALID"])
                self.store.read(artifact["byte_sha256"])
                upstream[logical_ids[0]] = revision_id
            return upstream

    async def _request(self, contract, workspace, lease, role, phase, package, workflow):
        row = self._guard(contract)
        self._dependencies(contract)
        route = json.loads(row["route_snapshot_json"])
        provider = self.adapter if role == "B" else self.reviewer
        if getattr(provider, "test_only", False) and not route.get("test_only"):
            raise _Stop("BLOCKED", ["FIXTURE_PROVIDER_FORBIDDEN"])
        if not getattr(provider, "test_only", False) and getattr(provider, "scope_enforced", False) is not True:
            raise _Stop("BLOCKED", ["EXTERNAL_SCOPE_ENFORCEMENT_MISSING"])
        if self.budget_port is None:
            raise _Stop("BLOCKED", ["BUDGET_PORT_MISSING"])
        function = "execution" if phase == "execution" else "takeover" if phase == "takeover" else "review"
        decision = self.budget_port(self.ledger.summary(contract.task_id), total_tokens=contract.budget.total_tokens,
            reserved_a_tokens=contract.budget.reserved_a_tokens, role=role,
            estimated_tokens=self.estimates.get(f"{role}.{function}"))
        if inspect.isawaitable(decision):
            decision = await decision
        workflow["last_budget"] = decision
        self._checkpoint(contract, workflow)
        if decision.get("allowed") is not True:
            raise _Stop("BLOCKED", [decision.get("reason", "BUDGET_DENIED")])
        profile_id, identity, live_profile = self._profile(role, route)
        if role == "A" and identity.family.value != contract.model_family:
            raise _Stop("BLOCKED", ["A_MODEL_FAMILY_MISMATCH"])
        if role == "A":
            binding = {"provider_id": profile_id, "model_id": identity.model_id,
                "model_family": identity.family.value, "adapter_id": identity.adapter,
                "identity_source": live_profile["identity_source"],
                "connection_version": live_profile["connection_version"]}
            if any(route.get(key) != value for key, value in binding.items()):
                raise _Stop("BLOCKED", ["A_MODEL_ROUTE_MISMATCH"])
        if identity.family.value == "claude":
            if self.translation_service is None:
                raise _Stop("BLOCKED", ["CLAUDE_REQUEST_CONTEXT_GATE_MISSING"])
            from app.translation.runtime_context import load_gateway
            gateway=load_gateway(self.translation_service,workspace,contract.task_id,contract.attempt_id)
            for source in contract.inputs: gateway.read('claude',source.ref)
            observed=getattr(provider,'provider',None)
            if not isinstance(observed,ProviderContract) or not self.translation_service.router.check_identity(contract.task_id,contract.attempt_id,observed):
                raise _Stop('PAUSED',['MODEL_IDENTITY_CHANGED'])
        self._guard(contract)
        step_id = uuid.uuid4().hex
        relative_prompt = f"{role.lower()}/prompts/{step_id}.json"
        from .role_prompts import load_role_prompt
        prompt_package = {**package, "role_prompt": load_role_prompt(phase, contract.model_family)}
        prompt = {"phase": phase, "contract": contract.model_dump(mode="json"), "evidence_package": prompt_package}
        prompt_path = workspace.write(role, relative_prompt, json.dumps(prompt, ensure_ascii=False).encode(), lease)
        request = AgentRequest(contract.task_id, contract.attempt_id, role, identity, str(prompt_path),
                               str(workspace.area(role.lower())), contract.contract_version)
        # A crash after reserving a request must retain uncertain usage rather
        # than making the attempt appear free. This does not assert billing.
        self.ledger.record(task_id=contract.task_id, attempt_id=contract.attempt_id,
            provider_profile_id=profile_id, external_request_id=step_id, event_id=f"usage:{step_id}:pending",
            provider=identity.family.value, raw={"usage_observed": False, "request_start_confirmed": False},
            source="unknown", mode="pending", sequence=1, role=role, function=function,
            domain=contract.domain, status="running")
        try:
            with closing(self.database.connect()) as connection, transaction(connection):
                current = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
                self._guard_row(current, contract)
                connection.execute("""INSERT INTO steps(id,task_id,attempt_id,step_key,role,state,contract_version,
                    provider_profile_id,external_request_id,request_json,started_at)
                    VALUES(?,?,?,?,?,'RUNNING',?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))""",
                    (step_id, contract.task_id, contract.attempt_id, step_id, role, contract.contract_version,
                     profile_id, step_id, json.dumps(asdict(request), ensure_ascii=False)))
        except Exception as exc:
            self.ledger.record(task_id=contract.task_id, attempt_id=contract.attempt_id,
                provider_profile_id=profile_id, external_request_id=step_id, event_id=f"usage:{step_id}:not-started",
                provider=identity.family.value, raw={"usage_observed": False, "request_start_confirmed": False},
                source="unknown", mode="request_total", sequence=2, role=role, function=function,
                domain=contract.domain, status="cancelled" if isinstance(exc, _Stop) else "failed")
            raise
        usage = []
        events = []
        failure = None
        cancelled = False
        remote = None
        stop = None
        prior_sequence = 0
        try:
            self._guard(contract)
            async for event in provider.run(request):
                if not isinstance(event, AgentEvent):
                    raise ValueError("PROVIDER_EVENT_CONTRACT_REQUIRED")
                if ((event.task_id, event.attempt_id) != (contract.task_id, contract.attempt_id)
                        or event.sequence <= prior_sequence):
                    raise ValueError("PROVIDER_EVENT_BINDING_OR_SEQUENCE")
                prior_sequence = event.sequence
                if len(events) >= 1000 or len(json.dumps(event.payload).encode()) > 1_048_576:
                    raise ValueError("PROVIDER_EVENT_RESOURCE_LIMIT")
                if event.kind == "provider.usage":
                    usage.append((event.sequence, event.payload))
                elif event.kind == "provider.started":
                    remote = self._remote_started(contract, step_id, profile_id, role, event.payload)
                    if any(previous.kind in _COMPLETION_KINDS for previous in events):
                        raise ValueError("PROVIDER_STARTED_AFTER_COMPLETION")
                elif event.kind == "provider.error":
                    raise ValueError("PROVIDER_ERROR_EVENT")
                elif event.kind=='provider.identity' and role=='A' and contract.model_family=='claude':
                    observed=ProviderContract(schema_version='1.0',provider_id=profile_id,
                        identity=dict(adapter=identity.adapter,model_id=event.payload.get('model_id'),
                            family=event.payload.get('family'),connection_id=identity.connection_id),
                        identity_status=event.payload.get('identity_status',event.payload.get('status','unknown')),
                        identity_source=event.payload.get('identity_source'),connection_version=event.payload.get('connection_version'))
                    if not self.translation_service.router.check_identity(contract.task_id,contract.attempt_id,observed):
                        raise _Stop('PAUSED',['MODEL_IDENTITY_CHANGED'])
                events.append(event)
                self._observe(contract, "workflow.provider_event", {"step_id": step_id,
                    "provider_sequence": event.sequence, "kind": event.kind, "payload": event.payload},
                    key=f"provider:{step_id}:{event.sequence}")
                if self._row(contract)["cancel_requested"]:
                    if not cancelled:
                        await asyncio.wait_for(provider.cancel(contract.task_id, contract.attempt_id), timeout=5)
                    cancelled = True
                else:
                    self._guard(contract)
        except _Stop as stopped:
            stop = stopped
            cancelled = stopped.state == "CANCELLED"
        except Exception as exc:
            failure = exc
        cancelled = cancelled or bool(self._row(contract)["cancel_requested"])
        remote_unknown = remote is not None and (cancelled or failure is not None or stop is not None
            or not any(event.kind in _COMPLETION_KINDS for event in events))
        status = "cancelled" if cancelled else "failed" if failure or stop or remote_unknown else "completed"
        if not usage:
            usage = [(1, {"raw": {}, "source": "unknown"})]
        for sequence, payload in usage:
            raw = payload.get("raw")
            cumulative_scope = payload.get("cumulative_scope")
            receipt_sequence = sequence
            if cumulative_scope is not None:
                receipt_sequence = payload.get("receipt_sequence")
                if (payload.get("mode") != "cumulative" or type(receipt_sequence) is not int
                        or receipt_sequence < 1):
                    raise ValueError("USAGE_CUMULATIVE_BINDING_MISSING")
            self.ledger.record(task_id=contract.task_id, attempt_id=contract.attempt_id,
                provider_profile_id=profile_id, external_request_id=step_id,
                event_id=f"usage:{step_id}:{sequence}", provider=identity.family.value,
                raw=raw if isinstance(raw, dict) else {}, source=payload.get("source", "unknown"),
                mode=payload.get("mode", "request_total"), sequence=receipt_sequence + 1, role=role, function=function,
                domain=contract.domain, status=status, cumulative_scope=cumulative_scope)
        step_state = "CANCEL_PENDING_REMOTE" if cancelled and remote_unknown else "UNKNOWN_REMOTE" if remote_unknown else status.upper()
        self._finish_request(contract, step_id, step_state,
            {"provider_events": len(events), "cancel_requested": cancelled,
             "failure": type(failure).__name__ if failure else None}, remote,
            "unknown" if remote_unknown else "completed" if remote is not None else None)
        if cancelled:
            raise _Stop("CANCELLED", ["CANCELLED_FENCE"])
        self._guard(contract)
        if stop is not None:
            raise stop
        if remote_unknown:
            raise _Stop("BLOCKED", ["UNKNOWN_REMOTE"])
        if failure:
            if isinstance(failure, OSError):
                raise _ConnectionFailure(str(failure)) from failure
            raise _Stop("BLOCKED", ["PROVIDER_RESPONSE_FAILED"])
        self._guard(contract)
        return events, step_id

    def _candidate(self, contract, workspace, lease, role, events, step_id, workflow):
        candidates = [event.payload for event in events if event.kind == "artifact.candidate"]
        if len(candidates) != 1 or not isinstance(candidates[0].get("text"), str) or not candidates[0]["text"].strip():
            raise _Stop("BLOCKED", ["CANDIDATE_MISSING"])
        language = candidates[0].get("language", "und")
        if not isinstance(language, str) or language not in {"und", "en", "zh-CN", "mul"}:
            raise _Stop("BLOCKED", ["CANDIDATE_LANGUAGE_INVALID"])
        content = candidates[0]["text"].encode("utf-8")
        self._guard(contract)
        upstream = self._dependencies(contract)
        path = contract.deliverables[0].write_scope
        workspace.write(role, path, content, lease)
        revision = "candidate-" + uuid.uuid4().hex
        digest = hashlib.sha256(content).hexdigest()
        artifact = ArtifactVersion(id=revision, task_id=contract.task_id, artifact_kind=contract.deliverables[0].kind,
            language=language, immutable_uri=self.store.uri_for(digest), byte_sha256=digest,
            canonical_content_sha256=digest, source_version_id=None, origin_authors=[role],
            canonical_issued_by=role, reviewed_by=[], rendered_by="service",
            a_response_ref=step_id if role == "A" else None,
            dependencies=[ArtifactDependency(artifact_version_id=value, relationship="source") for value in upstream.values()])
        with closing(self.database.connect()) as connection:
            store_artifact(connection, self.store, content, artifact, attempt_id=contract.attempt_id,
                provenance={"step_id": step_id, "test_only": bool(getattr(self.adapter if role == "B" else self.reviewer, "test_only", False)),
                    "authenticated_authorship": False}, source_request={"step_id": step_id, "role": role})
            activate_revision(connection, self.store, contract.task_id, contract.attempt_id, "answer", revision, upstream)
        if role == 'A' and (contract.model_family=='claude' or any(item.require_a_canonical for item in contract.deliverables)
                or checkpoint_for(self._row(contract)).get('requested_formats')):
            from app.documents.canonical import CanonicalCapture
            CanonicalCapture(self.database_path).capture(contract.task_id,contract.attempt_id,step_id,
                language=language,logical_id='answer',dependencies=upstream,revision_id=revision)
        workflow["candidate_history"].append({"revision_id": revision, "byte_sha256": digest,
            "role": role, "step_id": step_id, "previous_revision_id": workflow.get("current_revision_id")})
        workflow["current_revision_id"] = revision
        self._checkpoint(contract, workflow, current_revision_id=revision, stale=False, publication_blocked=False)
        return CandidateContext(contract, workspace, revision, self.store.path_for(digest), digest, content)

    def _proof(self, contract, workspace, candidate, criterion, passed, details, verifier):
        if type(passed) is not bool:
            raise _Stop("BLOCKED", ["VERIFIER_BOOLEAN_REQUIRED"])
        # Bind revision/criterion inside immutable JSON, not a long or user-
        # controlled filename (Windows MAX_PATH and path-component injection).
        name = uuid.uuid4().hex + ".json"
        body = {"criterion_id": criterion.id, "revision_id": candidate.revision_id,
            "byte_sha256": candidate.byte_sha256, "passed": passed, "verifier": verifier, "details": details}
        path = workspace.write("service", "evidence/" + name, json.dumps(body, ensure_ascii=False, allow_nan=False).encode())
        evidence = {"criterion_id": criterion.id, "revision_id": candidate.revision_id, "ref": name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "verifier": verifier, "passed": passed}
        with closing(self.database.connect()) as connection, transaction(connection):
            connection.execute("""INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,
                result,check_version,evidence_ref,details_json) VALUES(?,?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, contract.task_id, contract.attempt_id, candidate.revision_id,
                 verifier + ".criterion", "pass" if passed else "fail", contract.contract_version,
                 str(path), json.dumps(body, ensure_ascii=False, allow_nan=False)))
        return evidence

    async def _validate(self, contract, workspace, candidate):
        if self.validator is None:
            raise _Stop("BLOCKED", ["VALIDATION_PORT_MISSING"])
        observed = self.validator(candidate)
        if inspect.isawaitable(observed):
            observed = await observed
        if not isinstance(observed, list):
            raise _Stop("BLOCKED", ["VALIDATION_OBSERVATIONS_REQUIRED"])
        evidence = []
        for criterion in contract.acceptance:
            if criterion.semantic or criterion.verifier not in {"C"}:
                continue
            matching = [item for item in observed if isinstance(item, dict) and item.get("criterion_id") == criterion.id]
            if len(matching) == 1:
                evidence.append(self._proof(contract, workspace, candidate, criterion,
                    matching[0].get("passed"), matching[0].get("evidence", {}), "C"))
        return evidence

    async def _review(self, contract, workspace, a_lease, candidate, evidence, workflow):
        from app.providers.phase_bridge import read_mechanical_observations
        original_observations = read_mechanical_observations(contract, candidate.revision_id,
            candidate.byte_sha256, evidence, workspace.area('evidence'))
        observations = original_observations
        if contract.model_family == 'claude':
            from app.translation.context_gateway import SourceMaterial, english_view
            from .context_gateway import ContextGateway
            observations = []
            for observation in original_observations:
                source_ref = 'evidence/' + observation['ref']
                translated = await self.translation_service.translate(task_id=contract.task_id,
                    attempt_id=contract.attempt_id, source=observation['content'], source_language='mul',
                    target_language='en', purpose='review-evidence', format='text',
                    source_version_id=candidate.revision_id, source_locator=source_ref)
                if translated.status != 'READY' or translated.source_sha256 != observation['sha256']:
                    raise _Stop('NEEDS_INPUT' if translated.status == 'NEEDS_INPUT' else 'BLOCKED',
                        ['CLAUDE_REVIEW_EVIDENCE_TRANSLATION_NOT_READY'])
                proof, _ = english_view(workspace, SourceMaterial(source_ref, language='mul', format='text'), translated)
                view = ContextGateway(workspace, {source_ref: proof}).read('claude', source_ref)
                observations.append(dict(ref=observation['ref'], sha256=observation['sha256'],
                    content=view.content.decode(), content_sha256=view.sha256, content_ref=view.content_ref,
                    translation_job_id=translated.job_id, qa_id=translated.qa_id, language='en'))
        # Translation may yield control. Recheck the same actual bytes before A
        # receives their view; publication independently rechecks these hashes.
        if read_mechanical_observations(contract, candidate.revision_id, candidate.byte_sha256,
                evidence, workspace.area('evidence')) != original_observations:
            raise _Stop('BLOCKED', ['REVIEW_EVIDENCE_INVALID'])
        package = {"revision_id": candidate.revision_id, "artifact_path": str(candidate.artifact_path),
            'clarification_instruction':'For NEED_EVIDENCE, put the complete necessary user question in clarification_text. Keep internal diagnostics in issues. Claude questions must be complete English; GPT preserves the user language.',
            "byte_sha256": candidate.byte_sha256, "candidate_content": candidate.content.decode("utf-8"),
            "sources": workflow.get("source_context", []), "mechanical_evidence": evidence,
            "mechanical_observations": observations,
            "acceptance": [criterion.model_dump() for criterion in contract.acceptance],
            "source_refs": [item.ref for item in contract.inputs], "previous_defects": workflow["repair"]["history"][-1: ],
            "versions": workflow["candidate_history"][-2:]}
        events, step = await self._request(contract, workspace, a_lease, "A", "review", package, workflow)
        reviews = [event.payload for event in events if event.kind == "review.decision"]
        if len(reviews) != 1:
            raise _Stop("BLOCKED", ["A_REVIEW_RESPONSE_REQUIRED"])
        response = reviews[0]
        expected_binding = {"task_id": contract.task_id, "attempt_id": contract.attempt_id,
            "contract_version": contract.contract_version, "contract_sha256": contract_digest(contract),
            "revision_id": candidate.revision_id}
        if any(key in response and response[key] != expected for key, expected in expected_binding.items()):
            raise _Stop("BLOCKED", ["A_REVIEW_BINDING_MISMATCH"])
        semantic = response.get("criterion_results", {})
        for criterion in contract.acceptance:
            if criterion.verifier == "A" and criterion.id in semantic:
                evidence.append(self._proof(contract, workspace, candidate, criterion,
                    semantic[criterion.id], {"a_step_id": step, "test_only": bool(getattr(self.reviewer, "test_only", False))}, "A"))
        canonical_author = response.get("canonical_author")
        if any(item.require_a_canonical for item in contract.deliverables) and workflow["candidate_history"][-1]["role"] != "A":
            canonical_author = None
        decision = ReviewDecision(task_id=contract.task_id, attempt_id=contract.attempt_id,
            contract_version=contract.contract_version, contract_sha256=contract_digest(contract),
            reviewer="A", decision=response.get("decision"), revision_id=candidate.revision_id,
            evidence=evidence, read_unit_ids=response.get("read_unit_ids", []),
            source_refs=response.get("source_refs", [item.ref for item in contract.inputs]),
            sampling_note=response.get("sampling_note"), canonical_author=canonical_author,
            a_response_ref=step if canonical_author == "A" else None,
            issues=response.get("issues", []), review_scope=response.get("review_scope", []),
            findings=response.get("findings", []))
        self._guard(contract)
        gate = evaluate_review(contract, decision, workspace.area("evidence"))
        check_id = "A-review-" + uuid.uuid4().hex
        details = {"contract": contract.model_dump(mode="json"), "decision": decision.model_dump(mode="json"),
            "gate": gate.model_dump(), "evidence_root": str(workspace.area("evidence")), "a_step_id": step}
        with closing(self.database.connect()) as connection, transaction(connection):
            row = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
            if row["cancel_requested"]:
                raise _Stop("CANCELLED", ["CANCELLED_FENCE"])
            connection.execute("""INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,
                result,check_version,verifier_model,details_json) VALUES(?,?,?,?,'A.review',?,?,?,?)""",
                (check_id, contract.task_id, contract.attempt_id, candidate.revision_id,
                 "pass" if gate.eligible_for_output else "blocked" if decision.decision == "BLOCKED" else "fail",
                 contract.contract_version, "fixture" if getattr(self.reviewer, "test_only", False) else "verified-profile",
                 json.dumps(details, ensure_ascii=False, allow_nan=False)))
        workflow["review_check_id"] = check_id
        workflow['review_evidence_views'] = dict(review_check_id=check_id, revision_id=candidate.revision_id,
            mechanical_observations=observations)
        workflow["reviews"].append(details)
        self._checkpoint(contract, workflow)
        return decision, gate

    async def run(self, contract):
        contract = validate_contract(contract)
        key = contract.task_id, contract.attempt_id
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            owner, existing = self._claim(contract)
            if owner is None:
                return self._existing_result(contract, existing)
            self._owners[key] = owner
            try:
                return await self._run(contract)
            finally:
                self._release_owner(contract, owner)
                self._owners.pop(key, None)

    async def run_prepared(self, plan):
        from .planning import validate_prepared_plan
        checked = validate_prepared_plan(self.database_path, self.workspaces, plan)
        contract = checked.contract
        key = contract.task_id, contract.attempt_id
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            owner = 'workflow:' + uuid.uuid4().hex
            with closing(self.database.connect()) as connection, transaction(connection):
                # Recheck under the write transaction: a validation before lock
                # acquisition cannot authorize a cancelled or reassigned task.
                validate_prepared_plan(self.database_path, self.workspaces, plan, connection=connection)
                row = require_current_attempt(connection, *key, contract.contract_version)
                checkpoint = checkpoint_for(row)
                if checkpoint.get('workflow'):
                    raise WorkflowConflict('WORKFLOW_ALREADY_STARTED')
                checkpoint['workflow'] = self._initial_workflow(contract)
                checkpoint['planning_handoff'] = dict(planning_step_id=plan.planning_step_id,
                    previous_owner=plan.owner_token, workflow_owner=owner,
                    contract_sha256=contract_digest(contract))
                connection.execute('UPDATE task_runs SET lease_owner=?,lease_expires_at=?,checkpoint_json=? WHERE task_id=? AND attempt_id=?',
                    (owner, (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
                     json.dumps(checkpoint, ensure_ascii=False, allow_nan=False), *key))
            self._owners[key] = owner
            try:
                return await self._run(contract, prepared=True)
            finally:
                self._release_owner(contract, owner)
                self._owners.pop(key, None)

    async def _run(self, contract, *, prepared=False):
        workspace = self.workspaces.create(contract.task_id, contract.attempt_id)
        row = self._row(contract)
        previous = checkpoint_for(row).get("workflow")
        if not prepared and row["state"] != "RECEIVED" and isinstance(previous, dict):
            repairs = previous.get("repair", {})
            return WorkflowResult(row["state"], previous.get("current_revision_id"), previous.get("review_check_id"),
                repairs.get("quality_repairs", 0), repairs.get("connection_retries", 0), repairs.get("translation_retries", 0),
                tuple(previous.get("reason_codes", [])), str(workspace.area("evidence")))
        workflow = self._initial_workflow(contract)
        tracker = RepairTracker(workflow["repair"])
        b_lease = a_lease = None
        takeover_used = False
        candidate = None
        try:
            self._guard(contract)
            if row["state"] != ('PLANNING' if prepared else 'RECEIVED'):
                raise _Stop(row["state"], ["WORKFLOW_ALREADY_STARTED"])
            if not prepared:
                self._transition(contract, "INPUT_PREPARING")
            route = json.loads(row["route_snapshot_json"])
            if route.get("id") != contract.route_snapshot_id:
                raise _Stop("BLOCKED", ["CONTRACT_ROUTE_BINDING_MISMATCH"])
            if contract.model_family == "claude":
                if self.translation_service is None:
                    raise _Stop("BLOCKED", ["CLAUDE_LANGUAGE_AND_PUBLICATION_GATES_MISSING"])
                from app.translation.runtime_context import prepare_sources,load_gateway
                if not prepared:
                    context=await prepare_sources(self.translation_service,workspace,contract.task_id,contract.attempt_id,
                        [dict(ref=item.ref,sha256=item.sha256) for item in contract.inputs])
                    if context.status!='READY':
                        raise _Stop('NEEDS_INPUT' if context.status=='NEEDS_INPUT' else 'BLOCKED',['CLAUDE_INPUT_TRANSLATION_NOT_READY'])
                gateway=load_gateway(self.translation_service,workspace,contract.task_id,contract.attempt_id)
                provider=getattr(self.reviewer,'provider',None)
                if not isinstance(provider,ProviderContract) or not self.translation_service.router.check_identity(contract.task_id,contract.attempt_id,provider):
                    raise _Stop('PAUSED',['MODEL_IDENTITY_CHANGED'])
            if len(contract.deliverables) != 1:
                raise _Stop("BLOCKED", ["MULTIPLE_DELIVERABLE_GATE_MISSING"])
            workflow["upstream_versions"] = self._dependencies(contract)
            sources = []
            for source in contract.inputs:
                original=workspace.read('A',source.ref)
                if hashlib.sha256(original).hexdigest() != source.sha256:
                    raise _Stop("BLOCKED", ["CONTRACT_SOURCE_HASH_MISMATCH"])
                content=gateway.read('claude',source.ref).content if contract.model_family=='claude' else original
                try:
                    source_text = content.decode("utf-8")
                except UnicodeDecodeError:
                    raise _Stop("BLOCKED", ["SOURCE_CONTEXT_PREPARATION_MISSING"])
                sources.append({"ref": source.ref, "sha256": source.sha256, "content": source_text,
                                "content_ref":gateway.english_views[source.ref].view_ref if contract.model_family=='claude' else source.ref,
                                "content_sha256":hashlib.sha256(content).hexdigest(),
                                "trust": "untrusted_material"})
            workflow["source_context"] = sources
            if not prepared:
                self._transition(contract, "PLANNING", {"contract_sha256": contract_digest(contract)})
            b_lease = workspace.acquire_write_lease("B", "b")
            a_lease = workspace.acquire_write_lease("A", "a")
            self._checkpoint(contract, workflow, task_contract=contract.model_dump(mode="json"))
            self._transition(contract, "EXECUTING")
            while True:
                if candidate is None:
                    try:
                        if getattr(self, '_production_a_led', False):
                            workflow['optimization_gate'] = dict(route_mode='a_led',optimization_goal_met=False,
                                reason_codes=['JOINT_QUALITY_TOKEN_QUALIFICATION_MISSING'])
                            before = workspace.lease_snapshot()
                            b_lease = workspace.handoff(b_lease, 'A')
                            during = workspace.lease_snapshot()
                            try:
                                events, step = await self._request(contract, workspace, a_lease, 'A', 'takeover',
                                    dict(sources=sources,repair=tracker.snapshot(),
                                         instruction='Independently complete the task from all sources. Issue your complete '+
                                         ('English' if contract.model_family=='claude' else 'original-language')+
                                         ' final body, including the required reasoning and evidence.'),workflow)
                                candidate = self._candidate(contract,workspace,b_lease,'A',events,step,workflow)
                                takeover_used = True
                            finally:
                                b_lease = workspace.handoff(b_lease,'B')
                                workflow['takeover_leases'].append(dict(before=before,during=during,
                                    after=workspace.lease_snapshot(),snapshot_path=None))
                                self._checkpoint(contract,workflow)
                        else:
                            if workflow.get('repair_work_order'):
                                from .review_handoff import require_repair_work_order
                                require_repair_work_order(contract, workflow['repair_work_order'], self.store,
                                    workspace.area('evidence'), workflow['current_revision_id'], workflow['review_check_id'])
                            events, step = await self._request(contract, workspace, b_lease, "B", "execution",
                                {"sources": sources,
                                 **({"repair_work_order": workflow["repair_work_order"]} if workflow.get("repair_work_order") else {}),
                                 "repair": tracker.snapshot()}, workflow)
                    except _ConnectionFailure:
                        allowed = tracker.connection_failure()
                        workflow["repair"] = tracker.snapshot()
                        self._checkpoint(contract, workflow)
                        if not allowed:
                            raise _Stop("BLOCKED", ["CONNECTION_RETRY_LIMIT"])
                        continue
                    if candidate is None:
                        candidate = self._candidate(contract, workspace, b_lease, "B", events, step, workflow)
                self._transition(contract, "VALIDATING")
                evidence = await self._validate(contract, workspace, candidate)
                self._guard(contract)
                needs_final=contract.model_family=='claude' or bool(checkpoint_for(self._row(contract)).get('requested_formats'))
                if needs_final and workflow['candidate_history'][-1]['role']=='B':
                    # C's B evidence is supplied to A, but only a full A-owned
                    # English body can become the canonical public source.
                    before=workspace.lease_snapshot(); b_lease=workspace.handoff(b_lease,'A')
                    during=workspace.lease_snapshot()
                    try:
                        events,step=await self._request(contract,workspace,a_lease,'A','takeover',
                            dict(revision_id=candidate.revision_id,candidate_content=candidate.content.decode(),
                                sources=sources,mechanical_evidence=evidence,
                                instruction='Read all sources and B evidence. Issue your complete '+('English' if contract.model_family=='claude' else 'original-language')+' final body; do not merely approve or summarize B.'),workflow)
                        candidate=self._candidate(contract,workspace,b_lease,'A',events,step,workflow)
                        if self.store.read(candidate.byte_sha256)!=candidate.content or workflow['candidate_history'][-1]['role']!='A':
                            raise _Stop('BLOCKED',['CLAUDE_A_CANONICAL_MISSING'])
                    finally:
                        b_lease=workspace.handoff(b_lease,'B')
                        workflow['takeover_leases'].append(dict(before=before,during=during,after=workspace.lease_snapshot(),snapshot_path=None))
                        self._checkpoint(contract,workflow)
                    evidence=await self._validate(contract,workspace,candidate)
                self._transition(contract, "REVIEWING")
                decision, gate = await self._review(contract, workspace, a_lease, candidate, evidence, workflow)
                if gate.eligible_for_output:
                    self._transition(contract, "OUTPUT_PREPARING", {"review_check_id": workflow["review_check_id"]})
                    break
                if decision.decision == "BLOCKED":
                    raise _Stop("BLOCKED", ["A_BLOCKED"])
                if decision.decision == "NEED_EVIDENCE":
                    from app.translation.clarification import ClarificationPublisher
                    with closing(self.database.connect()) as connection:
                        recorded=connection.execute("SELECT internal_payload_json FROM outbox_events WHERE task_id=? AND attempt_id=? AND kind='workflow.provider_event' ORDER BY sequence",(contract.task_id,contract.attempt_id)).fetchall()
                        a_messages=[json.loads(item[0]) for item in recorded]
                        a_messages=[item['payload'] for item in a_messages if item.get('step_id')==workflow['reviews'][-1]['a_step_id'] and item['kind']=='review.decision']
                    if len(a_messages)==1 and a_messages[0].get('clarification_text') is not None:
                        try:
                            await ClarificationPublisher(self.database_path,self.translation_service).publish(contract.task_id,contract.attempt_id,
                                workflow['reviews'][-1]['a_step_id'],origin='workflow_review')
                        except ValueError:
                            self._guard(contract)
                            raise _Stop('BLOCKED',['A_CLARIFICATION_TRANSLATION_OR_PROVENANCE_FAILED'])
                    raise _Stop("NEEDS_INPUT", ["A_NEEDS_EVIDENCE"])
                if decision.decision == "PASS":
                    raise _Stop("BLOCKED", gate.reason_codes or ["CURRENT_REVIEW_EVIDENCE_REQUIRED"])
                from .review_handoff import repair_work_order
                workflow['repair_work_order'] = repair_work_order(contract, decision, candidate,
                    workspace.area('evidence'), workflow['review_check_id'])
                defects = list(dict.fromkeys([item.id for item in decision.findings] + list(decision.issues))) or ["unresolved-review-defect"]
                tracker.observe(defects, candidate.revision_id, candidate.byte_sha256)
                action = tracker.next_action()
                workflow["repair"] = tracker.snapshot()
                self._checkpoint(contract, workflow)
                self._transition(contract, "REPAIRING", {"action": action, "defects": defects})
                if action == "repair":
                    candidate = None
                    self._transition(contract, "EXECUTING")
                    continue
                if takeover_used:
                    raise _Stop("BLOCKED", ["A_TAKEOVER_NO_PROGRESS"])
                from .review_handoff import require_repair_work_order
                require_repair_work_order(contract, workflow['repair_work_order'], self.store,
                    workspace.area('evidence'), workflow['current_revision_id'], workflow['review_check_id'])
                from .review_handoff import takeover_prompt_order
                takeover_order = takeover_prompt_order(contract, workflow['repair_work_order'],
                    workflow.get('review_evidence_views'), workspace)
                takeover_used = True
                before = workspace.lease_snapshot()
                b_lease = workspace.handoff(b_lease, "A")
                during = workspace.lease_snapshot()
                snapshot_path = workspace.write("A", f"b/snapshots/{candidate.revision_id}.txt", candidate.content, b_lease)
                try:
                    events, step = await self._request(contract, workspace, a_lease, "A", "takeover",
                        {"revision_id": candidate.revision_id, "snapshot_path": str(snapshot_path),
                         "sources": sources,
                         "repair_work_order": takeover_order,
                         "defects": defects, "repair": tracker.snapshot()}, workflow)
                    candidate = self._candidate(contract, workspace, b_lease, "A", events, step, workflow)
                finally:
                    b_lease = workspace.handoff(b_lease, "B")
                    workflow["takeover_leases"].append({"before": before, "during": during,
                        "after": workspace.lease_snapshot(), "snapshot_path": str(snapshot_path)})
                    self._checkpoint(contract, workflow)
                self._transition(contract, "EXECUTING")
        except _Stop as stop:
            workflow["reason_codes"] = list(stop.reasons)
            self._stop(contract, workflow, stop.state)
        except (PermissionError, ValueError, OSError, _ConnectionFailure) as exc:
            workflow["reason_codes"] = ["PROVIDER_UNAVAILABLE" if isinstance(exc, _ConnectionFailure) else "WORKFLOW_BOUNDARY_FAILED"]
            workflow["failure_type"] = type(exc).__name__
            self._stop(contract, workflow, "BLOCKED")
        finally:
            for lease in (b_lease, a_lease):
                if lease is not None:
                    workspace.release(lease)
        current = self._row(contract)
        return WorkflowResult(current["state"], workflow["current_revision_id"], workflow["review_check_id"],
            tracker.state["quality_repairs"], tracker.state["connection_retries"], tracker.state["translation_retries"],
            tuple(workflow["reason_codes"]), str(workspace.area("evidence")))
