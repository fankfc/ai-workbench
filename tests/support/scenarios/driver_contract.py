import json
import sqlite3
import time
from uuid import uuid4

from support.local_service import local_service
from support.manifest import create_manifest, validate_manifest, write_json

OPTIONS_SCHEMA = dict(type='object', additionalProperties=False, properties={
    'fault': dict(enum=['deleted_evidence'])})
RESULT_SCHEMA = dict(type='object', additionalProperties=False, required=['exit_code', 'service_pid', 'evidence_files',
    'manifest_valid', 'root_isolated', 'process_cleaned', 'run_id', 'task_state', 'answer_count'], properties={
    'exit_code': dict(type='integer'), 'service_pid': dict(type='integer', minimum=1),
    'evidence_files': dict(type='array', items=dict(type='string')),
    'manifest_valid': dict(type='boolean'), 'root_isolated': dict(type='boolean'),
    'process_cleaned': dict(type='boolean'), 'run_id': dict(type='string'),
    'task_state': dict(type='string'), 'answer_count': dict(type='integer', minimum=0),
    'provider_boundary': dict(enum=['fake']), 'real_provider_verified': dict(const=False)})


def run(root, options):
    with local_service(root) as service:
        request = service['request']
        with request('/v1/conversations', {'title': '验收隔离会话'}) as response:
            cid = json.load(response)['id']
        with request('/v1/conversations/' + cid + '/turns', dict(text='验收装置问题',
                     provider_profile_id='fake-gpt', client_request_id=uuid4().hex)) as response:
            submitted = json.load(response)
        metadata = json.loads((root / '.qa-run.json').read_text(encoding='utf-8'))
        metadata['task_id'] = submitted['task_id']
        write_json(root / '.qa-run.json', metadata)
        deadline = time.monotonic() + 20
        while True:
            with request('/v1/tasks/' + submitted['task_id']) as response:
                task = json.load(response)
            if task['status'] in {'completed', 'failed', 'blocked'}:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('TASK_TIMEOUT')
            time.sleep(.02)
        with request('/v1/conversations/' + cid + '/messages') as response:
            messages = json.load(response)
        write_json(root / 'task.json', task)
        write_json(root / 'public-messages.json', messages)
        with sqlite3.connect(root / 'service-data' / 'workbench.sqlite3') as connection:
            state = connection.execute('SELECT state FROM task_runs WHERE task_id=?', (submitted['task_id'],)).fetchone()[0]
    files = [root / name for name in ('task.json', 'public-messages.json', 'service-identity.json', 'service-teardown.json')]
    manifest = create_manifest(root, files)
    if options.get('fault') == 'deleted_evidence':
        (root / 'task.json').unlink()
    write_json(root / 'evidence-manifest.json', manifest)
    metadata = json.loads((root / '.qa-run.json').read_text(encoding='utf-8'))
    return dict(exit_code=0, service_pid=service['pid'], evidence_files=[p.name for p in files],
                manifest_valid=validate_manifest(root, manifest)['valid'], root_isolated=True,
                process_cleaned=service['cleaned'], run_id=metadata['run_id'], task_state=state,
                answer_count=sum(m['kind'] == 'answer.published' for m in messages['items']),
                provider_boundary='fake', real_provider_verified=False)
