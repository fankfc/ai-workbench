"""Start the real authenticated service with a test-only external provider."""
from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import sys
import time
import urllib.request

from support.manifest import write_json
from app.runtime.processes import ProcessManager


@contextmanager
def local_service(root):
    root = Path(root)
    token = secrets.token_hex(24)
    token_file = root / '.service-token'
    token_file.write_text(token, encoding='utf-8')
    manager = ProcessManager(root / 'service-leases.sqlite3')
    command = [sys.executable, str(Path(__file__).with_name('service_worker.py')), str(root)]
    process = manager.start('acceptance-service', secrets.token_hex(16), command, root)
    state = dict(pid=None, launcher_pid=process.pid, cleaned=False)
    try:
        deadline = time.monotonic() + 20
        while b'\n' not in process.stdout:
            if process.local_state != 'running' or time.monotonic() >= deadline:
                raise RuntimeError('SERVICE_START_FAILED')
            time.sleep(.01)
        ready = json.loads(process.stdout.splitlines()[0])
        if ready.get('kind') != 'backend.ready' or not isinstance(ready.get('pid'), int):
            raise RuntimeError('SERVICE_HANDSHAKE_INVALID')
        state['pid'] = ready['pid']
        base = 'http://127.0.0.1:' + str(ready['port'])
        def request(path, data=None, method=None, authorized=True, origin=None):
            headers = {'Content-Type': 'application/json'}
            if authorized:
                headers['Authorization'] = 'Bearer ' + token
            if origin:
                headers['Origin'] = origin
            raw = json.dumps(data, ensure_ascii=False).encode('utf-8') if data is not None else None
            req = urllib.request.Request(base + path, data=raw, headers=headers, method=method)
            return urllib.request.urlopen(req, timeout=15)
        deadline = time.monotonic() + 20
        while True:
            try:
                with request('/v1/health') as response:
                    health = json.load(response)
                if health['pid'] != ready['pid'] or health['instance_id'] != ready['instance_id']:
                    raise RuntimeError('SERVICE_IDENTITY_MISMATCH')
                break
            except (OSError, ValueError):
                if process.local_state != 'running' or time.monotonic() >= deadline:
                    raise RuntimeError('SERVICE_HEALTH_TIMEOUT')
                time.sleep(.02)
        write_json(root / 'service-identity.json', health)
        state.update(request=request, ready=ready)
        yield state
    finally:
        manager.close()
        token_file.unlink(missing_ok=True)
        (root / 'service.stderr.log').write_bytes(process.stderr)
        state['cleaned'] = process.local_state != 'running' and manager.resource_snapshot()['open_handles'] == 0
        write_json(root / 'service-teardown.json', dict(pid=state['pid'], launcher_pid=process.pid,
                   cleaned=state['cleaned'], returncode=process.returncode))
