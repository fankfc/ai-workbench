"""Capture A body from service-owned persisted request and immutable event stream.

Calling this API does not create provenance from a supplied author label. It
reads the same request/event records written by the provider runner, checks its
role and pinned identity, and refuses incomplete output and review-only text.
"""
from contextlib import closing
import json
import re
from uuid import uuid4

from app.contracts.artifacts import ArtifactDependency, ArtifactVersion
from app.contracts.providers import AgentRequestRecord
from app.storage.blobs import BlobStore, read_artifact, store_artifact
from app.storage.database import Database, transaction
from app.storage.revisions import activate_revision
from .model import digest, json_bytes


def _read_response(connection, task_id, attempt_id, step_id):
    task = connection.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?', (task_id, attempt_id)).fetchone()
    step = connection.execute('SELECT * FROM steps WHERE id=? AND task_id=? AND attempt_id=?', (step_id, task_id, attempt_id)).fetchone()
    if task is None or step is None or step['role'] != 'A':
        raise ValueError('A_RESPONSE_STEP_REQUIRED')
    if step['state'] != 'COMPLETED':
        raise ValueError('A_RESPONSE_NOT_COMPLETE')
    request = AgentRequestRecord.model_validate_json(step['request_json'])
    route = json.loads(task['route_snapshot_json'])
    if (request.task_id, request.attempt_id, request.role, step['provider_profile_id']) != (task_id, attempt_id, 'A', route['provider_id']):
        raise ValueError('A_RESPONSE_IDENTITY_MISMATCH')
    if (request.identity.model_id, request.identity.adapter, request.identity.family.value) != (route['model_id'], route['adapter_id'], route['model_family']):
        raise ValueError('A_RESPONSE_IDENTITY_MISMATCH')
    if route.get('identity_status') != 'verified' and not (route.get('test_only') and request.identity.adapter == 'fake'):
        raise ValueError('A_RESPONSE_IDENTITY_UNVERIFIED')
    raw = []
    for row in connection.execute("SELECT * FROM outbox_events WHERE task_id=? AND attempt_id=? AND kind='workflow.provider_event' ORDER BY sequence", (task_id, attempt_id)):
        payload = json.loads(row['internal_payload_json'])
        if payload.get('step_id') == step_id:
            raw.append({k: payload[k] for k in ('provider_sequence', 'kind', 'payload')})
    sequences = [e['provider_sequence'] for e in raw]
    if not raw or any(type(s) is not int for s in sequences) or sequences != sorted(set(sequences)):
        raise ValueError('A_RESPONSE_EVENT_SEQUENCE_INVALID')
    complete = [e for e in raw if e['kind'] in ('model.completed', 'provider.completed')]
    if len(complete) != 1:
        raise ValueError('A_RESPONSE_NOT_COMPLETE')
    final = complete[0]
    if any(e['kind'] in ('model.delta', 'artifact.candidate') and e['provider_sequence'] > final['provider_sequence'] for e in raw):
        raise ValueError('A_RESPONSE_AFTER_COMPLETION')
    if (any(e['kind'] == 'provider.error' for e in raw)
            or final['payload'].get('reported_complete') is False
            or final['payload'].get('finish_reason', 'stop') not in ('stop', 'end_turn', 'completed')):
        raise ValueError('A_RESPONSE_NOT_COMPLETE')
    candidates = [e['payload']['text'] for e in raw if e['kind'] == 'artifact.candidate' and isinstance(e['payload'].get('text'), str)]
    if len(candidates) > 1:
        raise ValueError('A_RESPONSE_BODY_MISMATCH')
    parts = [e['payload'].get('text', '') for e in raw if e['kind'] == 'model.delta']
    if any(not isinstance(p, str) for p in parts):
        raise ValueError('A_RESPONSE_BODY_MISMATCH')
    body = final['payload'].get('text', candidates[0] if candidates else ''.join(parts))
    if not isinstance(body, str) or not body.strip() or re.fullmatch(r'\s*(PASS|APPROVED|OK|通过|批准)[.!。\s]*', body, re.I):
        raise ValueError('A_CANONICAL_REQUIRED')
    if (parts and ''.join(parts) != body) or (candidates and candidates[0] != body):
        raise ValueError('A_RESPONSE_BODY_MISMATCH')
    manifest = final['payload'].get('document_manifest')
    if manifest is not None:
        count = manifest.get('part_count') if isinstance(manifest, dict) else None
        if (type(count) is not int or count < 1 or manifest.get('part_numbers') != list(range(1, count+1))
                or manifest.get('complete') is not True or len(parts) != count
                or manifest.get('body_sha256') != digest(body.encode())):
            raise ValueError('A_RESPONSE_MANIFEST_INCOMPLETE')
    return task, step, body.encode('utf-8'), json_bytes(raw), {'completion_sequence': final['provider_sequence'],
        'event_sequences': sequences, 'multipart': manifest, 'test_only': bool(route.get('test_only'))}


