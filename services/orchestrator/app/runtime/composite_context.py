"""Service-owned fixed CSV computation before A locks its execution contract."""
from contextlib import closing
import hashlib
import json
from pathlib import Path

from app.documents.composite import CompositePipeline
from app.documents.model import json_bytes
from app.storage.blobs import BlobStore, read_artifact
from app.storage.database import Database, transaction
from app.storage.revisions import is_current_revision
from .state_machine import checkpoint_for, require_current_attempt

KINDS = ('source_data', 'analysis_code', 'computed_results', 'figures')


def require_composite_run(connection, store, task, attempt, run):
    if not isinstance(run, dict) or any(not isinstance(run.get(key), str) for key in KINDS):
        raise ValueError('COMPOSITE_RESULTS_REQUIRED')
    for key in KINDS:
        if not is_current_revision(connection, task, attempt, run[key]):
            raise ValueError('COMPOSITE_DEPENDENCY_CHANGED')
        row = connection.execute('SELECT task_id,attempt_id FROM artifact_revisions WHERE id=?', (run[key],)).fetchone()
        if row is None or (row['task_id'], row['attempt_id']) != (task, attempt):
            raise ValueError('COMPOSITE_SCOPE_CHANGED')
        data = read_artifact(connection, store, run[key])
        if key == 'source_data' and hashlib.sha256(data).hexdigest() != run['source_sha256']:
            raise ValueError('COMPOSITE_SOURCE_CHANGED')
        if key == 'computed_results' and json.loads(data) != run['results']:
            raise ValueError('COMPOSITE_RESULTS_CHANGED')
    return run


def prepare_composite_context(database_path, workspace_manager, task_id, attempt_id, profile_context):
    if not profile_context or profile_context.get('domain') != 'mixed':
        return None
    refs = profile_context['inputs'].get('data_refs')
    if not isinstance(refs, list) or len(refs) != 1:
        raise ValueError('COMPOSITE_ONE_CSV_REQUIRED')
    database = Database(database_path)
    store = BlobStore(Path(database_path).parent / 'blobs')
    workspace = workspace_manager.create(task_id, attempt_id)
    data = workspace.read('service', refs[0])
    source_hash = hashlib.sha256(data).hexdigest()
    with closing(database.connect()) as connection:
        row = require_current_attempt(connection, task_id, attempt_id, '1.0')
        if row['cancel_requested'] or row['state'] != 'INPUT_PREPARING':
            raise ValueError('COMPOSITE_INPUT_STATE_REQUIRED')
        saved = checkpoint_for(row).get('composite_run')
        if saved:
            require_composite_run(connection, store, task_id, attempt_id, saved)
            if saved['source_sha256'] != source_hash or saved['data_ref'] != refs[0]:
                raise ValueError('COMPOSITE_INPUT_CHANGED')
            return saved['planning_context']
    run = CompositePipeline(database_path, workspace_manager).run(task_id, attempt_id, data)
    results_data = json_bytes(run['results'])
    result_ref = 'input/composite-results-' + hashlib.sha256(results_data).hexdigest()[:16] + '.json'
    workspace.ingest_source(result_ref.removeprefix('input/'), results_data)
    inputs = [dict(id='COMPOSITE-CSV', ref=run['source_ref'], sha256=run['source_sha256']),
              dict(id='COMPOSITE-CODE', ref=run['code_ref'], sha256=run['code_sha256']),
              dict(id='COMPOSITE-RESULT', ref=result_ref, sha256=hashlib.sha256(results_data).hexdigest())]
    context = dict(summary='Service independently recomputed the attached CSV. Use these exact results and '
                   'state January, February, and Increase fields in the canonical report: ' + json.dumps(run['results'], sort_keys=True),
                   inputs=inputs, dependencies=[run[key] for key in KINDS])
    run.update(data_ref=refs[0], planning_context=context)
    with closing(database.connect()) as connection, transaction(connection):
        row = require_current_attempt(connection, task_id, attempt_id, '1.0')
        if row['cancel_requested'] or row['state'] != 'INPUT_PREPARING':
            raise ValueError('COMPOSITE_INPUT_STATE_REQUIRED')
        require_composite_run(connection, store, task_id, attempt_id, run)
        checkpoint = checkpoint_for(row)
        checkpoint['composite_run'] = run
        connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',
                           (json.dumps(checkpoint), task_id, attempt_id))
    return context


class CompositeAwareValidator:
    """Select only the frozen mixed-profile checks, preserving other C ports."""
    def __init__(self, original, database_path, workspaces):
        self.original = original
        self.database = Database(database_path)
        self.store = BlobStore(Path(database_path).parent / 'blobs')
        self.workspaces = workspaces

    def __call__(self, candidate):
        from app.profiles.registry import get_profile
        contract = candidate.contract
        with closing(self.database.connect()) as connection:
            task = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
            checkpoint = checkpoint_for(task)
            run = checkpoint.get('composite_run')
            profile = checkpoint.get('task_profile')
            if contract.domain != 'mixed' or not profile:
                return self.original(candidate)
            require_composite_run(connection, self.store, contract.task_id, contract.attempt_id, run)
            expected = {item['id']: item for item in get_profile('mixed')['acceptance'] if item['verifier'] == 'C'}
            if set(contract.dependencies) != {run[key] for key in KINDS}:
                raise ValueError('COMPOSITE_CONTRACT_DEPENDENCIES_REQUIRED')
            for criterion in contract.acceptance:
                if criterion.id in expected:
                    template = expected[criterion.id]
                    if (criterion.condition != template['condition'] or criterion.verifier != 'C'
                            or criterion.semantic or criterion.evidence_type != template['evidence_type']):
                        raise ValueError('COMPOSITE_CRITERION_CHANGED')
        original = self.original(candidate)
        if hasattr(original, '__await__'):
            raise ValueError('COMPOSITE_SYNCHRONOUS_C_PORT_REQUIRED')
        composite = CompositePipeline(self.database.path, self.workspaces).validator(run)(candidate)
        return [value for value in original if value['criterion_id'] not in expected] + [
            value for value in composite if value['criterion_id'] in expected]
