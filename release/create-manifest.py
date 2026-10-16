"""Create an auditable candidate ledger; exit 2 for unmet release gates."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/orchestrator'))
from app.release.audit import MANDATORY, audit_manifest
from app.release.evidence import load_json, sha256
from app.release.sbom import inventory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', default='dist/windows/AIBroker-Setup.exe')
    parser.add_argument('--evidence', default='release/candidate-evidence.json')
    parser.add_argument('--output', default='artifacts/qa/D054/release-manifest.json')
    parser.add_argument('--sbom', default='artifacts/qa/D054/sbom.json')
    parser.add_argument('--ledger-output')
    args = parser.parse_args()
    sbom_path = ROOT / args.sbom
    sbom_path.parent.mkdir(parents=True, exist_ok=True)
    sbom_path.write_text(json.dumps(inventory(ROOT), indent=2, ensure_ascii=False), encoding='utf-8')
    evidence_path = ROOT / args.evidence
    source = load_json(evidence_path) if evidence_path.is_file() else {}
    candidate = ROOT / args.candidate
    git = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    manifest = dict(schema_version='1.0', candidate={'path': args.candidate, 'sha256': sha256(candidate)} if candidate.is_file() else None,
                    commit=git.stdout.strip() if git.returncode == 0 else None,
                    dependency_locks={name: {'path': name, 'sha256': sha256(ROOT / name)} for name in ('package-lock.json', 'services/orchestrator/uv.lock')},
                    sbom={'path': args.sbom, 'sha256': sha256(sbom_path)}, compatible_schema=4,
                    evidence={name: source.get('evidence', {}).get(name, {'status': 'missing', 'report': None}) for name in MANDATORY + ('authenticode', 'release_approval', 'optimization_qualification', 'final_handover')},
                    note='Lock inventory is not a verified packaged runtime/tool/license SBOM. Missing evidence is a blocking result.')
    result = audit_manifest(ROOT, manifest)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    output.with_name(output.stem + '-audit.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    if args.ledger_output:
        ledger = ROOT / args.ledger_output
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['valid'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
