"""Immutable artifact references and bundle records, not provenance proofs."""
from typing import Literal, Self

from pydantic import ConfigDict, model_validator

from .providers import ContractModel, NonEmptyString, RFC3339_SCHEMA, Sha256, WireTimestamp


class ArtifactDependency(ContractModel):
    artifact_version_id: NonEmptyString
    relationship: NonEmptyString


class ArtifactVersion(ContractModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True,
        json_schema_extra={"allOf": [{
            "if": {"properties": {"canonical_issued_by": {"const": "A"}}},
            "then": {"properties": {"a_response_ref": {"type": "string", "minLength": 1, "pattern": r"\S"}}},
        }]},
    )

    id: NonEmptyString
    task_id: NonEmptyString
    artifact_kind: NonEmptyString
    language: NonEmptyString
    immutable_uri: NonEmptyString
    byte_sha256: Sha256
    canonical_content_sha256: Sha256
    source_version_id: NonEmptyString | None
    origin_authors: list[NonEmptyString]
    canonical_issued_by: NonEmptyString
    reviewed_by: list[NonEmptyString]
    rendered_by: NonEmptyString
    a_response_ref: NonEmptyString | None
    dependencies: list[ArtifactDependency]

    @model_validator(mode="after")
    def a_canonical_requires_response_reference(self) -> Self:
        if self.canonical_issued_by == "A" and self.a_response_ref is None:
            raise ValueError("A_RESPONSE_REFERENCE_REQUIRED")
        return self


class ArtifactPair(ContractModel):
    artifact_pair_id: NonEmptyString
    format: Literal["pdf", "docx", "markdown"]
    source_version_id: NonEmptyString
    english_artifact_id: NonEmptyString
    chinese_artifact_id: NonEmptyString


class DeliveryBundle(ContractModel):
    """A stored state/reference declaration; the publisher must verify it."""
    model_config = ConfigDict(
        extra="forbid", frozen=True,
        json_schema_extra={"allOf": [{
            "if": {"properties": {"state": {"const": "PUBLISHED"}}},
            "then": {"properties": {
                "approval_id": {"type": "string", "minLength": 1, "pattern": r"\S"},
                "published_at": dict(RFC3339_SCHEMA),
                "source_version_ids": {"minItems": 1},
            }},
        }]},
    )

    id: NonEmptyString
    task_id: NonEmptyString
    turn_id: NonEmptyString
    spec_version: NonEmptyString
    route_snapshot_id: NonEmptyString
    source_version_ids: list[NonEmptyString]
    translation_version_ids: list[NonEmptyString]
    format_pairs: list[ArtifactPair]
    qa_ids: list[NonEmptyString]
    approval_id: NonEmptyString | None
    state: Literal["STAGING", "VERIFIED", "PUBLISHED"]
    published_at: WireTimestamp | None

    @model_validator(mode="after")
    def published_requires_complete_references(self) -> Self:
        if self.state == "PUBLISHED" and (
                self.approval_id is None or self.published_at is None
                or not self.source_version_ids):
            raise ValueError("PUBLISHED_BUNDLE_MISSING_REFERENCES")
        return self
