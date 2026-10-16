"""feedback_bundle: actual local probe or read-only release evidence audit."""
from pathlib import Path
from app.operations.feedback import build_feedback
from .release_common import REPO, STRING_LIST, options as schema_options, result, save

OPTIONS_SCHEMA = schema_options({'include_content': {'type':'boolean'}, 'content_opt_in': {'type':'boolean'}})
RESULT_SCHEMA = result({'secret_leaks': STRING_LIST, 'contains_user_content': {'type': 'boolean'}, 'explicit_content_opt_in': {'type': 'boolean'}, 'reproducible_case': {'type': 'boolean'}})

def run(root: Path, options: dict) -> dict:
    value = build_feedback(root, include_content=options.get("include_content", False), content_opt_in=options.get("content_opt_in", False))
    return save(root, 'feedback_bundle', value)

