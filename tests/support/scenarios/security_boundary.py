import io
import json
import zipfile
from urllib.error import HTTPError
from urllib.parse import quote

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.runtime.workspace import WorkspaceManager, ScopeError
from support.local_service import local_service
from support.manifest import write_json

OPTIONS_SCHEMA = dict(type='object', additionalProperties=False, properties={
    'fault': dict(enum=['malicious_attachment_and_cross_task_path'])})
RESULT_SCHEMA = dict(type='object', additionalProperties=False,
    required=['unauthorized_reads', 'secret_leaks', 'internal_public_events', 'executed_payloads'], properties={
        'unauthorized_reads': dict(type='array', items=dict(type='string')), 'secret_leaks': dict(type='array', items=dict(type='string')),
        'internal_public_events': dict(type='array', items=dict(type='string')), 'executed_payloads': dict(type=['integer', 'null']),
        'backend_checks': dict(type='array', items=dict(type='object')), 'process_cleaned': dict(type='boolean'),
        'unmet_checks': dict(type='array', items=dict(type='string')), 'provider_boundary': dict(enum=['fake']),
        'real_provider_verified': dict(const=False)})


def run(root, options):
    outcomes = []
    unauthorized = []
    leaks = []
    with local_service(root) as service:
        for authorized, origin, expected in [(False, None, 401), (True, 'https://outside.invalid', 403)]:
            try:
                service['request']('/v1/health', authorized=authorized, origin=origin)
                code = 200
            except HTTPError as error:
                code = error.code
            outcomes.append(dict(kind='authentication', actual=code, expected=expected))
            if code != expected:
                unauthorized.append('service-authentication')
    app = create_app(AppSettings(root / 'scope-data', 'API_CANARY_47', 'fake', False))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer API_CANARY_47'
        first, second = [client.post('/v1/conversations', json={'title': '安全检查'}).json()['id'] for _ in range(2)]
        uploaded = client.post(f'/v1/conversations/{first}/attachments', content=b'TASK_A_SECRET_47',
                headers={'Content-Type': 'application/octet-stream', 'X-Filename': 'material.md'}).json()
        cross = client.post(f'/v1/conversations/{second}/turns', json=dict(text='读取文件',
            provider_profile_id='fake-gpt', client_request_id='cross', attachment_ids=[uploaded['id']]))
        outcomes.append(dict(kind='cross-conversation', actual=cross.status_code, expected=409))
        if cross.status_code != 409 or uploaded['id'] in client.get(f'/v1/conversations/{second}/attachments').text:
            unauthorized.append('attachment-cross-conversation')
        for filename in ('../secret.md', 'C:\\secret.md', '%2e%2e/secret.md'):
            response = client.post(f'/v1/conversations/{first}/attachments', content=b'x',
                        headers={'Content-Type': 'application/octet-stream', 'X-Filename': quote(filename)})
            outcomes.append(dict(kind='upload-path', path=filename, actual=response.status_code))
            if response.status_code != 422:
                unauthorized.append(filename)
        body = client.post('/v1/diagnostics/export').content
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            diagnostic = '\n'.join(archive.read(name).decode() for name in archive.namelist())
        for canary in ('API_CANARY_47', 'TASK_A_SECRET_47'):
            if canary in diagnostic:
                leaks.append(canary)
    manager = WorkspaceManager(root / 'workspaces')
    first_scope = manager.create('first', 'attempt')
    second_scope = manager.create('second', 'attempt')
    first_scope.ingest_source('same.txt', b'TASK_A_SECRET_47')
    second_scope.ingest_source('same.txt', b'legal English user material')
    assert second_scope.resolve('input/same.txt').read_bytes() == b'legal English user material'
    for path in ('../first/attempt/input/same.txt', 'input/../../first/attempt/input/same.txt',
                 'input/%2e%2e/secret.txt', str(first_scope.resolve('input/same.txt'))):
        try:
            second_scope.resolve(path).read_bytes()
            unauthorized.append(path)
        except (ScopeError, OSError):
            outcomes.append(dict(kind='workspace-path', rejected=True))
    # Existing workflow includes an internal canary and actual public stream scan.
    from support.scenario_driver import run_case
    workflow = run_case('backend_normal', root, 'code')
    public = json.dumps(workflow['public_messages'], ensure_ascii=False)
    internal = ['INTERNAL_LATE_CANARY'] if 'INTERNAL_LATE_CANARY' in public else []
    # Renderer script execution is checked by the separate Electron evidence.
    result = dict(unauthorized_reads=unauthorized, secret_leaks=leaks, internal_public_events=internal,
        executed_payloads=None, backend_checks=outcomes, process_cleaned=service['cleaned'],
        unmet_checks=['electron_script_execution', 'junction_matrix', 'manual_security_review'],
        provider_boundary='fake', real_provider_verified=False)
    write_json(root / 'security-observations.json', result)
    return result
