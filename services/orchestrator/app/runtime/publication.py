"""Trusted native answer publisher. No HTTP or provider-event publication authority."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from app.contracts.tasks import contract_digest,evaluate_review,validate_contract
from app.contracts.events import PublicEvent
from app.storage.database import Database,transaction
from app.storage.blobs import BlobStore,read_artifact
from app.storage.revisions import is_current_revision,snapshot_fence,require_publication_fence
from .state_machine import require_current_attempt,checkpoint_for,register_release_gate,validate_release_gate,TransitionError
from .outbox import enqueue_event

class PublicationBlocked(ValueError):
    pass

class NativePublisher:
    def __init__(self,database_path:Path,evidence_root:Path):
        self.database_path=Path(database_path)
        self.database=Database(self.database_path)
        self.store=BlobStore(self.database_path.parent/'blobs')
        self.evidence_root=Path(evidence_root).resolve()
        self.evidence_root.relative_to(self.database_path.parent.resolve())

    def _review_snapshot(self,connection,task,revision_id,review_check_id,content):
        task_id,attempt_id,version=task['task_id'],task['attempt_id'],task['contract_version']
        route=json.loads(task['route_snapshot_json'])
        if route.get('model_family')!='gpt' or route.get('route_policy')!='native':
            raise PublicationBlocked('LANGUAGE_AND_PROVENANCE_GATES_MISSING')
        check=connection.execute("SELECT * FROM checks WHERE id=? AND task_id=? AND attempt_id=? AND artifact_version_id=? AND check_kind='A.review' AND result='pass'",(review_check_id,task_id,attempt_id,revision_id)).fetchone()
        if check is None or check['check_version']!=version:
            raise PublicationBlocked('CURRENT_A_REVIEW_REQUIRED')
        details=json.loads(check['details_json'])
        contract=validate_contract(details['contract'])
        if (contract.task_id,contract.attempt_id,contract.contract_version,contract.route_snapshot_id)!=(task_id,attempt_id,version,route.get('id')) or details['decision'].get('revision_id')!=revision_id:
            raise PublicationBlocked('REVIEW_ROUTE_OR_REVISION_BINDING_MISMATCH')
        digest=contract_digest(contract)
        checkpoint=checkpoint_for(task)
        pinned=checkpoint.get('task_contract')
        if pinned is None or contract_digest(pinned)!=digest or checkpoint.get('workflow',{}).get('contract_sha256')!=digest:
            raise PublicationBlocked('PINNED_CONTRACT_CHANGED')
        if details.get('stale') or not evaluate_review(contract,details['decision'],self.evidence_root).eligible_for_output:
            raise PublicationBlocked('REVIEW_EVIDENCE_REQUIRED')
        requested_formats=checkpoint.get('requested_formats',[])
        if any(item.require_a_canonical for item in contract.deliverables) or requested_formats:
            from app.documents.canonical import require_canonical
            try:
                require_canonical(connection,self.store,revision_id)
            except ValueError as error:
                raise PublicationBlocked(str(error)) from error
        review_sha=hashlib.sha256(json.dumps(details,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()
        return {'contract_sha256':digest,'review_sha256':review_sha,'requires_bundle':bool(requested_formats)}

    def stage(self,task_id,attempt_id,contract_version,revision_id,review_check_id):
        with closing(self.database.connect()) as connection,transaction(connection):
            task=require_current_attempt(connection,task_id,attempt_id,contract_version)
            if task['state']!='OUTPUT_PREPARING' or task['cancel_requested']:
                raise PublicationBlocked('OUTPUT_STATE_REQUIRED')
            route=json.loads(task['route_snapshot_json'])
            checkpoint=checkpoint_for(task)
            if checkpoint.get('current_revision_id')!=revision_id or checkpoint.get('stale') or checkpoint.get('publication_blocked'):
                raise PublicationBlocked('CURRENT_REVISION_REQUIRED')
            content=read_artifact(connection,self.store,revision_id)
            content.decode('utf-8')
            review_snapshot=self._review_snapshot(connection,task,revision_id,review_check_id,content)
            if not is_current_revision(connection,task_id,attempt_id,revision_id):
                raise PublicationBlocked('CURRENT_DEPENDENCIES_REQUIRED')
            fence=snapshot_fence(connection,task_id,attempt_id,[revision_id])
            approval='release-'+uuid4().hex
            register_release_gate(connection,task_id,attempt_id,contract_version,revision_id,approval,route['id'])
            task=connection.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?',(task_id,attempt_id)).fetchone()
            checkpoint=checkpoint_for(task)
            checkpoint['public_release']={'revision_id':revision_id,'approval_id':approval,'message_id':uuid4().hex,'sha256':hashlib.sha256(content).hexdigest(),'review_check_id':review_check_id,'dependency_fence':fence,'review_snapshot':review_snapshot}
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task_id,attempt_id))
            return approval

    def publish(self,task_id,attempt_id,contract_version):
        with closing(self.database.connect()) as connection,transaction(connection):
            task=require_current_attempt(connection,task_id,attempt_id,contract_version)
            return self.publish_in_transaction(connection,task)

    def publish_in_transaction(self,connection,task,*,bundle_id=None):
        """Same native gates inside the bundle publisher's existing writer."""
        if not connection.in_transaction:
            raise PublicationBlocked('PUBLICATION_TRANSACTION_REQUIRED')
        task_id,attempt_id,contract_version=task['task_id'],task['attempt_id'],task['contract_version']
        task=require_current_attempt(connection,task_id,attempt_id,contract_version)
        checkpoint=checkpoint_for(task)
        if task['cancel_requested'] or checkpoint.get('stale') or checkpoint.get('publication_blocked'):
            raise PublicationBlocked('CANCELLED_OR_STALE')
        if task['state']=='PUBLISHED':
            return dict(task_id=task_id,attempt_id=attempt_id,state='PUBLISHED')
        if task['state']!='READY':
            raise PublicationBlocked('READY_REQUIRED')
        validate_release_gate(connection,task,checkpoint)
        release=checkpoint.get('public_release')
        if not isinstance(release,dict) or release.get('revision_id')!=checkpoint.get('current_revision_id'):
            raise PublicationBlocked('STAGED_PUBLIC_RELEASE_REQUIRED')
        try:
            require_publication_fence(connection,task_id,attempt_id,release.get('dependency_fence'))
        except ValueError as error:
            raise PublicationBlocked(str(error)) from error
        content=read_artifact(connection,self.store,release['revision_id'])
        if hashlib.sha256(content).hexdigest()!=release['sha256']:
            raise PublicationBlocked('RELEASE_BYTES_CHANGED')
        review_snapshot=self._review_snapshot(connection,task,release['revision_id'],release.get('review_check_id'),content)
        if review_snapshot!=release.get('review_snapshot'):
            raise PublicationBlocked('STAGED_REVIEW_CHANGED')
        if review_snapshot['requires_bundle']:
            if not bundle_id: raise PublicationBlocked('COMPLETE_DELIVERY_BUNDLE_REQUIRED')
            from app.documents.publish import _verify_bundle
            row=connection.execute('SELECT * FROM delivery_bundles WHERE id=? AND task_id=? AND attempt_id=?',(bundle_id,task_id,attempt_id)).fetchone()
            if (row is None or row['state'] not in ('VERIFIED','PUBLISHED') or row['source_version_id']!=release['revision_id']
                    or row['approval_id']!=release['approval_id'] or row['route_snapshot_id']!=json.loads(task['route_snapshot_json'])['id']
                    or sorted(json.loads(row['requested_formats_json']))!=sorted(checkpoint['requested_formats'])):
                raise PublicationBlocked('COMPLETE_DELIVERY_BUNDLE_REQUIRED')
            try: _verify_bundle(connection,self.store,bundle_id,self.evidence_root,current=True)
            except ValueError as error: raise PublicationBlocked(str(error)) from error
        connection.execute("UPDATE task_runs SET state='PUBLISHED',completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE task_id=? AND attempt_id=?",(task_id,attempt_id))
        enqueue_event(connection,task_id,attempt_id,'task.state_changed',{'expected_state':'READY','new_state':'PUBLISHED','contract_version':contract_version},deduplication_key=f'publish-state:{task_id}:{attempt_id}:{release["revision_id"]}')
        artifact=connection.execute('SELECT * FROM artifact_revisions WHERE id=?',(release['revision_id'],)).fetchone()
        payload=dict(message_id=release['message_id'],text=content.decode('utf-8'),language=artifact['language'],content_version_id=release['revision_id'],approval_id=release['approval_id'])
        event=enqueue_event(connection,task_id,attempt_id,'answer.published',{'release_id':release['approval_id']},deduplication_key=f'publish-answer:{task_id}:{attempt_id}:{release["revision_id"]}',public_payload=payload)
        public=PublicEvent.model_validate_json(event['public_event_json']).model_dump(mode='json')
        snapshot_sha=hashlib.sha256(json.dumps(public,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()
        frozen=dict(event_id=event['event_id'],task_id=task_id,attempt_id=attempt_id,contract_version=contract_version,artifact_version_id=release['revision_id'],artifact_sha256=artifact['byte_sha256'],route_snapshot_id=json.loads(task['route_snapshot_json'])['id'],public_event_sha256=snapshot_sha,approval_id=release['approval_id'],review_check_id=release['review_check_id'],published_via='native_publisher_v1')
        connection.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES (?,?,?,?,'release.publication','pass',?,?)",('publication-'+event['event_id'],task_id,attempt_id,release['revision_id'],contract_version,json.dumps(frozen)))
        checkpoint['public_release']['event_id']=event['event_id']
        connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task_id,attempt_id))
        return dict(task_id=task_id,attempt_id=attempt_id,state='PUBLISHED',event_id=event['event_id'])
