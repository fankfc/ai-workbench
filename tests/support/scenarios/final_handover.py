"""final_handover: actual local probe or read-only release evidence audit."""
from pathlib import Path
from app.release.audit import final_handover
from .release_common import REPO, STRING_LIST, options as schema_options, result, save

OPTIONS_SCHEMA = schema_options({'evidence_manifest': {'type':'string'}, 'functional_complete': {'type':'boolean'}, 'optimization_complete': {'type':'boolean'}})
RESULT_SCHEMA = result({'files_complete': {'type': 'boolean'}, 'evidence_valid': {'type': 'boolean'}, 'functional_complete': {'type': 'boolean'}, 'optimization_complete': {'type': 'boolean'}, 'overall_goal_complete': {'type': 'boolean'}, 'open_items': STRING_LIST})

def run(root: Path, options: dict) -> dict:
    value = final_handover(REPO, options)
    return save(root, 'final_handover', value)

