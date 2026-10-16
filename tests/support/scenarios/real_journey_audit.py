"""real_journey_audit: actual local probe or read-only release evidence audit."""
from pathlib import Path
from app.release.audit import real_journey_audit
from .release_common import REPO, STRING_LIST, options as schema_options, result, save

OPTIONS_SCHEMA = schema_options({'evidence_manifest': {'type':'string'}, 'evidence_set': {'type':'string', 'enum':['candidate']}})
RESULT_SCHEMA = result({'domains_passed': STRING_LIST, 'provenance_valid': {'type': 'boolean'}, 'pairs_valid': {'type': 'boolean'}, 'model_identity_verified': {'type': 'boolean'}, 'all_required_entries_tested': {'type': 'boolean'}})

def run(root: Path, options: dict) -> dict:
    value = real_journey_audit(REPO, options)
    return save(root, 'real_journey_audit', value)

