"""Private workflow/publication assembly. HTTP and model data cannot issue it."""
from contextlib import closing
import asyncio

from app.storage.database import Database
from app.contracts.tasks import contract_digest
from .planning import PreparedPlan
from .publication import NativePublisher, PublicationBlocked
from .state_machine import StateMachine, checkpoint_for, require_current_attempt


class NativeTaskExecutor:
    def __init__(self, workflow):
        self.workflow = workflow
        self.database_path = workflow.database_path
        from .composite_context import CompositeAwareValidator
        if not isinstance(workflow.validator, CompositeAwareValidator):
            workflow.validator = CompositeAwareValidator(workflow.validator, self.database_path, workflow.workspaces)

    async def execute(self, plan):
        return await self.workflow.run_prepared(plan)

    async def publish(self, plan, result):
        if not isinstance(plan, PreparedPlan) or result.state != 'OUTPUT_PREPARING':
            raise PublicationBlocked('NATIVE_EXECUTION_NOT_APPROVED')
        contract = plan.contract
        with closing(Database(self.database_path).connect()) as connection:
            row = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
            checkpoint = checkpoint_for(row)
            handoff = checkpoint.get('planning_handoff', {})
            workflow = checkpoint.get('workflow', {})
            if (handoff.get('planning_step_id') != plan.planning_step_id
                    or handoff.get('previous_owner') != plan.owner_token
                    or handoff.get('contract_sha256') != contract_digest(contract)
                    or workflow.get('current_revision_id') != result.current_revision_id
                    or workflow.get('review_check_id') != result.review_check_id
                    or row['state'] not in {'OUTPUT_PREPARING', 'READY', 'PUBLISHED'}):
                raise PublicationBlocked('NATIVE_RESULT_BINDING_REQUIRED')
        workspace = self.workflow.workspaces.create(contract.task_id, contract.attempt_id)
        if contract.model_family=='claude':
            from .answer_publication import AnswerPublisher
            service=self.workflow.translation_service
            if service is None: raise PublicationBlocked('CLAUDE_TRANSLATION_SERVICE_REQUIRED')
            publisher=AnswerPublisher(self.database_path,workspace.area('evidence'),service)
        else:
            publisher = NativePublisher(self.database_path, workspace.area('evidence'))
        formats=checkpoint.get('requested_formats') or []
        composite_run=checkpoint.get('composite_run')
        extra_artifact_ids=[]
        if checkpoint.get('task_profile',{}).get('domain')=='mixed':
            from .composite_context import require_composite_run
            with closing(Database(self.database_path).connect()) as connection:
                require_composite_run(connection,publisher.store,contract.task_id,contract.attempt_id,composite_run)
            extra_artifact_ids=[composite_run[key] for key in ('source_data','analysis_code','figures')]
        bundle_id=checkpoint.get('native_document',{}).get('bundle_id')
        if row['state'] == 'OUTPUT_PREPARING':
            translated_document=None
            if formats:
                from app.documents.parse import parse_document
                from app.documents.translate import DocumentTranslator
                from app.storage.blobs import read_artifact
                with closing(Database(self.database_path).connect()) as connection:
                    artifact=connection.execute('SELECT * FROM artifact_revisions WHERE id=?',(result.current_revision_id,)).fetchone()
                    model=parse_document(read_artifact(connection,publisher.store,result.current_revision_id),'markdown',
                        source_version_id=result.current_revision_id,language=artifact['language'])
                if not model.complete: raise PublicationBlocked('DOCUMENT_PARSE_INCOMPLETE')
                if contract.model_family=='claude':
                    translated_document=await DocumentTranslator(self.database_path,service).translate(contract.task_id,contract.attempt_id,model)
            stage=publisher.stage(contract.task_id, contract.attempt_id, contract.contract_version,
                result.current_revision_id, result.review_check_id)
            if contract.model_family=='claude': await stage
            if formats:
                from app.documents.publish import BundlePublisher
                bundle=BundlePublisher(self.database_path,workspace.area('evidence'))
                bundle_id=bundle.stage(contract.task_id,contract.attempt_id,contract.contract_version,
                    result.current_revision_id,formats,title='Report',
                    translation_revision_id=translated_document['revision_id'] if translated_document else None,
                    review_check_id=result.review_check_id,extra_artifact_ids=extra_artifact_ids)
                from app.storage.database import transaction
                import json
                with closing(Database(self.database_path).connect()) as connection,transaction(connection):
                    current=require_current_attempt(connection,contract.task_id,contract.attempt_id,contract.contract_version)
                    updated=checkpoint_for(current)
                    updated['native_document']=dict(bundle_id=bundle_id,source_revision_id=result.current_revision_id,
                        requested_formats=formats,translation_revision_id=translated_document['revision_id'] if translated_document else None)
                    connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',
                        (json.dumps(updated),contract.task_id,contract.attempt_id))
            StateMachine(self.database_path).transition(contract.task_id, contract.attempt_id,
                'OUTPUT_PREPARING', 'READY', contract.contract_version)
        if formats:
            if not bundle_id: raise PublicationBlocked('COMPLETE_DOCUMENT_BUNDLE_REQUIRED')
            from app.documents.publish import BundlePublisher
            bundle=BundlePublisher(self.database_path,workspace.area('evidence'))
            return bundle.publish(bundle_id,answer_releaser=publisher.publish_in_transaction)
        return publisher.publish(contract.task_id, contract.attempt_id, contract.contract_version)

    async def cancel(self, task_id, attempt_id):
        # Both roles may be waiting; all cleanup results must be inspected.
        values = await asyncio.gather(self.workflow.adapter.cancel(task_id, attempt_id),
            self.workflow.reviewer.cancel(task_id, attempt_id), return_exceptions=True)
        if any(isinstance(value, BaseException) for value in values):
            raise PublicationBlocked('NATIVE_LOCAL_CLEANUP_UNCONFIRMED')
