"""Probe CLI orchestration uses projected connector records, never inference."""
import importlib.util
import json
import os
from pathlib import Path


def load_script():
    path = Path(__file__).resolve().parents[2] / 'scripts/probe_native_connections.py'
    spec = importlib.util.spec_from_file_location('native_connection_probe_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_explicit_probe_can_check_both_native_metadata_connectors(tmp_path, monkeypatch):
    module = load_script()
    seen = []

    class Codex:
        def __init__(self, command, cwd, **bounds):
            seen.append(('codex', command))

        def metadata(self):
            return {'identity_status': 'unknown', 'actual_model_id': None,
                    'production_enabled': False, 'model_turn_starts': 0,
                    'cleanup': {'cleanup_complete': True, 'running': 0, 'open_handles': 0, 'temp_dirs': 0}}

    class ZCode:
        @staticmethod
        def fixed_command(cwd):
            return ['fixture-node.exe', 'fixture-zcode.cjs', 'app-server', '--cwd', str(cwd), '--no-color']

        def __init__(self, command, cwd, **bounds):
            seen.append(('zcode', command))
            assert os.environ.get('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE') == 'D:/zcode/resources/config/provider/zcode-builtin.json'

        def probe(self):
            return {'metadata_status': 'observed', 'reason_code': 'HOST_ACCOUNT_CONTEXT_REQUIRED',
                    'identity_status': 'unknown', 'actual_model_id': None, 'available_models': [],
                    'production_enabled': False, 'model_turn_starts': 0,
                    'cleanup': {'cleanup_complete': True, 'running': 0, 'open_handles': 0, 'temp_dirs': 0}}

    monkeypatch.setattr(module, 'CodexProtocolClient', Codex)
    monkeypatch.setattr(module, 'ZCodeProtocolClient', ZCode, raising=False)
    monkeypatch.setenv('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE', 'keep-existing-nonsecret-path')
    output = tmp_path / 'combined.json'
    try:
        code = module.main(['--provider', 'all', '--cwd', str(tmp_path / 'work'), '--output', str(output)])
    except SystemExit:
        code = None
    assert [name for name, command in seen] == ['codex', 'zcode'], 'Both independent native metadata routes must be checked'
    assert code == 0
    report = json.loads(output.read_text(encoding='utf-8'))
    assert set(report['providers']) == {'codex', 'zcode'}
    assert report['production_enabled'] is False and report['model_identity_verified'] is False
    assert report['model_turn_submissions'] == 0
    assert os.environ['ZCODE_BUILTIN_PROVIDER_CONFIG_FILE'] == 'keep-existing-nonsecret-path'


def test_failed_connector_still_exports_fixed_failure_without_success(tmp_path, monkeypatch):
    module = load_script()

    class Failed:
        def __init__(self, *args, **kwargs):
            raise module.NativeRpcError('CODEX_OFFICIAL_ENTRY_MISMATCH')

    monkeypatch.setattr(module, 'CodexProtocolClient', Failed)
    output = tmp_path / 'failed.json'
    assert module.main(['--cwd', str(tmp_path / 'work'), '--output', str(output)]) == 1
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['protocol_probe_completed'] is False
    assert report['reason_code'] == 'CODEX_OFFICIAL_ENTRY_MISMATCH'
    assert report['production_enabled'] is False


def test_relative_script_entry_keeps_the_completed_probe_receipt(tmp_path, monkeypatch):
    module = load_script()

    class Completed:
        def __init__(self, *args, **kwargs):
            pass

        def metadata(self):
            return {'model_turn_starts': 0, 'cleanup': {'cleanup_complete': True,
                    'running': 0, 'open_handles': 0, 'temp_dirs': 0}}

    monkeypatch.setattr(module, 'CodexProtocolClient', Completed)
    monkeypatch.setattr(module, '__file__', 'scripts/probe_native_connections.py')
    output = tmp_path / 'relative.json'
    try:
        result = module.main(['--cwd', str(tmp_path / 'work'), '--output', str(output)])
    except ValueError:
        result = None
    assert result == 0 and output.is_file(), 'A relative script invocation must preserve the completed diagnostic'
