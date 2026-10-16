"""Explicit metadata-only connector probe. No inference, auth/config reads or UI."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from app.providers.codex_protocol import CodexProtocolClient
from app.providers.native_rpc import NativeRpcError
from app.providers.zcode_protocol import ZCodeProtocolClient, ZCodeProtocolError

ROOT = Path(__file__).resolve().parents[1]


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["codex", "zcode", "all"], default="codex")
    parser.add_argument("--codex-executable")
    parser.add_argument("--cwd", type=Path, default=ROOT / ".tools/native-connection-probe")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/acceptance/part-one-closeout/gpt-managed-metadata.json")
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--max-output-bytes", type=int, default=65536)
    return parser


def main(arguments=None):
    args = build_parser().parse_args(arguments)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "provider": args.provider,
        "mode": "metadata_only", "production_enabled": False, "model_identity_verified": False,
        "model_turn_submissions": 0, "providers": {}}
    selected = ('codex', 'zcode') if args.provider == 'all' else (args.provider,)
    for name in selected:
        current = {"protocol_probe_completed": False, "production_enabled": False}
        try:
            args.cwd.mkdir(parents=True, exist_ok=True)
            if name == 'codex':
                entry = json.loads((ROOT / "docs/acceptance/D006/supported-entry.json").read_text(encoding="utf-8"))
                executable = args.codex_executable or entry['executable']
                connector = CodexProtocolClient([executable, 'app-server', '--listen', 'stdio://'], args.cwd,
                    timeout_seconds=args.timeout_seconds, max_output_bytes=args.max_output_bytes)
                metadata = connector.metadata()
            else:
                old = os.environ.get('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE')
                os.environ['ZCODE_BUILTIN_PROVIDER_CONFIG_FILE'] = 'D:/zcode/resources/config/provider/zcode-builtin.json'
                try:
                    connector = ZCodeProtocolClient(ZCodeProtocolClient.fixed_command(args.cwd), args.cwd,
                        timeout_seconds=args.timeout_seconds, max_output_bytes=args.max_output_bytes)
                    metadata = connector.probe()
                finally:
                    if old is None:
                        os.environ.pop('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE', None)
                    else:
                        os.environ['ZCODE_BUILTIN_PROVIDER_CONFIG_FILE'] = old
            current['metadata'] = metadata
            cleanup = metadata.get('cleanup', {})
            current['protocol_probe_completed'] = (metadata.get('metadata_status', 'observed') == 'observed'
                and metadata.get('model_turn_starts') == 0 and cleanup.get('cleanup_complete') is True
                and all(cleanup.get(key) == 0 for key in ('running', 'open_handles', 'temp_dirs')))
            if not current['protocol_probe_completed']:
                current['reason_code'] = metadata.get('reason_code', 'METADATA_PROBE_INCOMPLETE')
        except Exception as error:
            current['reason_code'] = error.reason_code if isinstance(error, (NativeRpcError, ZCodeProtocolError)) else 'METADATA_PROBE_FAILED'
            if isinstance(error, NativeRpcError) and type(error.error_code) is int:
                current['server_error_code'] = error.error_code
            if isinstance(getattr(error, 'metadata_report', None), dict):
                current['metadata'] = error.metadata_report
        report['providers'][name] = current
    report['protocol_probe_completed'] = all(item['protocol_probe_completed'] for item in report['providers'].values())
    exit_code = 0 if report['protocol_probe_completed'] else 1
    if len(selected) == 1:
        report.update(report['providers'][selected[0]])
    paths = [Path(__file__).resolve(), ROOT / "services/orchestrator/app/providers/native_rpc.py",
        ROOT / "services/orchestrator/app/providers/native_rpc_worker.py", ROOT / "services/orchestrator/app/providers/codex_protocol.py",
        ROOT / "services/orchestrator/app/providers/zcode_protocol.py"]
    report["source_sha256"] = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    report["exit_code"] = exit_code
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
