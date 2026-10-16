"""release_decision: actual local probe or read-only release evidence audit."""
from pathlib import Path
from app.release.audit import release_decision
from .release_common import REPO, STRING_LIST, options as schema_options, result, save

OPTIONS_SCHEMA = schema_options({'evidence_manifest': {'type':'string'}, 'functional_checks': {'type':'boolean'}, 'optimization_eligible': {'type':'boolean'}})
RESULT_SCHEMA = result({'functional_release': {'type': 'boolean'}, 'optimization_goal_met': {'type': 'boolean'}, 'blocked_reasons': STRING_LIST, 'qualified_scope': STRING_LIST})

def run(root: Path, options: dict) -> dict:
    value = release_decision(REPO, options)
    return save(root, 'release_decision', value)

