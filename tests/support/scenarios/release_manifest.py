"""release_manifest: actual local probe or read-only release evidence audit."""
from pathlib import Path
from app.release.audit import audit_manifest, _manifest
from .release_common import REPO, STRING_LIST, options as schema_options, result, save

OPTIONS_SCHEMA = schema_options({'evidence_manifest': {'type':'string'}, 'fault': {'type':'string', 'enum':['skipped_security_test','missing_sbom','candidate_tamper','old_build_evidence']}})
RESULT_SCHEMA = result({'valid': {'type': 'boolean'}, 'missing_evidence': STRING_LIST, 'skipped_mandatory': STRING_LIST, 'artifact_hash_matches': {'type': 'boolean'}})

def run(root: Path, options: dict) -> dict:
    value = audit_manifest(REPO, _manifest(REPO, options))
    return save(root, 'release_manifest', value)

