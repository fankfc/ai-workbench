"""No installation: start and stop the extracted package's actual backend."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def tree_hash(directory):
    digest = hashlib.sha256()
    for path in sorted(directory.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def probe():
    resources = ROOT / 'dist/windows/win-unpacked/resources'
    python = resources / 'python/python.exe'
    data = ROOT / 'artifacts/qa/D052' / ('packaged-smoke-' + uuid.uuid4().hex)
    data.mkdir(parents=True)
    token, instance = uuid.uuid4().hex, uuid.uuid4().hex
    env = {key: os.environ[key] for key in ('PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA') if key in os.environ}
    env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1', WORKBENCH_API_TOKEN=token, WORKBENCH_INSTANCE_ID=instance)
    command = [str(python), '-m', 'app.api.launcher', '--host', '127.0.0.1', '--port', '0', '--data-root', str(data), '--provider-mode', 'real']
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    process = subprocess.Popen(command, cwd=resources / 'services/orchestrator', env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=creationflags)
    lines = queue.Queue()
    reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
    reader.start()
    report = {'source_kind': 'deterministic_packaged_smoke', 'installation_executed': False,
              'signed_candidate_qualified': False, 'real_provider_calls': 0,
              'backend_started': False, 'checkpoint_saved': False, 'process_cleanup_confirmed': False,
              'runtime_sha256': hashlib.sha256(python.read_bytes()).hexdigest()}
    report['packaged_service_tree_sha256'] = tree_hash(resources / 'services/orchestrator/app')
    report['workspace_service_tree_sha256'] = tree_hash(ROOT / 'services/orchestrator/app')
    if report['packaged_service_tree_sha256'] != report['workspace_service_tree_sha256']:
        process.terminate()
        process.wait(timeout=10)
        raise ValueError('PACKAGED_SERVICE_SOURCE_CHANGED_REBUILD_REQUIRED')
    try:
        ready = json.loads(lines.get(timeout=25))
        if ready.get('kind') != 'backend.ready' or ready.get('pid') != process.pid or ready.get('instance_id') != instance:
            raise ValueError('PACKAGED_HANDSHAKE_MISMATCH')
        base = 'http://127.0.0.1:' + str(ready['port'])
        request = urllib.request.Request(base + '/v1/health', headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=10) as response:
            health = json.load(response)
        if health.get('pid') != process.pid or health.get('instance_id') != instance or health.get('provider_mode') != 'real':
            raise ValueError('PACKAGED_HEALTH_MISMATCH')
        report.update(backend_started=True, service_pid=process.pid, protocol_version=health['protocol_version'])
        request = urllib.request.Request(base + '/v1/settings', headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=10) as response:
            settings = json.load(response)
        connections = settings['connections']
        report['available_connections'] = sum(row['available'] is True for row in connections)
        report['connection_states'] = [{key: row[key] for key in ('family', 'identity_status', 'available', 'enabled')} for row in connections]
        if report['available_connections'] != 0 or any(row['identity_status'] != 'unknown' for row in connections):
            raise ValueError('UNCONFIGURED_PACKAGED_CONNECTIONS_NOT_PENDING')
        checkpoint = urllib.request.Request(base + '/v1/checkpoint', method='POST', data=b'', headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(checkpoint, timeout=10) as response:
            report['checkpoint_saved'] = json.load(response).get('saved') is True
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        reader.join(timeout=2)
        report['process_cleanup_confirmed'] = process.poll() is not None
        process.stdout.close()
        process.stderr.close()
        (data / 'packaged-runtime-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        (ROOT / 'artifacts/qa/D052/packaged-runtime-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    print(json.dumps(probe()))
