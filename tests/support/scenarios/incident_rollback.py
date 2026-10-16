"""incident_rollback: actual local probe or read-only release evidence audit."""
from pathlib import Path
from app.operations.drills import incident_rollback
from .release_common import REPO, STRING_LIST, options as schema_options, result, save

OPTIONS_SCHEMA = schema_options({'fault': {'type':'string', 'enum':['critical_translation_after_model_change']}})
RESULT_SCHEMA = result({'optimization_disabled': {'type': 'boolean'}, 'affected_publication_stopped': {'type': 'boolean'}, 'provider_switched': {'type': 'boolean'}, 'evidence_preserved': {'type': 'boolean'}, 'resume_requires_requalification': {'type': 'boolean'}})

def run(root: Path, options: dict) -> dict:
    value = incident_rollback(root)
    return save(root, 'incident_rollback', value)

