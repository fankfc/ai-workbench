from dataclasses import replace
import pytest

from app.providers.phase_bridge import PhaseUsage, PhaseStarted
from app.usage.normalization import normalize_usage
from test_phase_bridge import prepared, MemoryRuntime, run, error


def bill(prepared):
    capture = prepared[-1]
    return PhaseUsage(capture.local_request_id, capture.observed_provider,
        capture.external_request_id, capture.external_execution_id, capture.usage_receipts)


def test_bill_only_record_retains_actual_usage_and_never_exposes_a_candidate(prepared):
    runtime = MemoryRuntime([PhaseStarted('local-request', 'remote-request', 'remote-execution'), bill(prepared)])
    events, _, _ = run(prepared, runtime=runtime)
    assert error(events) == 'BILLABLE_CAPTURE_FAILED'
    usage = [event for event in events if event.kind == 'provider.usage']
    assert len(usage) == 1 and normalize_usage('glm', usage[0].payload['raw'], usage[0].payload['source'])['total_tokens'] == 12
    assert not any(event.kind in ('artifact.candidate', 'review.decision', 'provider.completed') for event in events)


@pytest.mark.parametrize('field', ['local_request_id', 'external_request_id', 'external_execution_id'])
def test_foreign_billing_record_cannot_charge_the_current_request(prepared, field):
    record = replace(bill(prepared), **{field: 'foreign'})
    runtime = MemoryRuntime([PhaseStarted('local-request', 'remote-request', 'remote-execution'), record])
    events, _, _ = run(prepared, runtime=runtime)
    assert error(events) == 'CAPTURE_REQUEST_BINDING_MISMATCH'
    assert not any(event.kind == 'provider.usage' for event in events)
