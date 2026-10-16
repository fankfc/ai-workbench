import json
from pathlib import Path
import random
import sqlite3

from app.contracts.events import AgentEvent
from app.runtime.recovery import Recovery
from support.manifest import write_json
from support.scenario_driver import run_case

OPTIONS_SCHEMA = dict(type='object', additionalProperties=False, properties={'fault': dict(enum=[
    'cancel_then_1000_duplicate_successes', 'unknown_remote_after_restart', 'old_approval', 'upstream_change'])})
RESULT_SCHEMA = dict(type='object', additionalProperties=False,
    required=['external_starts', 'published_versions', 'task_state', 'cross_task_reads', 'orphan_pids'], properties={
        'external_starts': dict(type='integer', minimum=0), 'published_versions': dict(type='array'),
        'task_state': dict(type='string'), 'cross_task_reads': dict(type=['array', 'null']),
        'orphan_pids': dict(type=['array', 'null']), 'event_rejections': dict(type='array', items=dict(type='object')),
        'unmet_checks': dict(type='array', items=dict(type='string')), 'recovery_decision': dict(type=['string', 'null']),
        'provider_boundary': dict(enum=['fake']), 'real_provider_verified': dict(const=False)})


def run(root, options):
    fault = options.get('fault', 'cancel_then_1000_duplicate_successes')
    case = {'cancel_then_1000_duplicate_successes': 'backend_cancel_late',
            'unknown_remote_after_restart': 'backend_restart', 'old_approval': 'backend_old_approval',
            'upstream_change': 'backend_upstream_change'}[fault]
    result = run_case(case, root, 'mixed' if fault == 'upstream_change' else 'code')
    db = Path(result['database_path'])
    decisions = []
    if fault == 'cancel_then_1000_duplicate_successes':
        events = [AgentEvent(result['task_id'], result['attempt_id'], 1, 'provider.completed',
                    dict(provider_event_id='late-success', text='INTERNAL_ENGLISH_CANARY')) for _ in range(1000)]
        random.Random(4317).shuffle(events)
        recovery = Recovery(db)
        for event in events:
            decisions.append(recovery.ingest(event, '1.0'))
    with sqlite3.connect(db) as connection:
        state = connection.execute('SELECT state FROM task_runs WHERE task_id=?', (result['task_id'],)).fetchone()[0]
        published = connection.execute("SELECT public_event_json FROM outbox_events WHERE task_id=? AND kind='answer.published' AND public_event_json IS NOT NULL", (result['task_id'],)).fetchall()
    observations = dict(external_starts=result['model_starts'], published_versions=[json.loads(r[0]) for r in published],
         task_state=state, cross_task_reads=None, orphan_pids=None, event_rejections=decisions,
         unmet_checks=['all_crash_cutpoints', 'windows_file_lock', 'two_session_stress', 'real_provider_cancel'],
         recovery_decision=result['recovery_decision'], provider_boundary='fake', real_provider_verified=False)
    write_json(root / 'fault-observations.json', observations)
    return observations
