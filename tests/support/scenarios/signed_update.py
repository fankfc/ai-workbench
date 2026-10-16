"""signed_update: actual local probe or read-only release evidence audit."""
from pathlib import Path
from app.release.audit import signed_update
from .release_common import REPO, STRING_LIST, options as schema_options, result, save

OPTIONS_SCHEMA = schema_options({'evidence_manifest': {'type':'string'}, 'fault': {'type':'string', 'enum':['invalid_publisher','invalid_signature','tampered_package','replayed_manifest','version_downgrade','health_failure']}})
RESULT_SCHEMA = result({'update_state': {'type': 'string'}, 'active_version': {'type': 'string'}, 'previous_version': {'type': 'string'}, 'restored_schema': {'type': 'integer'}, 'expected_schema': {'type': 'integer'}})

def run(root: Path, options: dict) -> dict:
    value = signed_update(REPO, options)
    return save(root, 'signed_update', value)

