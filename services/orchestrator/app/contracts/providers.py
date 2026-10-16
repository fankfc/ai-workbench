"""Identity records and immutable A-route snapshots; no connection probing."""
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import math
import re
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, WithJsonSchema, model_validator

SCHEMA_VERSION = "1.0"
NonEmptyString = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
Sha256 = Annotated[str, StringConstraints(strict=True, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")]
RFC3339_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt](?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])(?![\s\S])"
)
RFC3339_SCHEMA = {"type": "string", "format": "date-time", "pattern": RFC3339_PATTERN}


def _wire_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("RFC3339_TIMEZONE_REQUIRED")
        return value
    if not isinstance(value, str) or re.fullmatch(RFC3339_PATTERN, value) is None:
        raise ValueError("RFC3339_STRING_REQUIRED")
    parsed = datetime.fromisoformat(value[:-1] + "Z" if value.endswith("z") else value)
    if parsed.utcoffset() is None:
        raise ValueError("RFC3339_TIMEZONE_REQUIRED")
    return parsed


def _json_integer(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("JSON_INTEGER_REQUIRED")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    raise ValueError("JSON_INTEGER_REQUIRED")


WireTimestamp = Annotated[AwareDatetime, BeforeValidator(_wire_timestamp), WithJsonSchema(RFC3339_SCHEMA)]
SequenceNumber = Annotated[int, Field(strict=True, ge=1), BeforeValidator(_json_integer)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0), BeforeValidator(_json_integer)]
TranslationAttemptCount = Annotated[int, Field(strict=True, ge=0, le=3), BeforeValidator(_json_integer)]
RoutePolicy = Literal["claude_en_bridge", "native"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelFamily(StrEnum):
    CLAUDE = "claude"
    GPT = "gpt"
    GLM = "glm"
    UNKNOWN = "unknown"


class IdentityStatus(StrEnum):
    VERIFIED = "verified"
    UNKNOWN = "unknown"
    MISMATCH = "mismatch"


class ProviderIdentityRecord(ContractModel):
    adapter: NonEmptyString
    model_id: NonEmptyString
    family: ModelFamily
    connection_id: NonEmptyString


@dataclass(frozen=True)
class ProviderIdentity:
    adapter: str
    model_id: str
    family: ModelFamily
    connection_id: str

    def __post_init__(self) -> None:
        value = ProviderIdentityRecord.model_validate(asdict(self))
        object.__setattr__(self, "family", value.family)


class AgentRequestRecord(ContractModel):
    task_id: NonEmptyString
    attempt_id: NonEmptyString
    role: NonEmptyString
    identity: ProviderIdentityRecord
    prompt_path: NonEmptyString
    workspace: NonEmptyString
    policy_version: NonEmptyString


@dataclass(frozen=True)
class AgentRequest:
    task_id: str
    attempt_id: str
    role: str
    identity: ProviderIdentity
    prompt_path: str
    workspace: str
    policy_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ProviderIdentity):
            raise TypeError("identity must be ProviderIdentity")
        AgentRequestRecord.model_validate(asdict(self))


class ProviderContract(ContractModel):
    """Connection evidence association, separate from the legacy identity."""

    model_config = ConfigDict(
        extra="forbid", frozen=True,
        json_schema_extra={"allOf": [{
            "if": {"properties": {"identity_status": {"const": "verified"}}},
            "then": {"properties": {
                "identity_source": {"type": "string", "minLength": 1, "pattern": r"\S"},
                "identity": {"properties": {"family": {"enum": ["claude", "gpt", "glm"]}}},
            }},
        }]},
    )

    schema_version: Literal["1.0"]
    provider_id: NonEmptyString
    identity: ProviderIdentityRecord
    identity_status: IdentityStatus
    identity_source: NonEmptyString | None
    connection_version: NonEmptyString

    @model_validator(mode="after")
    def check_verified_identity(self) -> Self:
        if (self.identity_status == IdentityStatus.VERIFIED
                and (self.identity.family == ModelFamily.UNKNOWN or self.identity_source is None)):
            raise ValueError("UNVERIFIED_MODEL_IDENTITY")
        return self

    def require_executable(self) -> None:
        validated = ProviderContract.model_validate(self.model_dump())
        if validated.identity_status != IdentityStatus.VERIFIED:
            raise ValueError("UNVERIFIED_MODEL_IDENTITY")


class RouteSnapshot(ContractModel):
    """Unknown identity is recordable with explicit null policy, never executable."""

    model_config = ConfigDict(
        extra="forbid", frozen=True,
        json_schema_extra={"allOf": [{
            "if": {"properties": {"identity_status": {"const": "verified"}}},
            "then": {
                "properties": {
                    "model_family": {"enum": ["claude", "gpt"]},
                    "identity_source": {"type": "string", "minLength": 1, "pattern": r"\S"},
                    "route_policy": {"enum": ["claude_en_bridge", "native"]},
                },
                "allOf": [
                    {"if": {"properties": {"model_family": {"const": "claude"}}},
                     "then": {"properties": {"route_policy": {"const": "claude_en_bridge"}}}},
                    {"if": {"properties": {"model_family": {"const": "gpt"}}},
                     "then": {"properties": {"route_policy": {"const": "native"}}}},
                ],
            },
        }]},
    )

    id: NonEmptyString
    task_id: NonEmptyString
    turn_id: NonEmptyString
    attempt_id: NonEmptyString
    provider_id: NonEmptyString
    model_id: NonEmptyString
    model_family: ModelFamily
    adapter_id: NonEmptyString
    identity_status: IdentityStatus
    identity_source: NonEmptyString | None
    connection_version: NonEmptyString
    policy_version: NonEmptyString
    route_policy: RoutePolicy | None
    locked_at: WireTimestamp

    @model_validator(mode="after")
    def check_route_policy(self) -> Self:
        if self.identity_status == IdentityStatus.VERIFIED:
            expected = {ModelFamily.CLAUDE: "claude_en_bridge", ModelFamily.GPT: "native"}.get(self.model_family)
            if self.identity_source is None or expected is None:
                raise ValueError("UNVERIFIED_MODEL_IDENTITY")
            if self.route_policy != expected:
                raise ValueError("MODEL_ROUTE_MISMATCH")
        return self

    def require_executable(self, provider: ProviderContract) -> None:
        """Check the snapshot against a supplied connection record, not a real probe."""
        RouteSnapshot.model_validate(self.model_dump())
        if self.identity_status != IdentityStatus.VERIFIED:
            raise ValueError("UNVERIFIED_MODEL_IDENTITY")
        provider.require_executable()
        expected = (provider.provider_id, provider.identity.model_id,
                    provider.identity.family, provider.identity.adapter,
                    provider.identity_source, provider.connection_version)
        actual = (self.provider_id, self.model_id, self.model_family, self.adapter_id,
                  self.identity_source, self.connection_version)
        if actual != expected:
            raise ValueError("ROUTE_PROVIDER_MISMATCH")
