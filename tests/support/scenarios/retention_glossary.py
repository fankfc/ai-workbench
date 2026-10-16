"""retention_glossary: actual local probe or read-only release evidence audit."""
from pathlib import Path
from app.operations.drills import retention_glossary
from .release_common import REPO, STRING_LIST, options as schema_options, result, save

OPTIONS_SCHEMA = schema_options({'fault': {'type':'string', 'enum':['expired_log_with_active_evidence']}})
RESULT_SCHEMA = result({'deleted_active_evidence': {'type': 'boolean'}, 'secret_leaks': STRING_LIST, 'cache_reused_after_glossary_change': {'type': 'boolean'}, 'history_preserved': {'type': 'boolean'}, 'cleanup_blocked': {'type': 'boolean'}})

def run(root: Path, options: dict) -> dict:
    value = retention_glossary(root)
    return save(root, 'retention_glossary', value)

