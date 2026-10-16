"""Byte-level acceptance evidence, with scoped paths and explicit provenance."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app.runtime.workspace import _reject_reparse


def source_build_id():
    repo = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    files = []
    for directory in ('services/orchestrator/app', 'apps/desktop/src', 'packages/contracts'):
        files.extend(p for p in (repo / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    files.extend(repo / name for name in ('package.json', 'package-lock.json', 'apps/desktop/package.json',
        'services/orchestrator/pyproject.toml', 'services/orchestrator/uv.lock', 'apps/desktop/electron-builder.yml')
        if (repo / name).is_file())
    for path in sorted(files):
        digest.update(path.relative_to(repo).as_posix().encode('utf-8'))
        digest.update(bytes.fromhex(hashlib.sha256(path.read_bytes()).hexdigest()))
    return digest.hexdigest()


def verification_source_id():
    """Also freeze the test instruments, fixtures and executable QA scripts."""
    repo = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256(source_build_id().encode())
    for directory in ('tests', 'scripts', 'release', '.github'):
        for path in sorted((repo / directory).rglob('*')):
            if (path.is_file() and '__pycache__' not in path.parts and 'staging' not in path.parts
                    and (directory in ('tests', 'scripts') or path.suffix in ('.py', '.ps1', '.yml', '.yaml'))):
                digest.update(path.relative_to(repo).as_posix().encode('utf-8'))
                digest.update(bytes.fromhex(hashlib.sha256(path.read_bytes()).hexdigest()))
    return digest.hexdigest()


def _scoped(root, relative):
    parts = PurePosixPath(relative)
    if not isinstance(relative, str) or '\\' in relative or ':' in relative or not relative or parts.is_absolute() or '..' in parts.parts:
        raise ValueError('EVIDENCE_PATH_OUTSIDE_ROOT')
    path = Path(root).joinpath(*parts.parts)
    _reject_reparse(path)
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('EVIDENCE_PATH_OUTSIDE_ROOT')
    if path.exists() and path.stat().st_nlink > 1:
        raise ValueError('EVIDENCE_HARDLINK_DENIED')
    return path


def create_manifest(root, files, *, build_id=None, run_id=None, provider_boundary='fake'):
    root = Path(root).resolve()
    entries = []
    for value in files:
        path = Path(value).absolute()
        relative = path.relative_to(root).as_posix()
        checked = _scoped(root, relative)
        data = checked.read_bytes()
        entries.append(dict(path=relative, size=len(data), sha256=hashlib.sha256(data).hexdigest()))
    return dict(version='1.0', build_id=build_id or source_build_id(), run_id=run_id,
                created_at=datetime.now(timezone.utc).isoformat(), seed=4317, encoding='UTF-8',
                provider_boundary=provider_boundary, files=entries)


def validate_manifest(root, manifest):
    issues = []
    entries = manifest.get('files') if isinstance(manifest, dict) else None
    if not entries or not isinstance(entries, list):
        return dict(valid=False, issues=['EVIDENCE_FILES_MISSING'])
    paths = set()
    for entry in entries:
        try:
            relative = entry['path']
            if relative in paths:
                raise ValueError('EVIDENCE_DUPLICATE_PATH')
            paths.add(relative)
            data = _scoped(root, relative).read_bytes()
            if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError('EVIDENCE_BYTES_CHANGED')
        except (OSError, ValueError, TypeError, KeyError) as error:
            issues.append(dict(path=entry.get('path') if isinstance(entry, dict) else None, reason=type(error).__name__))
    return dict(valid=not issues, issues=issues)


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
