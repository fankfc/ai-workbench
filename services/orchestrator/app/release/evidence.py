"""Offline integrity checks shared by release auditors.

External evidence is an operator-provided attestation with hashed raw observations.
Integrity verifies binding, not the truth of an attestation; independent review and
native signature verification remain mandatory. Fixture acceptance is test-only.
"""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


HEX = re.compile(r'^[0-9a-f]{64}$')
COMMIT = re.compile(r'^[0-9a-f]{40}$')


def sha256(path):
    with Path(path).open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256')
    return digest.hexdigest()


def safe_path(base, relative):
    if not isinstance(relative, str) or not relative or ':' in relative or '\\' in relative or PurePosixPath(relative).is_absolute():
        raise ValueError('EVIDENCE_RELATIVE_PATH_REQUIRED')
    from app.runtime.workspace import _reject_reparse
    try:
        _reject_reparse(Path(base))
        _reject_reparse(Path(base) / relative)
    except PermissionError:
        raise ValueError('EVIDENCE_REPARSE_FORBIDDEN') from None
    base = Path(base).resolve()
    path = base / relative
    if '..' in Path(relative).parts or not path.resolve().is_relative_to(base):
        raise ValueError('EVIDENCE_PATH_ESCAPE')
    cursor = path
    while cursor != base:
        if cursor.is_symlink():
            raise ValueError('EVIDENCE_SYMLINK_FORBIDDEN')
        cursor = cursor.parent
    return path


def verify_file(base, reference):
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'} or not isinstance(reference['sha256'], str) or not HEX.fullmatch(reference['sha256']):
        raise ValueError('EVIDENCE_REFERENCE_INVALID')
    path = safe_path(base, reference['path'])
    if not path.is_file():
        raise ValueError('EVIDENCE_FILE_MISSING')
    if path.stat().st_nlink != 1:
        raise ValueError('EVIDENCE_HARDLINK_FORBIDDEN')
    if sha256(path) != reference['sha256']:
        raise ValueError('EVIDENCE_HASH_MISMATCH')
    return path


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


def check_reference(base, reference, *, candidate_sha256, commit, allow_test_fixture=False):
    value = load_json(verify_file(base, reference))
    allowed = {'external'} | ({'test_fixture'} if allow_test_fixture else set())
    if not isinstance(value, dict) or value.get('source_kind') not in allowed:
        raise ValueError('NON_RELEASE_EVIDENCE')
    if not HEX.fullmatch(candidate_sha256 or '') or not COMMIT.fullmatch(commit or ''):
        raise ValueError('CANDIDATE_IDENTITY_MISSING')
    if value.get('candidate_sha256') != candidate_sha256 or value.get('commit') != commit:
        raise ValueError('EVIDENCE_BUILD_MISMATCH')
    if value.get('status') != 'passed':
        raise ValueError('EVIDENCE_NOT_PASSED')
    return value


def observed_report(base, reference, *, candidate_sha256, commit, allow_test_fixture=False):
    report = check_reference(base, reference, candidate_sha256=candidate_sha256, commit=commit,
                             allow_test_fixture=allow_test_fixture)
    if not isinstance(report.get('observer'), str) or not report['observer'].strip():
        raise ValueError('EVIDENCE_OBSERVER_MISSING')
    from datetime import datetime
    try:
        stamp = datetime.fromisoformat(report.get('recorded_at', '').replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('UTC_EVIDENCE_TIME_REQUIRED') from None
    raw = report.get('raw_evidence')
    if not isinstance(raw, list) or not raw:
        raise ValueError('RAW_EVIDENCE_REQUIRED')
    for item in raw:
        path = verify_file(base, item)
        if path.suffix.lower() == '.json' and not allow_test_fixture:
            payload = load_json(path)
            if isinstance(payload, dict) and (payload.get('source_kind') == 'test_fixture' or payload.get('evidence_kind') == 'synthetic_fixture'):
                raise ValueError('NON_RELEASE_RAW_EVIDENCE')
    return report

