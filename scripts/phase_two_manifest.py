"""Record source identities in this unborn checkout without including user data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_files(scope='all'):
    files = set()
    folders=('services/orchestrator/app', 'tests', 'packages/contracts', 'scripts') if scope=='backend' else ('services/orchestrator/app', 'apps/desktop/src', 'tests', 'packages', 'scripts')
    for folder in folders:
        for path in (ROOT / folder).rglob('*'):
            if (path.is_file() and '__pycache__' not in path.parts
                    and path.suffix in ({'.py', '.sql', '.yaml', '.json', '.md', '.txt', '.csv', '.pdf', '.docx', '.png'} if scope=='backend' else {'.py', '.ts', '.tsx', '.mjs', '.css', '.html', '.sql', '.yaml', '.json', '.md', '.txt', '.csv', '.pdf', '.docx', '.png'})):
                files.add(path)
    names=('pytest.ini','.python-version','services/orchestrator/pyproject.toml','services/orchestrator/uv.lock')
    if scope=='all': names+=('package.json','package-lock.json','playwright.config.ts')
    for name in names:
        files.add(ROOT / name)
    return sorted(files)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--compare')
    parser.add_argument('--scope',choices=('backend','all'),default='all')
    args = parser.parse_args()
    rows = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_files(args.scope)}
    record = dict(recorded_at=datetime.now(timezone.utc).isoformat(), git_commit=None,
                  checkout='unborn codex/part1-foundation', scope=args.scope, files=rows,
                  source_sha256=hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest())
    if args.compare:
        before = json.loads(Path(args.compare).read_text(encoding='utf-8'))['files']
        record['changed_files'] = [name for name in sorted(set(before) | set(rows)) if before.get(name) != rows.get(name)]
        record['unchanged'] = not record['changed_files']
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in record.items() if key != 'files'}))
