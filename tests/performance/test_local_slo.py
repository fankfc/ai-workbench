from support.scenarios.local_performance import percentile


def test_performance_keeps_unmeasured_gui_values_unknown(probe):
    result = probe('local_performance', history_tasks=10000, active_tasks=1)
    assert result['latency_components']['history_tasks'] == 10000
    assert len(result['latency_components']['samples_ms']) == 30
    assert all(sample > 0 for sample in result['latency_components']['samples_ms'])
    if '30_desktop_cold_starts' in result['unmet_checks']:
        # Small measured samples stay visible but cannot qualify the threshold.
        assert result['cold_start_p95_ms'] is None or result['cold_start_p95_ms'] > 0
    if 'send_ack' in result['unmet_checks']:
        assert result['ui_ack_p95_ms'] is None
    assert '24h_soak' in result['unmet_checks']
    assert result['orphan_pids'] == []


def test_p95_preserves_slow_samples():
    samples = list(range(1, 101))
    assert percentile(samples) == 95
    assert len(samples) == 100
    assert percentile([]) is None
