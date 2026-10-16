"""Offline byte/link check only; does not confer acceptance or signing trust."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/orchestrator'))
from app.release.evidence import load_json, verify_file

if __name__ == '__main__':
    index = load_json(ROOT / 'release/offline-evidence-index.json')
    errors = list(index['missing'])
    for reference in index['files']:
        try:
            verify_file(ROOT, reference)
        except (ValueError, OSError) as error:
            errors.append(reference['path'] + ':' + str(error))
    print(json.dumps({'links_and_hashes_valid': not errors, 'files_checked': len(index['files']), 'errors': errors, 'release_qualified': False}))
    raise SystemExit(1 if errors else 0)
