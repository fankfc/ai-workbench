"""Mechanical registry port. It never executes commands supplied by a model."""
from contextlib import closing

from app.storage.database import Database
from app.storage.blobs import BlobStore
from app.validation.base import ArtifactSnapshot, ValidationContext
from app.validation.registry import Registry


METHODS = {
    'code': {'python_ast_parse': 'artifact'},
    'paper': {'citation_structure_only': 'artifact'},
    'document': {'document_structure_and_source_tokens': 'artifact'},
    'mixed': {'persisted_dependency_current': 'dependency'},
}


class NativeRegistryValidator:
    def __init__(self, database_path, *, execution_port=None, renderer=None):
        self.database = Database(database_path)
        self.store = BlobStore(self.database.path.parent / 'blobs')
        self.execution_port,self.renderer=execution_port,renderer

    def __call__(self, candidate):
        contract, workspace = candidate.contract, candidate.workspace
        output = []
        with closing(self.database.connect()) as connection:
            from app.profiles.newprofile_checks import FrozenProfileChecks
            profile=FrozenProfileChecks(connection,self.store,candidate,execution_port=self.execution_port,renderer=self.renderer)
            for criterion in contract.acceptance:
                if criterion.verifier != 'C' or criterion.semantic:
                    continue
                if profile.handles(criterion):
                    output.append(profile.result(criterion))
                    continue
                method = criterion.condition.removeprefix('C_METHOD:')
                if (criterion.condition != 'C_METHOD:' + method
                        or METHODS.get(contract.domain, {}).get(method) != criterion.evidence_type):
                    output.append(dict(criterion_id=criterion.id, passed=False,
                        evidence=dict(status='not_verified', reason_code='MECHANICAL_METHOD_UNAVAILABLE',
                            artifact_sha256=candidate.byte_sha256, revision_id=candidate.revision_id)))
                    continue
                source = contract.inputs[0]
                context = ValidationContext(contract.task_id, contract.attempt_id,
                    ArtifactSnapshot(candidate.revision_id, candidate.byte_sha256, candidate.artifact_path),
                    [criterion], workspace.root,
                    source=ArtifactSnapshot('source:' + source.id, source.sha256, workspace.resolve(source.ref)),
                    connection=connection, store=self.store,
                    environment=dict(assembly='native-registry', commands_enabled=False))
                result = Registry().validate(contract.domain, context)[0]
                output.append(dict(criterion_id=criterion.id, passed=result.passed,
                    evidence=result.to_dict()))
        return output
