"""Refresh truthful local no-go and offline handover indexes."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/orchestrator'))
from app.release.audit import REQUIRED_FILES, final_handover, release_decision, real_journey_audit, windows_install, signed_update
from app.release.evidence import sha256


def save(relative, value):
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    decision = release_decision(ROOT, {})
    handover = final_handover(ROOT, {})
    save('release/release-decision.json', decision)
    save('release/final-acceptance.json', handover)
    save('artifacts/qa/D052/installation-report.json', windows_install(ROOT, {}))
    save('artifacts/qa/D053/update-matrix.json', signed_update(ROOT, {}))
    save('artifacts/qa/D055/real-journeys/audit.json', real_journey_audit(ROOT, {}))
    names = list(REQUIRED_FILES) + ['release/final-handover.md', 'release/release-checklist.md', 'release/release-decision.json', 'release/final-acceptance.json',
        'release/candidate-evidence.json', 'artifacts/qa/D054/release-manifest.json', 'artifacts/qa/D054/sbom.json',
        'package-lock.json', 'services/orchestrator/uv.lock', 'release/staging/tool-inventory.json',
        'artifacts/qa/D052/authenticode.json', 'artifacts/qa/D052/packaged-runtime-report.json']
    from app.release.evidence import load_json
    candidate = load_json(ROOT / 'release/candidate-evidence.json').get('candidate')
    if candidate:
        names.append(candidate['path'])
    save('release/offline-evidence-index.json', {'schema_version': '1.0', 'release_qualified': False,
        'files': [{'path': name, 'sha256': sha256(ROOT / name)} for name in names if (ROOT / name).is_file()],
        'missing': [name for name in names if not (ROOT / name).is_file()]})
    print(json.dumps({'functional_release': decision['functional_release'], 'optimization_goal_met': decision['optimization_goal_met'],
                      'overall_goal_complete': handover['overall_goal_complete'], 'open_items': handover['open_items']}))
