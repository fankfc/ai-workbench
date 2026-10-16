"""Business red cases against the frozen first-part implementation."""
import hashlib
import json
from contextlib import closing

import pytest

from app.contracts.artifacts import ArtifactVersion
from app.storage.blobs import store_artifact
from app.storage.database import transaction
from app.storage.revisions import activate_revision
from app.runtime.publication import NativePublisher, PublicationBlocked
from support.contracts import make_contract, make_decision


def test_published_bundle_list_is_an_actual_authenticated_business_endpoint(client):
    conversation = client.post('/v1/conversations', json={'title': 'documents'}).json()['id']
    response = client.get(f'/v1/conversations/{conversation}/bundles')
    assert response.status_code == 200
    assert response.json() == {'items': []}


def test_a_pass_does_not_become_complete_a_document_by_adding_metadata(client):
    conversation = client.post('/v1/conversations', json={'title': 'documents'}).json()['id']
    task = client.post(f'/v1/conversations/{conversation}/turns', json={
        'text': 'Write the full report', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'one'
    }).json()['task_id']
    root = client.app.state.settings.data_root / 'evidence'
    with closing(client.app.state.database.connect()) as connection:
        row = connection.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone()
        attempt = row['attempt_id']
        route = json.loads(row['route_snapshot_json'])
        content = b'PASS'
        sha = hashlib.sha256(content).hexdigest()
        ref = client.app.state.blobs.uri_for(sha)
        artifact = ArtifactVersion(id='pass-only', task_id=task, artifact_kind='document', language='en',
            immutable_uri=ref, byte_sha256=sha, canonical_content_sha256=sha, source_version_id=None,
            origin_authors=['A'], canonical_issued_by='A', reviewed_by=['A'], rendered_by='none',
            a_response_ref=ref, dependencies=[])
        store_artifact(connection, client.app.state.blobs, content, artifact, attempt_id=attempt,
            provenance={'claimed_author': 'A'})
        contract = make_contract(task, attempt, route['id'], domain='document')
        decision = make_decision(contract, artifact.id, root)
        from app.contracts.tasks import contract_digest
        with transaction(connection):
            checkpoint = {'current_revision_id': artifact.id, 'task_contract': contract,
                'workflow': {'contract_sha256': contract_digest(contract)}}
            connection.execute("UPDATE task_runs SET state='OUTPUT_PREPARING',checkpoint_json=? WHERE task_id=?",
                (json.dumps(checkpoint), task))
            activate_revision(connection, client.app.state.blobs, task, attempt, 'report', artifact.id, {})
            connection.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES ('review',?,?,?,'A.review','pass','1.0',?)",
                (task, attempt, artifact.id, json.dumps({'contract': contract, 'decision': decision})))
            connection.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES ('canonical',?,?,?,'A.canonical','pass','1.0',?)",
                (task, attempt, artifact.id, json.dumps({'response_ref': ref, 'canonical_content_sha256': sha, 'verified_issuer': 'A'})))
    with pytest.raises(PublicationBlocked, match='A_CANONICAL'):
        NativePublisher(client.app.state.database.path, root).stage(task, attempt, '1.0', artifact.id, 'review')
