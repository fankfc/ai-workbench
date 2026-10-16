"""Stage a portable runtime from pinned local Python and locked production files.

Does not copy a virtualenv or execute provider/account tools. Staged hashes and
metadata license notices support an internal build; a release package still needs
an independent license/tool audit, signing, and clean-machine execution.
"""
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/orchestrator'))
from app.release.evidence import sha256


def stage(destination):
    destination = destination.resolve()
    if not destination.is_relative_to(ROOT / 'release') or destination == ROOT / 'release':
        raise ValueError('STAGING_DESTINATION_OUTSIDE_RELEASE')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('STAGING_MUST_BE_NEW_EMPTY_DIRECTORY')
    if sys.version_info[:3] != (3, 13, 0) or sys.platform != 'win32':
        raise ValueError('PINNED_WINDOWS_PYTHON_3_13_0_REQUIRED')
    destination.mkdir(parents=True, exist_ok=True)
    runtime = destination / 'python'
    runtime.mkdir()
    base = Path(sys.base_prefix)
    for path in [base / 'python.exe', base / 'LICENSE.txt', *sorted(base.glob('*.dll'))]:
        shutil.copy2(path, runtime / path.name)
    shutil.copytree(base / 'DLLs', runtime / 'DLLs', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(base / 'Lib', runtime / 'Lib', ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'ensurepip', 'tkinter'))
    lock = tomllib.loads((ROOT / 'services/orchestrator/uv.lock').read_text(encoding='utf-8'))
    packages = {package['name']: package for package in lock['package']}
    pending = [row['name'] for row in packages['ai-workbench-orchestrator']['dependencies']]
    selected = set()
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        selected.add(name)
        pending.extend(row['name'] for row in packages[name].get('dependencies', []))
    tools = []
    site = runtime / 'Lib/site-packages'
    site.mkdir()
    for name in sorted(selected):
        distribution = importlib.metadata.distribution(name)
        if distribution.version != packages[name]['version']:
            raise ValueError('INSTALLED_PACKAGE_DIFFERS_FROM_LOCK:' + name)
        license_text = distribution.metadata.get('License-Expression') or distribution.metadata.get('License')
        notices = []
        for relative in distribution.files or []:
            # Console wrappers in ../Scripts are not needed by the service.
            if '..' in relative.parts or str(relative).endswith(('.pyc', '.pyo')):
                continue
            source = Path(distribution.locate_file(relative)).resolve()
            if not source.is_file() or source.is_symlink():
                raise ValueError('PACKAGE_FILE_UNSAFE:' + str(relative))
            target = site / relative
            if not target.resolve().is_relative_to(site.resolve()):
                raise ValueError('PACKAGE_PATH_ESCAPE')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if any(token in str(relative).lower() for token in ('license', 'copying', 'notice')):
                notices.append({'path': target.relative_to(destination).as_posix(), 'sha256': sha256(target)})
        tools.append({'name': name, 'version': distribution.version,
                      'license_metadata': license_text or 'unverified', 'license_notices': notices})
    smoke = subprocess.run([str(runtime / 'python.exe'), '-c',
        'import sys,fastapi,pydantic,uvicorn,markdown_it,docx,reportlab,pymupdf; '
        'assert sys.version_info[:3]==(3,13,0); print("portable-runtime-imports-ok")'],
        cwd=str(runtime), capture_output=True, text=True, timeout=30, check=False)
    (destination / 'runtime-smoke.txt').write_text(smoke.stdout + smoke.stderr, encoding='utf-8')
    if smoke.returncode != 0:
        raise ValueError('STAGED_RUNTIME_IMPORT_CHECK_FAILED')
    files = [{'path': path.relative_to(destination).as_posix(), 'sha256': sha256(path)}
             for path in sorted(runtime.rglob('*')) if path.is_file() and '__pycache__' not in path.parts]
    value = dict(status='internal_hash_inventory', runtime_sha256=sha256(runtime / 'python.exe'),
                 python_version='3.13.0', dependency_lock_sha256=sha256(ROOT / 'services/orchestrator/uv.lock'),
                 tools=tools, files=files, verified_imports=smoke.returncode == 0,
                 capabilities={'markdown': 'import_smoke_verified', 'docx': 'import_smoke_verified', 'pdf': 'import_smoke_verified', 'ocr': 'unavailable_not_packaged'},
                 release_blockers=['independent_packaged_license_audit', 'clean_machine_format_execution', 'trusted_signature'])
    (destination / 'tool-inventory.json').write_text(json.dumps(value, indent=2), encoding='utf-8')
    return {'status': value['status'], 'staged_files': len(files), 'production_packages': len(tools), 'smoke_exit_code': smoke.returncode}


if __name__ == '__main__':
    try:
        print(json.dumps(stage(ROOT / 'release/staging')))
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'status': 'blocked', 'reason': str(error)}))
        raise SystemExit(2)
