"""Version-bound task contracts and evidence checks. This gate does not publish."""
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal, Self

from pydantic import Field, StrictBool, model_validator

from .providers import ContractModel, NonEmptyString, NonNegativeInt, Sha256

CORE_RESPONSIBILITIES = {"problem_modeling", "core_reasoning", "method_choice", "evidence_judgment", "final_review"}


def safe_relative_scope(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or PureWindowsPath(value).drive or any(p in ("", ".", "..") for p in normalized.split("/")) or ":" in normalized:
        raise ValueError("UNSAFE_RELATIVE_SCOPE")
    return path


class SourceInput(ContractModel):
    id: NonEmptyString
    ref: NonEmptyString
    sha256: Sha256


class Constraint(ContractModel):
    id: NonEmptyString
    text: NonEmptyString
    mandatory: StrictBool


class Deliverable(ContractModel):
    id: NonEmptyString
    kind: Literal["code", "document", "data", "figure"]
    write_scope: NonEmptyString
    require_a_canonical: StrictBool


class AcceptanceCriterion(ContractModel):
    id: NonEmptyString
    mandatory: StrictBool
    verifier: Literal["A", "B", "C", "human"]
    evidence_type: Literal["execution", "artifact", "review", "source", "render", "dependency"]
    condition: NonEmptyString
    semantic: StrictBool

    @model_validator(mode="after")
    def verifier_boundary(self) -> Self:
        if self.semantic and self.verifier not in ("A", "human"):
            raise ValueError("SEMANTIC_REVIEW_REQUIRES_A")
        if self.mandatory and self.verifier == "B":
            raise ValueError("EXECUTOR_SELF_SCORE_NOT_ACCEPTANCE")
        return self


class TaskBudget(ContractModel):
    total_tokens: NonNegativeInt = Field(ge=1)
    reserved_a_tokens: NonNegativeInt

    @model_validator(mode="after")
    def reserve(self) -> Self:
        if self.reserved_a_tokens > self.total_tokens:
            raise ValueError("A_RESERVE_EXCEEDS_BUDGET")
        return self


class TaskContract(ContractModel):
    task_id: NonEmptyString
    attempt_id: NonEmptyString
    contract_version: NonEmptyString
    domain: Literal["code", "paper", "document", "mixed"]
    model_family: Literal["claude", "gpt"]
    route_snapshot_id: NonEmptyString
    objective: NonEmptyString
    method: NonEmptyString
    inputs: list[SourceInput] = Field(min_length=1)
    constraints: list[Constraint] = Field(min_length=1)
    deliverables: list[Deliverable] = Field(min_length=1)
    acceptance: list[AcceptanceCriterion] = Field(min_length=1)
    dependencies: list[NonEmptyString]
    budget: TaskBudget
    b_write_scopes: list[NonEmptyString] = Field(min_length=1)
    a_responsibilities: list[NonEmptyString]
    guidance_depth: Literal["ordinary", "checkpoint", "a_takeover"]
    full_read_required: StrictBool
    source_unit_ids: list[NonEmptyString] = Field(min_length=1)

    @model_validator(mode="after")
    def invariants(self) -> Self:
        for group in (self.inputs, self.constraints, self.deliverables, self.acceptance):
            ids = [item.id for item in group]
            if len(ids) != len(set(ids)):
                raise ValueError("DUPLICATE_CONTRACT_ID")
        if not CORE_RESPONSIBILITIES.issubset(self.a_responsibilities):
            raise ValueError("A_CORE_RESPONSIBILITIES_REQUIRED")
        if len(self.source_unit_ids) != len(set(self.source_unit_ids)):
            raise ValueError("DUPLICATE_SOURCE_UNIT")
        scopes = [safe_relative_scope(value) for value in self.b_write_scopes]
        for item in self.deliverables:
            target = safe_relative_scope(item.write_scope)
            if not any(target == scope or scope in target.parents for scope in scopes):
                raise ValueError("DELIVERABLE_OUTSIDE_B_SCOPE")
            if self.model_family == "claude" and item.kind == "document" and not item.require_a_canonical:
                raise ValueError("CLAUDE_DOCUMENT_REQUIRES_A_CANONICAL")
        return self


class ReviewEvidence(ContractModel):
    criterion_id: NonEmptyString
    revision_id: NonEmptyString
    ref: NonEmptyString
    sha256: Sha256
    verifier: NonEmptyString
    passed: StrictBool


class ReviewFinding(ContractModel):
    id: NonEmptyString
    requirement_id: NonEmptyString
    location: NonEmptyString
    impact: NonEmptyString
    required_change: NonEmptyString
    pass_condition: NonEmptyString


class ReviewDecision(ContractModel):
    task_id: NonEmptyString
    attempt_id: NonEmptyString
    contract_version: NonEmptyString
    contract_sha256: NonEmptyString
    reviewer: Literal["A"]
    decision: Literal["PASS", "REPAIR", "NEED_EVIDENCE", "BLOCKED"]
    revision_id: NonEmptyString
    evidence: list[ReviewEvidence]
    read_unit_ids: list[NonEmptyString]
    source_refs: list[NonEmptyString]
    sampling_note: str | None
    canonical_author: str | None
    a_response_ref: str | None
    issues: list[NonEmptyString]
    review_scope: list[NonEmptyString] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_findings(self) -> Self:
        identities = [item.id for item in self.findings]
        if len(identities) != len(set(identities)):
            raise ValueError("DUPLICATE_REVIEW_DEFECT_ID")
        return self


class ReviewGate(ContractModel):
    decision: Literal["PASS", "REPAIR", "NEED_EVIDENCE", "BLOCKED"]
    eligible_for_output: StrictBool
    missing_criteria: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


def validate_contract(value: TaskContract | dict) -> TaskContract:
    return TaskContract.model_validate(value.model_dump() if isinstance(value, TaskContract) else value)


def contract_digest(value: TaskContract | dict) -> str:
    payload = json.dumps(validate_contract(value).model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _check_evidence(item: ReviewEvidence, criterion: AcceptanceCriterion, revision: str, root: Path) -> bool:
    if item.revision_id != revision or item.verifier != criterion.verifier or not item.passed:
        return False
    try:
        file = (root / str(safe_relative_scope(item.ref))).resolve()
        file.relative_to(root.resolve())
        if not file.is_file() or file.stat().st_size > 1_048_576:
            return False
        data = file.read_bytes()
        if hashlib.sha256(data).hexdigest() != item.sha256:
            return False
        proof = json.loads(data)
        return isinstance(proof, dict) and proof.get("criterion_id") == criterion.id and proof.get("revision_id") == revision and proof.get("passed") is True
    except (OSError, ValueError):
        return False


def evaluate_review(contract: TaskContract | dict, decision: ReviewDecision | dict, evidence_root: Path) -> ReviewGate:
    contract = validate_contract(contract)
    decision = ReviewDecision.model_validate(decision.model_dump() if isinstance(decision, ReviewDecision) else decision)
    actual = (decision.task_id, decision.attempt_id, decision.contract_version, decision.contract_sha256)
    expected = (contract.task_id, contract.attempt_id, contract.contract_version, contract_digest(contract))
    if actual != expected:
        raise ValueError("REVIEW_BINDING_MISMATCH")
    if any(item.requirement_id not in {criterion.id for criterion in contract.acceptance} for item in decision.findings):
        raise ValueError("REVIEW_FINDING_REQUIREMENT_MISMATCH")
    if decision.decision != "PASS":
        return ReviewGate(decision=decision.decision, eligible_for_output=False)
    missing = []
    for criterion in contract.acceptance:
        evidence = [item for item in decision.evidence if item.criterion_id == criterion.id]
        if criterion.mandatory and (len(evidence) != 1 or not _check_evidence(evidence[0], criterion, decision.revision_id, Path(evidence_root))):
            missing.append(criterion.id)
    reasons = ["MANDATORY_EVIDENCE_MISSING"] if missing else []
    if contract.full_read_required and (set(decision.read_unit_ids) != set(contract.source_unit_ids) or not decision.source_refs or decision.sampling_note is not None):
        reasons.append("FULL_READ_INCOMPLETE")
    if any(item.require_a_canonical for item in contract.deliverables) and (decision.canonical_author != "A" or not decision.a_response_ref):
        reasons.append("A_CANONICAL_REQUIRED")
    if decision.issues or decision.findings:
        reasons.append("OPEN_REVIEW_ISSUES")
    return ReviewGate(decision="NEED_EVIDENCE" if reasons else "PASS", eligible_for_output=not reasons, missing_criteria=missing, reason_codes=reasons)
