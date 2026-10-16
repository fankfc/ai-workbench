"""D007 schema boundaries; no real provider, translation, or publication."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker
import pytest
from pydantic import TypeAdapter, ValidationError

from app.contracts.artifacts import ArtifactVersion, DeliveryBundle
from app.contracts.events import (
    AgentEvent, InternalEventRecord, MessageRecord, PublicEvent,
    validate_event_sequence,
)
from app.contracts.providers import (
    AgentRequest, ModelFamily, ProviderContract, ProviderIdentity, RouteSnapshot, Sha256,
)
from app.contracts.translation import TranslationBlock, TranslationJob, TranslationQA


ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 64
NOW = "2026-10-13T19:00:00+08:00"


def provider_sample():
    return {
        "schema_version": "1.0", "provider_id": "fixture",
        "identity": {"adapter": "claude_code", "model_id": "test-claude", "family": "claude", "connection_id": "c1"},
        "identity_status": "verified", "identity_source": "test-fixture-only",
        "connection_version": "test-only",
    }


def route_sample():
    return {
        "id": "r1", "task_id": "t1", "turn_id": "turn1", "attempt_id": "a1",
        "provider_id": "fixture", "model_id": "test-claude", "model_family": "claude",
        "adapter_id": "claude_code", "identity_status": "verified",
        "identity_source": "test-fixture-only", "connection_version": "test-only",
        "policy_version": "1.0", "route_policy": "claude_en_bridge", "locked_at": NOW,
    }


PUBLIC_PAYLOADS = {
    "message.accepted": {"message_id": "m1", "text": "用户原话", "language": "zh-CN"},
    "response.pending": {"status": "pending"},
    "answer.published": {"message_id": "m2", "text": "最终中文回答", "language": "zh-CN", "content_version_id": "v1", "approval_id": "approval1"},
    "artifacts.published": {"bundle_id": "bundle1", "version_id": "v1", "artifacts": [{"artifact_id": "f1", "artifact_pair_id": "pair1", "format": "pdf", "language": "en", "file_name": "report.en.pdf", "size_bytes": 20}]},
    "request.failed": {"error_code": "CONNECTION_UNAVAILABLE", "text": "连接不可用，请重试。", "language": "zh-CN", "action": "retry"},
    "request.cancelled": {"text": "已请求停止。", "language": "zh-CN", "cancel_requested": True, "external_stop_confirmed": None},
    "input.required": {"prompt_id": "q1", "text": "请确认交付范围。", "language": "zh-CN"},
}


def public_sample(kind="answer.published"):
    return {
        "schema_version": "1.0", "event_id": "e1", "conversation_id": "conv1",
        "turn_id": "turn1", "task_id": "t1", "attempt_id": "a1", "sequence": 1,
        "kind": kind, "payload": deepcopy(PUBLIC_PAYLOADS[kind]),
    }


def assert_both_accept(model, sample):
    value = model.model_validate_json(json.dumps(sample))
    schema = model.model_json_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=registered_format_checker()).validate(sample)
    return value


def assert_both_reject(model, sample):
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(sample))
    assert list(Draft202012Validator(model.model_json_schema(), format_checker=registered_format_checker()).iter_errors(sample))


def registered_format_checker():
    checker = FormatChecker()
    assert "date-time" in checker.checkers, "date-time validation dependency is missing"
    return checker


def test_legacy_dataclasses_keep_positional_order_and_frozen_fields():
    identity = ProviderIdentity("claude_code", "test", ModelFamily.CLAUDE, "c1")
    request = AgentRequest("t1", "a1", "A", identity, "prompt.md", "workspace", "v1")
    event = AgentEvent("t1", "a1", 1, "model.delta", {"text": "internal"})
    assert [f.name for f in fields(identity)] == ["adapter", "model_id", "family", "connection_id"]
    assert [f.name for f in fields(request)] == ["task_id", "attempt_id", "role", "identity", "prompt_path", "workspace", "policy_version"]
    assert [f.name for f in fields(event)] == ["task_id", "attempt_id", "sequence", "kind", "payload"]
    for obj in (identity, request, event):
        with pytest.raises(FrozenInstanceError):
            obj.task_id = "other"


@pytest.mark.parametrize("model,kwargs", [
    (ProviderIdentity, {"adapter": "", "model_id": "m", "family": ModelFamily.CLAUDE, "connection_id": "c"}),
    (AgentEvent, {"task_id": "", "attempt_id": "a", "sequence": 1, "kind": "model.delta", "payload": {}}),
    (AgentEvent, {"task_id": "t", "attempt_id": "a", "sequence": 0, "kind": "model.delta", "payload": {}}),
])
def test_legacy_records_reject_invalid_values(model, kwargs):
    with pytest.raises((ValidationError, ValueError, TypeError)):
        model(**kwargs)


def test_verified_provider_executes_only_with_identity_evidence():
    value = assert_both_accept(ProviderContract, provider_sample())
    value.require_executable()


@pytest.mark.parametrize("status", ["unknown", "mismatch"])
def test_unverified_provider_is_recordable_but_not_executable(status):
    data = provider_sample()
    data.update(identity_status=status, identity_source=None)
    data["identity"]["family"] = "unknown"
    value = assert_both_accept(ProviderContract, data)
    with pytest.raises(ValueError, match="UNVERIFIED_MODEL_IDENTITY"):
        value.require_executable()


@pytest.mark.parametrize("fault", ["family", "extra", "source"])
def test_provider_rejects_unknown_family_extra_fields_or_false_verified(fault):
    data = provider_sample()
    if fault == "family":
        data["identity"]["family"] = "claude-alias"
    elif fault == "extra":
        data["identity"]["api_key"] = "SECRET_CANARY"
    else:
        data["identity_source"] = None
    assert_both_reject(ProviderContract, data)


def test_route_is_frozen_and_claude_policy_is_not_guessed():
    route = assert_both_accept(RouteSnapshot, route_sample())
    route.require_executable(ProviderContract.model_validate(provider_sample()))
    with pytest.raises(ValidationError):
        route.route_policy = "native"
    wrong = route_sample()
    wrong["route_policy"] = "native"
    assert_both_reject(RouteSnapshot, wrong)


def test_gpt_native_route_has_no_bridge():
    sample = route_sample()
    sample.update(model_family="gpt", model_id="test-gpt", route_policy="native")
    provider = provider_sample()
    provider["identity"].update(family="gpt", model_id="test-gpt")
    assert_both_accept(RouteSnapshot, sample).require_executable(ProviderContract.model_validate(provider))


def test_unknown_route_can_record_null_policy_but_cannot_execute():
    sample = route_sample()
    sample.update(model_family="unknown", identity_status="unknown", identity_source=None, route_policy=None)
    route = assert_both_accept(RouteSnapshot, sample)
    with pytest.raises(ValueError, match="UNVERIFIED_MODEL_IDENTITY"):
        route.require_executable(ProviderContract.model_validate(provider_sample()))


@pytest.mark.parametrize("field", ["provider_id", "model_id", "adapter_id", "connection_version", "identity_source"])
def test_executable_route_must_match_bound_provider(field):
    sample = route_sample()
    sample[field] = "other-binding"
    route = assert_both_accept(RouteSnapshot, sample)
    with pytest.raises(ValueError, match="ROUTE_PROVIDER_MISMATCH"):
        route.require_executable(ProviderContract.model_validate(provider_sample()))


@pytest.mark.parametrize("missing", list(route_sample()))
def test_route_requires_every_spec_field(missing):
    sample = route_sample()
    sample.pop(missing)
    assert_both_reject(RouteSnapshot, sample)


@pytest.mark.parametrize("kind", list(PUBLIC_PAYLOADS))
def test_public_whitelist_has_typed_payloads_in_both_schemas(kind):
    event = assert_both_accept(PublicEvent, public_sample(kind))
    assert event.model_dump(mode="json")["kind"] == kind


@pytest.mark.parametrize("kind", list(PUBLIC_PAYLOADS))
@pytest.mark.parametrize("location", ["top", "payload"])
def test_public_events_reject_internal_fields_at_every_boundary(kind, location):
    sample = public_sample(kind)
    target = sample if location == "top" else sample["payload"]
    target["raw_response"] = "INTERNAL_ENGLISH_CANARY"
    assert_both_reject(PublicEvent, sample)


@pytest.mark.parametrize("fault", ["kind", "attempt", "sequence", "boolean_sequence", "payload_kind", "approval", "artifact_extra", "version"])
def test_public_events_reject_invalid_or_unapproved_envelopes(fault):
    sample = public_sample()
    if fault == "kind":
        sample["kind"] = "tool.delta"
    elif fault == "attempt":
        sample.pop("attempt_id")
    elif fault == "sequence":
        sample["sequence"] = "1"
    elif fault == "boolean_sequence":
        sample["sequence"] = True
    elif fault == "payload_kind":
        sample["payload"] = {"status": "pending"}
    elif fault == "approval":
        sample["payload"].pop("approval_id")
    elif fault == "version":
        sample["schema_version"] = "2.0"
    else:
        sample = public_sample("artifacts.published")
        sample["payload"]["artifacts"][0]["immutable_uri"] = "private/path"
    assert_both_reject(PublicEvent, sample)


def test_internal_event_may_contain_raw_payload_but_public_schema_rejects_it():
    sample = {"task_id": "t1", "attempt_id": "a1", "sequence": 1, "kind": "model.delta", "payload": {"text": "INTERNAL_ENGLISH_CANARY"}}
    InternalEventRecord.model_validate(sample)
    assert_both_reject(PublicEvent, sample)


def test_sequence_validation_needs_stream_context_and_rejects_disorder():
    validate_event_sequence([AgentEvent("t", "a", n, "model.delta", {}) for n in (1, 2, 3)])
    for sequence in [(1, 2, 2), (1, 3, 2)]:
        with pytest.raises(ValueError, match="EVENT_SEQUENCE_NOT_INCREASING"):
            validate_event_sequence([AgentEvent("t", "a", n, "model.delta", {}) for n in sequence])
    with pytest.raises(ValueError, match="EVENT_STREAM_MISMATCH"):
        validate_event_sequence([AgentEvent("t", "a", 1, "model.delta", {}), AgentEvent("other", "a", 2, "model.delta", {})])


RECORD_SAMPLES = {
    MessageRecord: {"id": "m", "turn_id": "turn", "source_role": "user", "language": "zh-CN", "raw_content_ref": "blob1", "content_sha256": SHA, "parent_message_id": None, "route_snapshot_id": "r", "visibility": "internal", "created_at": NOW},
    TranslationJob: {"id": "j", "task_id": "t", "turn_id": "turn", "source_ref": "blob", "source_sha256": SHA, "source_language": "zh-CN", "target_language": "en", "glossary_version": "g1", "policy_version": "v1", "purpose": "input", "status": "PENDING", "attempt_count": 0, "budget_id": "b"},
    TranslationBlock: {"job_id": "j", "block_id": "block", "source_locator": "input.md:p1", "source_sha256": SHA, "target_ref": None, "target_sha256": None, "protected_span_ids": [], "translation_status": "PENDING", "uncertainty_codes": []},
    TranslationQA: {"id": "qa", "job_id": "j", "candidate_version": "v1", "coverage_result": "not_verified", "protected_span_result": "not_verified", "numeric_entity_result": "not_verified", "semantic_findings": [], "severity": "none", "verifier_model": None, "check_version": "v1", "evidence_ref": None},
    ArtifactVersion: {"id": "v1", "task_id": "t", "artifact_kind": "markdown", "language": "en", "immutable_uri": "blob1", "byte_sha256": SHA, "canonical_content_sha256": SHA, "source_version_id": None, "origin_authors": ["B"], "canonical_issued_by": "B", "reviewed_by": ["A"], "rendered_by": "C", "a_response_ref": None, "dependencies": []},
    DeliveryBundle: {"id": "bundle", "task_id": "t", "turn_id": "turn", "spec_version": "v1", "route_snapshot_id": "r", "source_version_ids": ["v1"], "translation_version_ids": ["zh-v1"], "format_pairs": [{"artifact_pair_id": "pair1", "format": "markdown", "source_version_id": "v1", "english_artifact_id": "en-v1", "chinese_artifact_id": "zh-v1"}], "qa_ids": [], "approval_id": None, "state": "STAGING", "published_at": None},
}


@pytest.mark.parametrize("model", list(RECORD_SAMPLES))
def test_spec_records_preserve_all_required_and_nullable_fields(model):
    sample = RECORD_SAMPLES[model]
    value = assert_both_accept(model, sample)
    assert set(value.model_dump()) == set(sample)
    for missing in sample:
        incomplete = deepcopy(sample)
        incomplete.pop(missing)
        assert_both_reject(model, incomplete)


def test_message_visibility_is_only_user_internal_or_attachment():
    for visibility in ("user", "internal", "attachment"):
        sample = deepcopy(RECORD_SAMPLES[MessageRecord])
        sample["visibility"] = visibility
        assert_both_accept(MessageRecord, sample)
    sample["visibility"] = "public_raw"
    assert_both_reject(MessageRecord, sample)


def test_b_authored_artifact_is_recorded_without_claiming_a_authorship():
    record = assert_both_accept(ArtifactVersion, RECORD_SAMPLES[ArtifactVersion])
    assert record.canonical_issued_by == "B"
    assert record.a_response_ref is None


def test_translation_attempt_limit_and_hash_integrity():
    sample = deepcopy(RECORD_SAMPLES[TranslationJob])
    sample["attempt_count"] = 4
    assert_both_reject(TranslationJob, sample)
    sample = deepcopy(RECORD_SAMPLES[TranslationBlock])
    sample["source_sha256"] = "unverified-hash"
    assert_both_reject(TranslationBlock, sample)


def test_ready_translation_requires_target_and_hash():
    sample = deepcopy(RECORD_SAMPLES[TranslationBlock])
    sample["translation_status"] = "READY"
    assert_both_reject(TranslationBlock, sample)


@pytest.mark.parametrize("fault", ["approval_id", "published_at", "source_version_ids"])
def test_published_bundle_requires_common_references(fault):
    sample = deepcopy(RECORD_SAMPLES[DeliveryBundle])
    sample.update(state="PUBLISHED", approval_id="approval1", published_at=NOW, qa_ids=["qa1"])
    sample[fault] = None if fault in ("approval_id", "published_at") else []
    assert_both_reject(DeliveryBundle, sample)


def test_a_issued_artifact_requires_response_reference_without_proving_authorship():
    sample = deepcopy(RECORD_SAMPLES[ArtifactVersion])
    sample.update(canonical_issued_by="A", origin_authors=["A"], a_response_ref=None)
    assert_both_reject(ArtifactVersion, sample)
    sample["a_response_ref"] = "unverified-response-ref"
    assert_both_accept(ArtifactVersion, sample)


def test_route_execution_rechecks_policy_on_unvalidated_model_copy():
    route = RouteSnapshot.model_validate(route_sample()).model_copy(update={"route_policy": "native"})
    with pytest.raises(ValueError, match="MODEL_ROUTE_MISMATCH"):
        route.require_executable(ProviderContract.model_validate(provider_sample()))


@pytest.mark.parametrize("flag", [1, "true", False])
def test_public_cancel_requires_boolean_true_without_coercion(flag):
    sample = public_sample("request.cancelled")
    sample["payload"]["cancel_requested"] = flag
    assert_both_reject(PublicEvent, sample)


def test_native_published_bundle_does_not_force_translation_or_bilingual_pairs():
    sample = deepcopy(RECORD_SAMPLES[DeliveryBundle])
    sample.update(state="PUBLISHED", approval_id="approval-native", published_at=NOW,
                  translation_version_ids=[], format_pairs=[], qa_ids=[])
    bundle = assert_both_accept(DeliveryBundle, sample)
    assert bundle.translation_version_ids == []
    assert bundle.format_pairs == []
    assert bundle.qa_ids == []


def test_date_time_format_checker_is_really_registered():
    checker = FormatChecker()
    assert "date-time" in checker.checkers, "date-time validation dependency is missing"
    assert not checker.conforms("2026-02-30T19:00:00+08:00", "date-time")


TIMESTAMP_FIELDS = [(RouteSnapshot, "locked_at"), (MessageRecord, "created_at"), (DeliveryBundle, "published_at")]


def timestamp_sample(model, field, value):
    sample = route_sample() if model is RouteSnapshot else deepcopy(RECORD_SAMPLES[model])
    if model is DeliveryBundle:
        sample.update(state="PUBLISHED", approval_id="approval-native", translation_version_ids=[], format_pairs=[], qa_ids=[])
    sample[field] = value
    return sample


@pytest.mark.parametrize("model,field", TIMESTAMP_FIELDS)
@pytest.mark.parametrize("value", [NOW, "2026-10-13T11:00:00Z", "2026-10-13T11:00:00.123456Z"])
def test_timestamp_wire_accepts_rfc3339_with_timezone(model, field, value):
    assert_both_accept(model, timestamp_sample(model, field, value))


@pytest.mark.parametrize("model,field", TIMESTAMP_FIELDS)
@pytest.mark.parametrize("value", [
    0, 0.0, "0", "2026-10-13T19:00:00", "2026-10-13 19:00:00+08:00",
    "2026-02-30T19:00:00+08:00", "2026-10-13T19:00:00+08:00\n",
    " 2026-10-13T19:00:00+08:00", "2026-10-13T19:00:00+08:00 ",
])
def test_timestamp_wire_rejects_coercion_naive_space_and_invalid_dates(model, field, value):
    assert_both_reject(model, timestamp_sample(model, field, value))


@pytest.mark.parametrize("model,field", TIMESTAMP_FIELDS)
def test_timestamp_python_accepts_only_aware_datetime(model, field):
    aware = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)
    record = model.model_validate(timestamp_sample(model, field, aware))
    assert getattr(record, field).utcoffset() is not None
    with pytest.raises(ValidationError):
        model.model_validate(timestamp_sample(model, field, aware.replace(tzinfo=None)))


@pytest.mark.parametrize("model,field", TIMESTAMP_FIELDS)
@pytest.mark.parametrize("offset", ["+00:60", "+00:99", "+24:00"])
def test_timestamp_rejects_out_of_range_offset_without_normalization(model, field, offset):
    assert_both_reject(model, timestamp_sample(model, field, "2026-10-13T19:00:00" + offset))


@pytest.mark.parametrize("model,field", TIMESTAMP_FIELDS)
def test_timestamp_accepts_maximum_valid_offset(model, field):
    assert_both_accept(model, timestamp_sample(model, field, "2026-10-13T19:00:00+23:59"))


@pytest.mark.parametrize("value", ["a" * 64, "a" * 64 + "\n", "g" * 64])
def test_shared_sha256_has_same_exact_length_and_hex_boundary(value):
    adapter = TypeAdapter(Sha256)
    validator = Draft202012Validator(adapter.json_schema())
    if value == "a" * 64:
        assert adapter.validate_json(json.dumps(value)) == value
        validator.validate(value)
    else:
        with pytest.raises(ValidationError):
            adapter.validate_json(json.dumps(value))
        assert list(validator.iter_errors(value))


INTEGER_FIELDS = [
    (PublicEvent, "sequence"),
    (PublicEvent, "artifact_size"),
    (TranslationJob, "attempt_count"),
]


def integer_sample(model, field, value):
    if field == "artifact_size":
        sample = public_sample("artifacts.published")
        sample["payload"]["artifacts"][0]["size_bytes"] = value
    else:
        sample = public_sample() if model is PublicEvent else deepcopy(RECORD_SAMPLES[model])
        sample[field] = value
    return sample


def normalized_integer(record, field):
    data = record.model_dump(mode="json")
    if field == "artifact_size":
        return data["payload"]["artifacts"][0]["size_bytes"]
    return data[field]


@pytest.mark.parametrize("model,field", INTEGER_FIELDS)
@pytest.mark.parametrize("value,accepted", [(1, True), (1.0, True), (True, False), ("1", False), (1.5, False), (float("inf"), False)])
def test_json_mathematical_integer_semantics_match_python_and_schema(model, field, value, accepted):
    sample = integer_sample(model, field, value)
    if accepted:
        record = assert_both_accept(model, sample)
        assert type(normalized_integer(record, field)) is int
        python_record = model.model_validate(sample)
        assert type(normalized_integer(python_record, field)) is int
    else:
        assert_both_reject(model, sample)
        with pytest.raises(ValidationError):
            model.model_validate(sample)


@pytest.mark.parametrize("model,field,value,accepted", [
    (PublicEvent, "sequence", 0.0, False),
    (PublicEvent, "artifact_size", 0.0, True),
    (PublicEvent, "artifact_size", -1.0, False),
    (TranslationJob, "attempt_count", 3.0, True),
    (TranslationJob, "attempt_count", 4.0, False),
])
def test_json_integer_constraints_still_apply_after_normalization(model, field, value, accepted):
    sample = integer_sample(model, field, value)
    if accepted:
        record = assert_both_accept(model, sample)
        assert type(normalized_integer(record, field)) is int
    else:
        assert_both_reject(model, sample)


def test_legacy_agent_event_normalizes_integral_float_to_frozen_int():
    event = AgentEvent("t", "a", 1.0, "model.delta", {})
    assert event.sequence == 1
    assert type(event.sequence) is int
    with pytest.raises(FrozenInstanceError):
        event.sequence = 2


def test_schema_script_strict_check_and_drift_rejection(tmp_path):
    script = ROOT / "scripts" / "check_contracts.py"
    write = subprocess.run([sys.executable, str(script), "--write", "--schema-dir", str(tmp_path)], capture_output=True, text=True, check=False)
    assert write.returncode == 0, write.stdout + write.stderr
    strict = subprocess.run([sys.executable, str(script), "--strict", "--schema-dir", str(tmp_path)], capture_output=True, text=True, check=False)
    assert strict.returncode == 0, strict.stdout + strict.stderr
    schema = tmp_path / "public-events.schema.json"
    data = json.loads(schema.read_text(encoding="utf-8"))
    data["description"] = "DRIFT_CANARY"
    schema.write_text(json.dumps(data), encoding="utf-8")
    drift = subprocess.run([sys.executable, str(script), "--strict", "--schema-dir", str(tmp_path)], capture_output=True, text=True, check=False)
    assert drift.returncode != 0
    assert "SCHEMA_DRIFT" in drift.stdout + drift.stderr


def test_checked_in_json_schemas_validate_public_and_provider_samples():
    for name, model, sample in [("public-events", PublicEvent, public_sample()), ("provider", ProviderContract, provider_sample())]:
        schema = json.loads((ROOT / "packages" / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(sample)
        model.model_validate_json(json.dumps(sample))
        invalid = deepcopy(sample)
        invalid["raw_response"] = "INTERNAL_ENGLISH_CANARY"
        assert list(Draft202012Validator(schema).iter_errors(invalid))
