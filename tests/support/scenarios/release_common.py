"""Schema and output helpers for release/operations scenario modules."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STRING_LIST = {'type': 'array', 'items': {'type': 'string'}}
COMMON = {'evidence_kind': {'type': 'string', 'enum': ['audit', 'deterministic_product_probe']},
          'blocked_reasons': STRING_LIST}

def options(properties):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties}

def result(properties):
    properties = {**properties, **COMMON}
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties)}

def save(root, name, value):
    root.mkdir(parents=True, exist_ok=True)
    (root / (name + '.json')).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    return value

