"""Translation bookkeeping only; no translation or quality approval service."""
from typing import Literal, Self

from pydantic import ConfigDict, model_validator

from .providers import ContractModel, NonEmptyString, Sha256, TranslationAttemptCount

TranslationStatus = Literal["PENDING", "RUNNING", "QA", "READY", "REPAIRING", "NEEDS_INPUT", "FAILED", "CANCELLED", "STALE"]
CheckResult = Literal["pass", "fail", "not_verified", "blocked"]
Severity = Literal["none", "minor", "major", "critical"]


class TranslationJob(ContractModel):
    id: NonEmptyString
    task_id: NonEmptyString
    turn_id: NonEmptyString
    source_ref: NonEmptyString
    source_sha256: Sha256
    source_language: NonEmptyString
    target_language: NonEmptyString
    glossary_version: NonEmptyString
    policy_version: NonEmptyString
    purpose: NonEmptyString
    status: TranslationStatus
    attempt_count: TranslationAttemptCount
    budget_id: NonEmptyString


class TranslationBlock(ContractModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True,
        json_schema_extra={"allOf": [{
            "if": {"properties": {"translation_status": {"const": "READY"}}},
            "then": {"properties": {
                "target_ref": {"type": "string", "minLength": 1, "pattern": r"\S"},
                "target_sha256": {"type": "string", "minLength": 64, "maxLength": 64, "pattern": r"^[a-f0-9]{64}$"},
            }},
        }]},
    )

    job_id: NonEmptyString
    block_id: NonEmptyString
    source_locator: NonEmptyString
    source_sha256: Sha256
    target_ref: NonEmptyString | None
    target_sha256: Sha256 | None
    protected_span_ids: list[NonEmptyString]
    translation_status: TranslationStatus
    uncertainty_codes: list[NonEmptyString]

    @model_validator(mode="after")
    def ready_has_target_references(self) -> Self:
        if self.translation_status == "READY" and (self.target_ref is None or self.target_sha256 is None):
            raise ValueError("READY_TRANSLATION_MISSING_TARGET")
        return self


class SemanticFinding(ContractModel):
    block_id: NonEmptyString
    code: NonEmptyString
    severity: Severity
    message: NonEmptyString
    source_locator: NonEmptyString


class TranslationQA(ContractModel):
    id: NonEmptyString
    job_id: NonEmptyString
    candidate_version: NonEmptyString
    coverage_result: CheckResult
    protected_span_result: CheckResult
    numeric_entity_result: CheckResult
    semantic_findings: list[SemanticFinding]
    severity: Severity
    verifier_model: NonEmptyString | None
    check_version: NonEmptyString
    evidence_ref: NonEmptyString | None
