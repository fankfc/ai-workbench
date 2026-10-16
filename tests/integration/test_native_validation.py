"""Registry assembly checks current stored bytes; fixtures do not run models."""
from contextlib import closing
import hashlib

from app.contracts.artifacts import ArtifactVersion
from app.contracts.tasks import validate_contract
from app.runtime.native_validation import NativeRegistryValidator
from app.runtime.workflow import CandidateContext
from app.storage.blobs import store_artifact
from app.storage.revisions import activate_revision
from test_native_planning import prepared_case


def candidate_case(tmp_path, domain='code', content=b'answer = 6\n', method='python_ast_parse'):
    app, manager, plan, _ = prepared_case(tmp_path)
    workspace = manager.create(plan.contract.task_id, plan.contract.attempt_id)
    value = plan.contract.model_dump(mode='json')
    value['domain'] = domain
    value['acceptance'][0].update(condition='C_METHOD:' + method,
        evidence_type='dependency' if domain == 'mixed' else 'artifact')
    contract = validate_contract(value)
    digest = hashlib.sha256(content).hexdigest()
    artifact = ArtifactVersion(id='registry-fixture', task_id=contract.task_id, artifact_kind='code', language='und',
        immutable_uri=app.state.blobs.uri_for(digest), byte_sha256=digest, canonical_content_sha256=digest,
        source_version_id=None, origin_authors=['B'], canonical_issued_by='B', reviewed_by=[], rendered_by='none',
        a_response_ref=None, dependencies=[])
    with closing(app.state.database.connect()) as connection:
        store_artifact(connection, app.state.blobs, content, artifact, attempt_id=contract.attempt_id,
            provenance={'test_only': True})
        activate_revision(connection, app.state.blobs, contract.task_id, contract.attempt_id,
            'answer', artifact.id, {})
    return app, CandidateContext(contract, workspace, artifact.id, app.state.blobs.path_for(digest), digest, content)


def test_registry_port_uses_actual_immutable_python_bytes(tmp_path):
    app, candidate = candidate_case(tmp_path)
    result = NativeRegistryValidator(app.state.database.path)(candidate)
    assert len(result) == 1 and result[0]['passed'] is True
    assert result[0]['evidence']['method'] == 'python_ast_parse'
    assert result[0]['evidence']['artifact_sha256'] == candidate.byte_sha256


def test_broken_python_is_not_a_successful_mechanical_check(tmp_path):
    app, candidate = candidate_case(tmp_path, content=b'def broken(:\n')
    result = NativeRegistryValidator(app.state.database.path)(candidate)
    assert len(result) == 1 and result[0]['passed'] is False


def test_arbitrary_execution_condition_cannot_be_called_syntax_verified(tmp_path):
    app, candidate = candidate_case(tmp_path, method='Run model command and verify everything')
    result = NativeRegistryValidator(app.state.database.path)(candidate)
    assert len(result) == 1 and result[0]['passed'] is False
    assert result[0]['evidence']['reason_code'] == 'MECHANICAL_METHOD_UNAVAILABLE'


def test_mixed_mechanical_proof_checks_current_dependency_revision(tmp_path):
    app, candidate = candidate_case(tmp_path, domain='mixed', method='persisted_dependency_current')
    result = NativeRegistryValidator(app.state.database.path)(candidate)
    assert len(result) == 1 and result[0]['passed'] is True
