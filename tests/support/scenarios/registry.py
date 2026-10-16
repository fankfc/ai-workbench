"""Explicit allowlist and JSON-schema validation at the CLI boundary."""
import importlib

from jsonschema import Draft202012Validator

NAMES = frozenset(('driver_contract', 'requirement_coverage', 'translation_corpus',
    'evaluation_protocol', 'usage_reconciliation', 'optimization_gate', 'security_boundary',
    'fault_matrix', 'gui_evidence', 'local_performance', 'backup_restore', 'windows_install',
    'signed_update', 'release_manifest', 'real_journey_audit', 'feedback_bundle',
    'release_decision', 'retention_glossary', 'incident_rollback', 'final_handover'))


def get_case(name):
    if name not in NAMES:
        raise ValueError('UNKNOWN_CASE')
    return importlib.import_module('support.scenarios.' + name)


def validate_options(module, options):
    Draft202012Validator(module.OPTIONS_SCHEMA).validate(options)


def invoke(module, root, options):
    result = module.run(root, options)
    Draft202012Validator(module.RESULT_SCHEMA).validate(result)
    return result
