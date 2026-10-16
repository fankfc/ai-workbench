import json
import math
from pathlib import Path
import sqlite3
import time

from app.api.application import create_app
from app.config import AppSettings
from support.local_service import local_service
from support.manifest import source_build_id, write_json

OPTIONS_SCHEMA = dict(type='object', additionalProperties=False, properties={
    'history_tasks': dict(type='integer', minimum=0, maximum=10000),
    'active_tasks': dict(type='integer', enum=[1])})
RESULT_SCHEMA = dict(type='object', additionalProperties=False, required=['input_echo_p95_ms', 'ui_ack_p95_ms',
    'cancel_feedback_p95_ms', 'state_visible_p95_ms', 'cold_start_p95_ms', 'orphan_pids', 'latency_components'], properties={
        **{name: dict(type=['number', 'null']) for name in ('input_echo_p95_ms', 'ui_ack_p95_ms',
            'cancel_feedback_p95_ms', 'state_visible_p95_ms', 'cold_start_p95_ms')},
        'orphan_pids': dict(type='array', items=dict(type='integer')),
        'latency_components': dict(type='object'), 'unmet_checks': dict(type='array', items=dict(type='string')),
        'provider_boundary': dict(enum=['fake']), 'real_provider_verified': dict(const=False)})


def percentile(samples, probability=.95):
    return sorted(samples)[max(0, math.ceil(len(samples) * probability) - 1)] if samples else None


def run(root, options):
    count = options.get('history_tasks', 10000)
    app = create_app(AppSettings(root / 'service-data', 'test-only-seeding', 'fake', False))
    with app.state.database.connect() as connection:
        connection.execute("INSERT INTO conversations(id,title) VALUES('history','历史任务')")
        connection.executemany("INSERT INTO turns(id,conversation_id,task_id,provider_profile_id,client_request_id,user_text) VALUES(?,'history',?,'fake-gpt',?,'历史输入')",
             [(f't{i}', f'task{i}', f'client{i}') for i in range(count)])
        connection.executemany("INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,state,route_snapshot_json) VALUES(?,'a1',?,'fake-gpt','CANCELLED','{}')",
             [(f'task{i}', f't{i}') for i in range(count)])
    service_started = time.perf_counter()
    samples = []
    with local_service(root) as service:
        startup_ms = (time.perf_counter() - service_started) * 1000
        for _ in range(30):
            start = time.perf_counter()
            with service['request']('/v1/conversations/history/messages') as response:
                json.load(response)
            samples.append((time.perf_counter() - start) * 1000)
    repo = Path(__file__).resolve().parents[3]
    ui_path = repo / 'artifacts/qa/D050/renderer-latency.json'
    ui = {}
    if ui_path.is_file():
        observed = json.loads(ui_path.read_text(encoding='utf-8'))
        if observed.get('build_id') == source_build_id() and observed.get('actual_electron') is True:
            ui = observed
    lifecycle = {}
    lifecycle_path = repo / 'artifacts/qa/D050/desktop-lifecycle.json'
    if lifecycle_path.is_file():
        observed = json.loads(lifecycle_path.read_text(encoding='utf-8'))
        if observed.get('build_id') == source_build_id() and observed.get('actual_electron') is True:
            lifecycle = observed
    unmet = ['cancel_feedback', '24h_soak', 'loaded_desktop_workload', 'hardware_power_baseline']
    if len(lifecycle.get('cold_start_samples_ms', [])) < 30:
        unmet.append('30_desktop_cold_starts')
    if lifecycle.get('cycles', 0) < 100:
        unmet.append('100_lifecycle_cycles')
    if not ui.get('ui_ack_samples_ms'):
        unmet.append('send_ack')
    if not ui.get('state_visible_samples_ms'):
        unmet.append('state_visibility')
    result = dict(input_echo_p95_ms=percentile(ui.get('input_echo_samples_ms', [])),
        ui_ack_p95_ms=percentile(ui.get('ui_ack_samples_ms', [])), cancel_feedback_p95_ms=None,
        state_visible_p95_ms=percentile(ui.get('state_visible_samples_ms', [])),
        cold_start_p95_ms=percentile(lifecycle.get('cold_start_samples_ms', [])),
        orphan_pids=[] if service['cleaned'] else [service['pid']],
        latency_components=dict(local_api_history_p95_ms=percentile(samples), backend_startup_single_ms=startup_ms,
             external_model_wait_ms=None, history_tasks=count, samples_ms=samples),
        unmet_checks=unmet,
        provider_boundary='fake', real_provider_verified=False)
    write_json(root / 'latency-observations.json', result)
    return result
