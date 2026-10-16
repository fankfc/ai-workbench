"""Separate internal records and a strict public event discriminated union."""
from dataclasses import asdict, dataclass
from typing import Annotated, Iterable, Literal

from pydantic import ConfigDict, Field, RootModel, StrictBool, field_validator

from .providers import ContractModel, NonEmptyString, NonNegativeInt, SequenceNumber, Sha256, WireTimestamp


class InternalEventRecord(ContractModel):
    task_id: NonEmptyString
    attempt_id: NonEmptyString
    sequence: SequenceNumber
    kind: NonEmptyString
    payload: dict


@dataclass(frozen=True)
class AgentEvent:
    task_id: str
    attempt_id: str
    sequence: int
    kind: str
    payload: dict

    def __post_init__(self) -> None:
        value = InternalEventRecord.model_validate(asdict(self))
        object.__setattr__(self, "sequence", value.sequence)


def validate_event_sequence(events: Iterable[AgentEvent | InternalEventRecord]) -> None:
    """Validate one supplied task/attempt stream; duplicate policy belongs to D012."""
    stream = None
    previous = 0
    for event in events:
        if stream is None:
            stream = (event.task_id, event.attempt_id)
        if (event.task_id, event.attempt_id) != stream:
            raise ValueError("EVENT_STREAM_MISMATCH")
        if event.sequence <= previous:
            raise ValueError("EVENT_SEQUENCE_NOT_INCREASING")
        previous = event.sequence


class MessageRecord(ContractModel):
    id: NonEmptyString
    turn_id: NonEmptyString
    source_role: NonEmptyString
    language: NonEmptyString
    raw_content_ref: NonEmptyString
    content_sha256: Sha256
    parent_message_id: NonEmptyString | None
    route_snapshot_id: NonEmptyString
    visibility: Literal["user", "internal", "attachment"]
    created_at: WireTimestamp


class MessageAcceptedPayload(ContractModel):
    message_id: NonEmptyString
    text: NonEmptyString
    language: NonEmptyString


class ResponsePendingPayload(ContractModel):
    status: Literal["pending"]


class AnswerPublishedPayload(ContractModel):
    """References are mandatory; D018 must verify actual approval and route gates."""
    message_id: NonEmptyString
    text: NonEmptyString
    language: NonEmptyString
    content_version_id: NonEmptyString
    approval_id: NonEmptyString


class PublicArtifact(ContractModel):
    artifact_id: NonEmptyString
    artifact_pair_id: NonEmptyString | None
    format: NonEmptyString
    language: NonEmptyString
    file_name: NonEmptyString
    size_bytes: NonNegativeInt


class ArtifactsPublishedPayload(ContractModel):
    bundle_id: NonEmptyString
    version_id: NonEmptyString
    artifacts: Annotated[list[PublicArtifact], Field(min_length=1)]


class RequestFailedPayload(ContractModel):
    error_code: NonEmptyString
    text: NonEmptyString
    language: Literal["zh-CN"]
    action: Literal["retry", "reconnect", "provide_input", "none"]


class RequestCancelledPayload(ContractModel):
    text: NonEmptyString
    language: Literal["zh-CN"]
    cancel_requested: Annotated[StrictBool, Field(json_schema_extra={"const": True})]
    external_stop_confirmed: StrictBool | None

    @field_validator("cancel_requested")
    @classmethod
    def require_cancel_request(cls, value: bool) -> bool:
        if not value:
            raise ValueError("CANCEL_REQUEST_REQUIRED")
        return value


class InputRequiredPayload(ContractModel):
    prompt_id: NonEmptyString
    text: NonEmptyString
    language: Literal["zh-CN","en"]


class PublicEnvelope(ContractModel):
    schema_version: Literal["1.0"]
    event_id: NonEmptyString
    conversation_id: NonEmptyString
    turn_id: NonEmptyString
    task_id: NonEmptyString
    attempt_id: NonEmptyString
    sequence: SequenceNumber


class MessageAccepted(PublicEnvelope):
    kind: Literal["message.accepted"]
    payload: MessageAcceptedPayload


class ResponsePending(PublicEnvelope):
    kind: Literal["response.pending"]
    payload: ResponsePendingPayload


class AnswerPublished(PublicEnvelope):
    kind: Literal["answer.published"]
    payload: AnswerPublishedPayload


class ArtifactsPublished(PublicEnvelope):
    kind: Literal["artifacts.published"]
    payload: ArtifactsPublishedPayload


class RequestFailed(PublicEnvelope):
    kind: Literal["request.failed"]
    payload: RequestFailedPayload


class RequestCancelled(PublicEnvelope):
    kind: Literal["request.cancelled"]
    payload: RequestCancelledPayload


class InputRequired(PublicEnvelope):
    kind: Literal["input.required"]
    payload: InputRequiredPayload


PublicEventValue = Annotated[
    MessageAccepted | ResponsePending | AnswerPublished | ArtifactsPublished
    | RequestFailed | RequestCancelled | InputRequired,
    Field(discriminator="kind"),
]


class PublicEvent(RootModel[PublicEventValue]):
    """Schema permission does not prove release authority or translation quality."""
    model_config = ConfigDict(frozen=True)


PUBLIC_EVENT_KINDS = frozenset({
    "message.accepted", "response.pending", "answer.published", "artifacts.published",
    "request.failed", "request.cancelled", "input.required",
})
