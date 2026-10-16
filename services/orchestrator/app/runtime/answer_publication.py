"""Trusted Claude answer gate; GPT delegates to the existing native publisher."""
from contextlib import closing
import hashlib
import json
from uuid import uuid4

from app.contracts.artifacts import ArtifactVersion, ArtifactDependency
from app.contracts.events import PublicEvent
from app.contracts.tasks import validate_contract,contract_digest,evaluate_review
from app.storage.blobs import store_artifact,read_artifact
from app.storage.database import transaction
from app.storage.revisions import activate_revision,is_current_revision,snapshot_fence,require_publication_fence
from app.translation.output_pipeline import OutputPipeline
from app.translation.history import BilingualHistory
from .publication import NativePublisher,PublicationBlocked
from .state_machine import require_current_attempt,checkpoint_for,register_release_gate,validate_release_gate
from .outbox import enqueue_event


class AnswerPublisher(NativePublisher):
    def __init__(self,database_path,evidence_root,translation_service=None):
        super().__init__(database_path,evidence_root)
        self.translation=translation_service
        self.output=OutputPipeline(translation_service) if translation_service is not None else None

    def _source_review(self,connection,task,source_id,review_id):
        route=json.loads(task['route_snapshot_json']); checkpoint=checkpoint_for(task)
        check=connection.execute("SELECT * FROM checks WHERE id=? AND task_id=? AND attempt_id=? AND artifact_version_id=? AND check_kind='A.review' AND result='pass'",(review_id,task['task_id'],task['attempt_id'],source_id)).fetchone()
        if check is None or check['check_version']!=task['contract_version']:
            raise PublicationBlocked('CURRENT_A_REVIEW_REQUIRED')
        details=json.loads(check['details_json']); contract=validate_contract(details['contract'])
        if ((contract.task_id,contract.attempt_id,contract.contract_version,contract.route_snapshot_id)!=(task['task_id'],task['attempt_id'],task['contract_version'],route['id'])
                or details['decision'].get('revision_id')!=source_id or details.get('stale')):
            raise PublicationBlocked('REVIEW_ROUTE_OR_REVISION_BINDING_MISMATCH')
        digest=contract_digest(contract)
        if (checkpoint.get('task_contract') is None or contract_digest(checkpoint['task_contract'])!=digest
                or checkpoint.get('workflow',{}).get('contract_sha256')!=digest
                or not evaluate_review(contract,details['decision'],self.evidence_root).eligible_for_output):
            raise PublicationBlocked('PINNED_CONTRACT_OR_REVIEW_CHANGED')
        artifact=connection.execute('SELECT * FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?',(source_id,task['task_id'],task['attempt_id'])).fetchone()
        if (artifact is None or artifact['language']!='en' or artifact['canonical_issued_by']!='A'
                or 'A' not in json.loads(artifact['origin_authors_json'])):
            raise PublicationBlocked('COMPLETE_A_ENGLISH_OUTPUT_REQUIRED')
        from app.documents.canonical import require_canonical
        try: require_canonical(connection,self.store,source_id)
        except ValueError as exc: raise PublicationBlocked(str(exc)) from exc
        content=read_artifact(connection,self.store,source_id)
        if any(d.require_a_canonical for d in contract.deliverables):
            canonical=connection.execute("SELECT details_json FROM checks WHERE task_id=? AND attempt_id=? AND artifact_version_id=? AND check_kind='A.canonical' AND result='pass' AND check_version=?",(task['task_id'],task['attempt_id'],source_id,task['contract_version'])).fetchone()
            if canonical is None: raise PublicationBlocked('A_CANONICAL_PROVENANCE_REQUIRED')
            provenance=json.loads(canonical[0])
            if (provenance.get('response_ref')!=artifact['a_response_ref'] or provenance.get('canonical_content_sha256')!=artifact['canonical_content_sha256']
                    or provenance.get('verified_issuer')!='A' or provenance.get('stale')):
                raise PublicationBlocked('A_CANONICAL_PROVENANCE_REQUIRED')
        return dict(contract_sha256=digest,review_sha256=hashlib.sha256(json.dumps(details,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),
            source_sha256=hashlib.sha256(content).hexdigest(),requires_bundle=bool(checkpoint.get('requested_formats') or checkpoint.get('document_request')))

    async def stage(self,task_id,attempt_id,contract_version,revision_id,review_check_id,*,complete=True,explicit_retry=False):
        if self.translation is None:
            raise PublicationBlocked('CLAUDE_TRANSLATION_SERVICE_REQUIRED')
        route=self.translation.router.lock(task_id,attempt_id)
        if route.route_policy=='native':
            return super().stage(task_id,attempt_id,contract_version,revision_id,review_check_id)
        with closing(self.database.connect()) as connection:
            task=self.translation.router.require_current(connection,route)
            checkpoint=checkpoint_for(task)
            if task['state']!='OUTPUT_PREPARING' or checkpoint.get('current_revision_id')!=revision_id or checkpoint.get('stale') or checkpoint.get('publication_blocked'):
                raise PublicationBlocked('OUTPUT_STATE_OR_CURRENT_REVISION_REQUIRED')
            review=self._source_review(connection,task,revision_id,review_check_id)
        translated=await self.output.prepare(task_id,attempt_id,revision_id,complete=complete,explicit_retry=explicit_retry)
        if translated.status!='READY':
            with closing(self.database.connect()) as connection,transaction(connection):
                task=self.translation.router.require_current(connection,route); checkpoint=checkpoint_for(task)
                checkpoint['language_output']={'source_revision_id':revision_id,'job_id':translated.job_id,'status':translated.status}
                connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task_id,attempt_id))
                enqueue_event(connection,task_id,attempt_id,'input.required' if translated.status=='NEEDS_INPUT' else 'request.failed',
                    {'prompt_code':'ambiguous_goal'} if translated.status=='NEEDS_INPUT' else {'error_code':'VALIDATION_FAILED'},
                    deduplication_key=f'translation-failure:{translated.job_id}')
            raise PublicationBlocked('OUTPUT_TRANSLATION_'+translated.status)
        zh_id='translation-'+translated.job_id; data=translated.text.encode(); sha=translated.target_sha256
        artifact=ArtifactVersion(id=zh_id,task_id=task_id,artifact_kind='answer',language='zh-CN',immutable_uri=self.store.uri_for(sha),byte_sha256=sha,
            canonical_content_sha256=sha,source_version_id=revision_id,origin_authors=['A','B'],canonical_issued_by='B',reviewed_by=['A','B'],rendered_by='none',a_response_ref=None,
            dependencies=[ArtifactDependency(artifact_version_id=revision_id,relationship='translation_source')])
        with closing(self.database.connect()) as connection:
            if connection.execute('SELECT id FROM artifact_revisions WHERE id=?',(zh_id,)).fetchone() is None:
                store_artifact(connection,self.store,data,artifact,attempt_id=attempt_id,provenance={'translation_job_id':translated.job_id,'source_sha256':translated.source_sha256,'qa_id':translated.qa_id,'translator':'B'})
        with closing(self.database.connect()) as connection,transaction(connection):
            task=self.translation.router.require_current(connection,route)
            if self._source_review(connection,task,revision_id,review_check_id)!=review:
                raise PublicationBlocked('REVIEW_CHANGED_DURING_TRANSLATION')
            if not is_current_revision(connection,task_id,attempt_id,revision_id): raise PublicationBlocked('CURRENT_SOURCE_REQUIRED')
            checkpoint=checkpoint_for(task)
            checkpoint.pop('public_release',None); checkpoint.pop('release_registry',None)
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task_id,attempt_id))
            activate_revision(connection,self.store,task_id,attempt_id,'answer.translation',zh_id,{'answer':revision_id})
            task=require_current_attempt(connection,task_id,attempt_id,contract_version); checkpoint=checkpoint_for(task)
            checkpoint['current_revision_id']=zh_id
            checkpoint['language_output']={'source_revision_id':revision_id,'job_id':translated.job_id,'status':'READY','qa_id':translated.qa_id}
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task_id,attempt_id))
            fence=snapshot_fence(connection,task_id,attempt_id,[revision_id,zh_id]); approval='release-'+uuid4().hex
            register_release_gate(connection,task_id,attempt_id,contract_version,zh_id,approval,route.id)
            task=require_current_attempt(connection,task_id,attempt_id); checkpoint=checkpoint_for(task)
            checkpoint['public_release']={'revision_id':zh_id,'source_revision_id':revision_id,'translation_job_id':translated.job_id,'qa_id':translated.qa_id,
                'approval_id':approval,'message_id':uuid4().hex,'sha256':sha,'review_check_id':review_check_id,'dependency_fence':fence,'review_snapshot':review}
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task_id,attempt_id))
        return approval

    def publish(self,task_id,attempt_id,contract_version):
        route=self.translation.router.lock(task_id,attempt_id)
        if route.route_policy=='native': return super().publish(task_id,attempt_id,contract_version)
        with closing(self.database.connect()) as connection,transaction(connection):
            task=self.translation.router.require_current(connection,route)
            return self.publish_in_transaction(connection,task)

    def publish_in_transaction(self,connection,task,*,bundle_id=None):
        """Document publisher calls after verifying its full bundle in this transaction."""
        if not connection.in_transaction: raise PublicationBlocked('PUBLICATION_TRANSACTION_REQUIRED')
        checkpoint=checkpoint_for(task); release=checkpoint.get('public_release'); task_id=task['task_id']; attempt_id=task['attempt_id']
        if task['state']=='PUBLISHED': return dict(task_id=task_id,attempt_id=attempt_id,state='PUBLISHED')
        if task['state']!='READY' or task['cancel_requested'] or checkpoint.get('stale') or checkpoint.get('publication_blocked'):
            raise PublicationBlocked('READY_CURRENT_UNCANCELLED_REQUIRED')
        validate_release_gate(connection,task,checkpoint)
        if not isinstance(release,dict) or not release.get('translation_job_id'): raise PublicationBlocked('TRANSLATED_RELEASE_REQUIRED')
        require_publication_fence(connection,task_id,attempt_id,release['dependency_fence'])
        review=self._source_review(connection,task,release['source_revision_id'],release['review_check_id'])
        if review!=release['review_snapshot']: raise PublicationBlocked('STAGED_REVIEW_CHANGED')
        if review['requires_bundle']:
            if not bundle_id: raise PublicationBlocked('COMPLETE_DELIVERY_BUNDLE_REQUIRED')
            # The documents lane verifies formats/provenance and supplies its
            # immutable bundle identifier in the same writer transaction.
            try: bundle=connection.execute('SELECT * FROM delivery_bundles WHERE id=? AND task_id=? AND attempt_id=?',(bundle_id,task_id,attempt_id)).fetchone()
            except Exception as exc: raise PublicationBlocked('DELIVERY_PUBLISHER_UNAVAILABLE') from exc
            if bundle is None or bundle['state'] not in ('VERIFIED','PUBLISHED'): raise PublicationBlocked('COMPLETE_DELIVERY_BUNDLE_REQUIRED')
        content=validate_translation_release(connection,self.store,task,release)
        connection.execute("UPDATE task_runs SET state='PUBLISHED',completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE task_id=? AND attempt_id=?",(task_id,attempt_id))
        event=enqueue_event(connection,task_id,attempt_id,'answer.published',{'release_id':release['approval_id']},
            deduplication_key=f'publish-answer:{task_id}:{attempt_id}:{release["revision_id"]}',
            public_payload=dict(message_id=release['message_id'],text=content.decode(),language='zh-CN',content_version_id=release['revision_id'],approval_id=release['approval_id']))
        public=PublicEvent.model_validate_json(event['public_event_json']).model_dump(mode='json')
        digest=hashlib.sha256(json.dumps(public,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        frozen=dict(event_id=event['event_id'],task_id=task_id,attempt_id=attempt_id,contract_version=task['contract_version'],artifact_version_id=release['revision_id'],
            artifact_sha256=release['sha256'],route_snapshot_id=json.loads(task['route_snapshot_json'])['id'],public_event_sha256=digest,approval_id=release['approval_id'],
            review_check_id=release['review_check_id'],published_via='answer_publisher_v1',translation_job_id=release['translation_job_id'],source_revision_id=release['source_revision_id'],qa_id=release['qa_id'])
        connection.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES (?,?,?,?,'release.publication','pass',?,?)",('publication-'+event['event_id'],task_id,attempt_id,release['revision_id'],task['contract_version'],json.dumps(frozen)))
        checkpoint['public_release']['event_id']=event['event_id']
        connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task_id,attempt_id))
        turn=connection.execute('SELECT conversation_id FROM turns WHERE id=?',(task['turn_id'],)).fetchone()
        source=connection.execute('SELECT immutable_uri,byte_sha256 FROM artifact_revisions WHERE id=?',(release['source_revision_id'],)).fetchone()
        connection.execute('INSERT OR IGNORE INTO bilingual_history(id,conversation_id,task_id,turn_id,source_role,language,raw_content_ref,content_sha256,parent_message_id,route_snapshot_id,visibility,english_ref,english_sha256,job_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (release['message_id'],turn[0],task_id,task['turn_id'],'assistant','zh-CN',self.store.uri_for(release['sha256']),release['sha256'],release['source_revision_id'],frozen['route_snapshot_id'],'user',source['immutable_uri'],source['byte_sha256'],release['translation_job_id']))
        return dict(task_id=task_id,attempt_id=attempt_id,state='PUBLISHED',event_id=event['event_id'])


def validate_translation_release(connection,store,task,release,*,historical=False):
    """Public projection uses the same byte/job/QA binding check."""
    job=connection.execute('SELECT * FROM translation_jobs WHERE id=? AND task_id=? AND attempt_id=?',(release.get('translation_job_id'),task['task_id'],task['attempt_id'])).fetchone()
    source=connection.execute('SELECT * FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?',(release.get('source_revision_id'),task['task_id'],task['attempt_id'])).fetchone()
    qa=connection.execute("SELECT * FROM checks WHERE id=? AND job_id=? AND check_kind='translation.qa' AND result='pass'",(release.get('qa_id'),release.get('translation_job_id'))).fetchone()
    route=json.loads(task['route_snapshot_json']); content=read_artifact(connection,store,release['revision_id'])
    if (job is None or source is None or qa is None or (job['status']!='READY' and not (historical and job['status']=='STALE')) or job['route_snapshot_id']!=route['id']
            or job['source_version_id']!=source['id'] or job['source_sha256']!=source['byte_sha256']
            or job['target_sha256']!=hashlib.sha256(content).hexdigest() or job['target_sha256']!=release['sha256']
            or job['qa_id']!=qa['id'] or (json.loads(qa['details_json']).get('stale') and not historical)
            or (not historical and connection.execute('SELECT 1 FROM route_invalidations WHERE route_snapshot_id=?',(route['id'],)).fetchone())):
        raise PublicationBlocked('TRANSLATION_RELEASE_BINDING_MISMATCH')
    details=json.loads(qa['details_json'])
    if (any(details.get(key)!='pass' for key in ('coverage_result','protected_span_result','numeric_entity_result'))
            or details.get('severity') in ('major','critical') or any(f.get('severity') in ('major','critical') for f in details.get('semantic_findings',[]))):
        raise PublicationBlocked('TRANSLATION_QA_NOT_PASSED')
    read_artifact(connection,store,source['id'])
    artifact=connection.execute('SELECT * FROM artifact_revisions WHERE id=?',(release['revision_id'],)).fetchone()
    if artifact['language']!='zh-CN' or artifact['source_version_id']!=source['id']:
        raise PublicationBlocked('TRANSLATION_ARTIFACT_SOURCE_MISMATCH')
    return content
