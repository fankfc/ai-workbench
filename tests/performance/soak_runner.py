"""Bounded local service soak. Checkpoints never turn a short run into 24h proof."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import shutil
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.local_service import local_service
from support.manifest import source_build_id, write_json
from support.resource_sample import resource_sample


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hours', type=float, default=24)
    parser.add_argument('--seed', type=int, default=4317)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--interval-seconds', type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.hours <= 24 or not 0 < args.interval_seconds <= 60:
        parser.error('duration and interval must be positive and bounded')
    root = args.output.absolute()
    from app.runtime.workspace import _reject_reparse
    _reject_reparse(root)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        parser.error('output directory must be empty; keep prior evidence in a different run')
    build = source_build_id()
    rng = random.Random(args.seed)
    requested = args.hours * 3600
    started = time.monotonic()
    successes = failures = samples = 0
    completed = False
    with local_service(root) as service:
        request = service['request']
        try:
            with (root / 'samples.jsonl').open('w', encoding='utf-8') as output:
                while time.monotonic() - started < requested:
                    now = time.monotonic()
                    failure = None
                    try:
                        with request('/v1/conversations', {'title': '持续运行本地试验'}) as response:
                            cid = json.load(response)['id']
                        with request(f'/v1/conversations/{cid}/turns', dict(text='有界固定任务',
                           provider_profile_id='fake-gpt', client_request_id=f'soak-{samples}-{rng.randrange(10**9)}')) as response:
                            tid = json.load(response)['task_id']
                        deadline = time.monotonic() + 20
                        while True:
                            with request('/v1/tasks/' + tid) as response:
                                task = json.load(response)
                            if task['status'] != 'pending' or time.monotonic() >= deadline:
                                break
                            time.sleep(.05)
                        if task['status'] != 'completed':
                            raise RuntimeError('SOAK_TASK_NOT_COMPLETED')
                        successes += 1
                    except Exception as error:
                        failures += 1
                        failure = type(error).__name__
                    samples += 1
                    row = dict(sample=samples, time=datetime.now(timezone.utc).isoformat(), service_pid=service['pid'],
                        elapsed_seconds=time.monotonic() - started, end_to_end_ms=(time.monotonic() - now) * 1000,
                        failure=failure, successes=successes, failures=failures, provider_boundary='fake')
                    row['service_resources'] = resource_sample(service['pid'])
                    row['disk_free_bytes'] = shutil.disk_usage(root).free
                    row['managed_data_bytes'] = sum(path.stat().st_size for path in (root / 'service-data').rglob('*') if path.is_file())
                    try:
                        with sqlite3.connect(root / 'service-data/workbench.sqlite3', timeout=10) as connection:
                            row['pending_tasks'] = connection.execute("SELECT COUNT(*) FROM task_runs WHERE state NOT IN ('PUBLISHED','FAILED','CANCELLED')").fetchone()[0]
                            row['persisted_tasks'] = connection.execute('SELECT COUNT(*) FROM task_runs').fetchone()[0]
                    except sqlite3.Error:
                        row['pending_tasks'] = row['persisted_tasks'] = None
                        row['queue_observation_error'] = 'database_metrics_unavailable'
                    output.write(json.dumps(row) + '\n')
                    output.flush()
                    write_json(root / 'checkpoint.json', row)
                    remaining = min(args.interval_seconds - (time.monotonic() - now), requested - (time.monotonic() - started))
                    if remaining > 0:
                        time.sleep(remaining)
                completed = True
        finally:
            elapsed = time.monotonic() - started
            write_json(root / 'summary.json', dict(build_id=build, seed=args.seed, elapsed_seconds=elapsed,
                requested_seconds=requested, full_24h=completed and requested == 86400 and elapsed >= 86400,
                completed=completed, successes=successes, failures=failures, samples=samples,
                provider_boundary='fake', real_provider_verified=False, resource_matrix_complete=False))
    summary = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
    summary['process_cleaned'] = service['cleaned']
    summary['raw_samples_sha256'] = hashlib.sha256((root / 'samples.jsonl').read_bytes()).hexdigest()
    write_json(root / 'summary.json', summary)
    print(json.dumps(summary))
    return 0 if completed and failures == 0 and service['cleaned'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
