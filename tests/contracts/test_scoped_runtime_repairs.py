"""Independent local schedules: no external provider or auth operations."""
import asyncio
import importlib.util
from pathlib import Path
import pytest
from app.providers.phase_bridge import PhaseCapture, PhaseUsage
from app.providers.scoped_codex_runtime import ScopedCodexError


def probes():
    path = Path(__file__).parents[2] / 'docs/acceptance/part-one-closeout/scoped-runtime-review-probe.py'
    spec = importlib.util.spec_from_file_location('scoped_independent_regression', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cancel_after_turn_permission_never_reopens_uncertain_attempt(tmp_path):
    result = asyncio.run(probes().cancellation_before_parent_consumes_submitted(tmp_path))
    assert result['parent_observed_submissions_before_cancel'] == 0
    assert result['states_after_cancel'][0]['state'] == 'unknown'
    assert result['next_request_allowed'] is False
    assert result['total_fixture_turns'] == 1


def test_zero_launch_boot_failure_retains_request_without_blocking_a_new_request(tmp_path):
    result = asyncio.run(probes().boot_failure(tmp_path))
    assert result['errors'] == ['FIXTURE_COMMAND_INVALID']
    assert result['states'] == [dict(request='first', state='failed_before_submission'),
                                dict(request='second', state='completed')]
    assert result['fixture_turns'] == 1


def test_ledger_handles_are_closed_without_garbage_collection(tmp_path):
    result = asyncio.run(probes().ledger_handle_lifetime(tmp_path))
    assert result['exclusive_read_after_runtime_close'] == dict(success=True, windows_error=0)
    assert result['fixture_turns'] == 0


def test_trailing_failure_preserves_bound_billing_without_business_capture(tmp_path):
    module = probes()
    runtime, _ = module.make_runtime(tmp_path, 'trailing_error')
    events = []
    try:
        with pytest.raises(ScopedCodexError):
            asyncio.run(module.collect(runtime, events=events))
        assert not any(isinstance(event, PhaseCapture) for event in events)
        bills = [event for event in events if isinstance(event, PhaseUsage)]
        assert len(bills) == 1 and bills[0].usage_receipts[0].raw['total_tokens'] == 33
        assert module.states(tmp_path)[0]['state'] == 'unknown'
        assert runtime.last_cleanup.cleanup_complete
    finally:
        runtime.close()