class CanonicalCapture:
    def __init__(self, database_path):
        self.database = Database(database_path)
        self.store = BlobStore(self.database.path.parent / 'blobs')

    def capture(self, task_id, attempt_id, step_id, *, language, logical_id='report', dependencies=None, revision_id=None):
        dependencies = dependencies or {}
        with closing(self.database.connect()) as c:
            task, step, body, raw, manifest = _read_response(c, task_id, attempt_id, step_id)
            route = json.loads(task['route_snapshot_json'])
            if task['cancel_requested']:
                raise ValueError('TASK_CANCELLED')
            if route['model_family'] == 'claude' and language != 'en':
                raise ValueError('A_CANONICAL_ENGLISH_REQUIRED')
            body_sha, raw_sha = digest(body), digest(raw)
            raw_ref = self.store.put(raw)
            revision_id = revision_id or 'canonical-' + uuid4().hex
            existing = c.execute('SELECT * FROM artifact_revisions WHERE id=?', (revision_id,)).fetchone()
            if existing is None:
                artifact = ArtifactVersion(id=revision_id, task_id=task_id, artifact_kind='document', language=language,
                    immutable_uri=self.store.uri_for(body_sha), byte_sha256=body_sha, canonical_content_sha256=body_sha,
                    source_version_id=None, origin_authors=['A'], canonical_issued_by='A', reviewed_by=[],
                    rendered_by='none', a_response_ref=self.store.uri_for(body_sha),
                    dependencies=[ArtifactDependency(artifact_version_id=v, relationship='source') for v in dependencies.values()])
                store_artifact(c, self.store, body, artifact, attempt_id=attempt_id,
                    provenance={'step_id': step_id, 'raw_response_ref': self.store.uri_for(raw_ref.sha256),
                        'authenticated_authorship': True, 'test_only': manifest['test_only']},
                    source_request={'step_id': step_id, 'external_request_id': step['external_request_id']})
            elif (existing['task_id'], existing['attempt_id'], existing['language'], existing['canonical_issued_by']) != (task_id, attempt_id, language, 'A') or read_artifact(c, self.store, revision_id) != body:
                raise ValueError('A_CANONICAL_RESPONSE_BYTES_REQUIRED')
            with transaction(c):
                proof = c.execute('SELECT * FROM a_document_responses WHERE revision_id=?', (revision_id,)).fetchone()
                if proof is None:
                    c.execute('INSERT INTO a_document_responses(id,task_id,attempt_id,step_id,revision_id,provider_profile_id,route_snapshot_id,raw_response_sha256,body_sha256,manifest_json) VALUES (?,?,?,?,?,?,?,?,?,?)',
                        ('response-'+uuid4().hex, task_id, attempt_id, step_id, revision_id, step['provider_profile_id'], route['id'], raw_sha, body_sha, json_bytes(manifest).decode()))
                    details = {'response_ref': existing['a_response_ref'] if existing else self.store.uri_for(body_sha), 'canonical_content_sha256': body_sha,
                        'verified_issuer': 'A', 'step_id': step_id, 'raw_response_sha256': raw_sha, 'test_only': manifest['test_only']}
                    c.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES (?,?,?,?,'A.canonical','pass',?,?)",
                        ('canonical-check-'+uuid4().hex, task_id, attempt_id, revision_id, task['contract_version'], json_bytes(details).decode()))
                activate_revision(c, self.store, task_id, attempt_id, logical_id, revision_id, dependencies)
            return {'revision_id': revision_id, 'step_id': step_id, 'body_sha256': body_sha,
                'raw_response_sha256': raw_sha, 'test_only': manifest['test_only']}


def require_canonical(connection, store, revision_id):
    proof = connection.execute('SELECT * FROM a_document_responses WHERE revision_id=?', (revision_id,)).fetchone()
    artifact = connection.execute('SELECT * FROM artifact_revisions WHERE id=?', (revision_id,)).fetchone()
    if proof is None or artifact is None or artifact['canonical_issued_by'] != 'A' or 'A' not in json.loads(artifact['origin_authors_json']):
        raise ValueError('A_CANONICAL_PROVENANCE_REQUIRED')
    task, step, body, raw, manifest = _read_response(connection, proof['task_id'], proof['attempt_id'], proof['step_id'])
    if (proof['body_sha256'], proof['raw_response_sha256'], proof['route_snapshot_id'], proof['provider_profile_id']) != (
            digest(body), digest(raw), json.loads(task['route_snapshot_json'])['id'], step['provider_profile_id']):
        raise ValueError('A_CANONICAL_PROVENANCE_MISMATCH')
    if read_artifact(connection, store, revision_id) != body or artifact['canonical_content_sha256'] != digest(body) or store.read(proof['raw_response_sha256']) != raw:
        raise ValueError('A_CANONICAL_RESPONSE_BYTES_REQUIRED')
    if artifact['a_response_ref'] not in (store.uri_for(digest(body)), proof['step_id']):
        raise ValueError('A_CANONICAL_RESPONSE_REFERENCE_REQUIRED')
    return dict(proof)
