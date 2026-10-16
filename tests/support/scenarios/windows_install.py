"""windows_install: actual local probe or read-only release evidence audit."""
from pathlib import Path
from app.release.audit import windows_install
from .release_common import REPO, STRING_LIST, options as schema_options, result, save

OPTIONS_SCHEMA = schema_options({'evidence_manifest': {'type':'string'}, 'fixture': {'type':'string', 'enum':['signed_candidate']}})
RESULT_SCHEMA = result({'install_ok': {'type': 'boolean'}, 'publisher_valid': {'type': 'boolean'}, 'backend_started': {'type': 'boolean'}, 'user_files_preserved': {'type': 'boolean'}, 'taskbar_windows': {'type': 'integer'}})

def run(root: Path, options: dict) -> dict:
    value = windows_install(REPO, options)
    return save(root, 'windows_install', value)

