"""Persist complete immutable files before atomically exposing answer + bundle."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4
from dataclasses import replace

from app.contracts.artifacts import ArtifactVersion, ArtifactDependency, ArtifactPair, DeliveryBundle
from app.contracts.events import PublicEvent
from app.contracts.tasks import validate_contract, contract_digest, evaluate_review
from app.runtime.outbox import enqueue_event
from app.runtime.state_machine import require_current_attempt, checkpoint_for
from app.storage.blobs import BlobStore, store_artifact, read_artifact
from app.storage.database import Database, transaction
from app.storage.revisions import activate_revision, is_current_revision, snapshot_fence, require_publication_fence
from .canonical import require_canonical
from .model import digest, json_bytes
from .parse import parse_document
from .render import DocumentRenderer, verify_pdf, _block_text, _compact
from .translate import read_model, persist_model, require_translation


CONTENT_TYPES={'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'markdown':'text/markdown; charset=utf-8','csv':'text/csv; charset=utf-8','python':'text/x-python; charset=utf-8','png':'image/png'}
EXTENSIONS={'markdown':'md','python':'py'}


def _review(connection, task, source_id, review_id, evidence_root):
    row=connection.execute("SELECT * FROM checks WHERE id=? AND task_id=? AND attempt_id=? AND artifact_version_id=? AND check_kind='A.review' AND result='pass'",
        (review_id,task['task_id'],task['attempt_id'],source_id)).fetchone()
    if row is None or row['check_version']!=task['contract_version']: raise ValueError('CURRENT_A_REVIEW_REQUIRED')
    details=json.loads(row['details_json']); contract=validate_contract(details['contract']); route=json.loads(task['route_snapshot_json'])
    checkpoint=checkpoint_for(task); sha=contract_digest(contract)
    if ((contract.task_id,contract.attempt_id,contract.contract_version,contract.route_snapshot_id)!=(task['task_id'],task['attempt_id'],task['contract_version'],route['id'])
            or details.get('stale') or details['decision'].get('revision_id')!=source_id
            or checkpoint.get('task_contract') is None or contract_digest(checkpoint['task_contract'])!=sha
            or checkpoint.get('workflow',{}).get('contract_sha256')!=sha
            or not evaluate_review(contract,details['decision'],evidence_root).eligible_for_output):
        raise ValueError('CURRENT_PINNED_REVIEW_EVIDENCE_REQUIRED')
    return {'contract_sha256':sha,'review_sha256':digest(json_bytes(details))}


def _logical(connection,task_id,attempt_id,revision_id):
    graph=checkpoint_for(connection.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?',(task_id,attempt_id)).fetchone())['dependency_graph']
    try: return next(k for k,v in graph['nodes'].items() if v['revision_id']==revision_id and not v['stale'])
    except StopIteration as error: raise ValueError('BUNDLE_DEPENDENCY_NOT_CURRENT') from error


def _verify_rendered_bytes(result,model,format,evidence_dir):
    """The publisher verifies byte products even when a renderer says PASS."""
    if (result.format,result.language)!=(format,model.language) or not isinstance(result.data,bytes):
        raise ValueError('RENDER_BYTES_FORMAT_OR_LANGUAGE_MISMATCH')
    if result.qa.get('byte_sha256')!=digest(result.data): raise ValueError('RENDER_BYTES_HASH_MISMATCH')
    try:
        if format=='pdf':
            qa,images=verify_pdf(result.data,model,evidence_dir)
            return replace(result,qa={**result.qa,**qa},page_images=images)
        parsed=parse_document(result.data,format,source_version_id=model.source_version_id,language=model.language)
        if not parsed.complete: raise ValueError('RENDER_BYTES_PARSE_INCOMPLETE')
        if format=='markdown':
            if [(b.kind,b.content,b.metadata) for b in parsed.blocks]!=[(b.kind,b.content,b.metadata) for b in model.blocks]: raise ValueError('RENDER_BYTES_CONTENT_MISSING')
            return result
        expected=[_compact(_block_text(b)) for b in model.blocks if b.kind!='separator']
        if [_compact(b.content) for b in parsed.blocks]!=expected or result.preview_pdf is None:
            raise ValueError('RENDER_BYTES_DOCX_CONTENT_OR_VISUAL_MISSING')
        qa,images=verify_pdf(result.preview_pdf,model,evidence_dir)
        return replace(result,qa={**result.qa,**qa,'byte_sha256':digest(result.data),
            'preview_sha256':digest(result.preview_pdf)},page_images=images)
    except (ValueError,RuntimeError,KeyError,OSError) as error:
        raise ValueError('RENDER_BYTES_INVALID:'+type(error).__name__) from error


class BundlePublisher:
    def __init__(self,database_path,evidence_root):
        self.database=Database(database_path); self.store=BlobStore(self.database.path.parent/'blobs')
        self.evidence_root=Path(evidence_root).resolve()
        self.evidence_root.relative_to(self.database.path.parent.resolve())
        self.evidence_root.mkdir(parents=True,exist_ok=True)

    def stage(self,task_id,attempt_id,contract_version,source_version_id,requested_formats,*,title,
            translation_revision_id=None,review_check_id,renderer=None,extra_artifact_ids=()):
        formats=list(requested_formats)
        if not formats or len(formats)!=len(set(formats)) or any(f not in ('markdown','pdf','docx') for f in formats):
            raise ValueError('EXACT_REQUESTED_FORMATS_REQUIRED')
        if not isinstance(title,str) or not title.strip() or len(title)>200: raise ValueError('BUNDLE_TITLE_INVALID')
        renderer=renderer or DocumentRenderer(); bid='bundle-'+uuid4().hex
        with closing(self.database.connect()) as c:
            task=require_current_attempt(c,task_id,attempt_id,contract_version); checkpoint=checkpoint_for(task)
            release=checkpoint.get('public_release'); route=json.loads(task['route_snapshot_json'])
            if task['state']!='OUTPUT_PREPARING' or task['cancel_requested'] or checkpoint.get('stale') or checkpoint.get('publication_blocked'):
                raise ValueError('OUTPUT_CURRENT_UNCANCELLED_REQUIRED')
            if (not isinstance(release,dict) or (release.get('source_revision_id') or release.get('revision_id'))!=source_version_id
                    or release.get('review_check_id')!=review_check_id): raise ValueError('ANSWER_BUNDLE_SAME_RELEASE_REQUIRED')
            require_canonical(c,self.store,source_version_id)
            review=_review(c,task,source_version_id,review_check_id,self.evidence_root)
            if not is_current_revision(c,task_id,attempt_id,source_version_id): raise ValueError('BUNDLE_SOURCE_STALE')
            # The prior answer fence must be valid before this publisher adds
            # deterministic render descendants. It cannot bless a stale reply.
            with transaction(c): require_publication_fence(c,task_id,attempt_id,release['dependency_fence'])
            original_release=json_bytes(release)
            source_row=c.execute('SELECT * FROM artifact_revisions WHERE id=?',(source_version_id,)).fetchone()
            source_model=parse_document(read_artifact(c,self.store,source_version_id),'markdown',source_version_id=source_version_id,language=source_row['language'])
            if not source_model.complete: raise ValueError('DOCUMENT_PARSE_INCOMPLETE')
            persist_model(c,source_model,source_version_id)
            models=[(source_version_id,source_model)]
            if route['model_family']=='claude':
                if not translation_revision_id: raise ValueError('COMPLETE_BILINGUAL_TRANSLATION_REQUIRED')
                translated=require_translation(c,self.store,translation_revision_id,source_version_id)
                if not is_current_revision(c,task_id,attempt_id,translation_revision_id): raise ValueError('BUNDLE_TRANSLATION_STALE')
                models.append((translation_revision_id,translated))
            elif translation_revision_id is not None: raise ValueError('GPT_EXPLICIT_TRANSLATION_TASK_REQUIRED')
            for aid in extra_artifact_ids:
                row=c.execute('SELECT * FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?',(aid,task_id,attempt_id)).fetchone()
                if row is None or not is_current_revision(c,task_id,attempt_id,aid): raise ValueError('EXTRA_ARTIFACT_CURRENT_SCOPE_REQUIRED')
                read_artifact(c,self.store,aid)
        rendered=[]
        # Failed rendering may leave verified orphan blobs and page evidence;
        # it creates no bundle, head pointer, or public event.
        for format in formats:
            pair='pair-'+uuid4().hex if len(models)==2 else None
            for model_revision,model in models:
                result=renderer.render(model,format,evidence_dir=self.evidence_root/bid)
                self.store.put(result.data)
                if result.qa.get('status')!='pass': raise ValueError('RENDER_QA_REQUIRED:'+result.qa.get('code','unknown'))
                if result.qa.get('content_sha256')!=model.content_sha256: raise ValueError('RENDER_MODEL_BINDING_MISMATCH')
                result=_verify_rendered_bytes(result,model,format,self.evidence_root/bid)
                rendered.append((model_revision,model,result,pair))
        staged=[]; pairs=[]
        for model_revision,model,result,pair in rendered:
            aid='render-'+uuid4().hex; sha=digest(result.data); language=model.language
            upstream={model_revision,source_version_id}
            artifact=ArtifactVersion(id=aid,task_id=task_id,artifact_kind=result.format,language=language,
                immutable_uri=self.store.uri_for(sha),byte_sha256=sha,canonical_content_sha256=model.content_sha256,
                source_version_id=source_version_id,origin_authors=['A'] if language==source_model.language else ['A','B'],
                canonical_issued_by='C',reviewed_by=[],rendered_by='C:'+result.qa['code'],a_response_ref=None,
                dependencies=[ArtifactDependency(artifact_version_id=v,relationship='render_source') for v in sorted(upstream)])
            with closing(self.database.connect()) as c:
                store_artifact(c,self.store,result.data,artifact,attempt_id=attempt_id,
                    provenance={'model_revision_id':model_revision,'source_version_id':source_version_id,'qa':result.qa})
            preview=None
            if result.preview_pdf is not None:
                psha=digest(result.preview_pdf); preview='preview-'+uuid4().hex
                p=ArtifactVersion(id=preview,task_id=task_id,artifact_kind='pdf',language=language,
                    immutable_uri=self.store.uri_for(psha),byte_sha256=psha,canonical_content_sha256=model.content_sha256,
                    source_version_id=source_version_id,origin_authors=artifact.origin_authors,canonical_issued_by='C',reviewed_by=[],
                    rendered_by='C:docx_preview',a_response_ref=None,dependencies=[ArtifactDependency(artifact_version_id=aid,relationship='docx_preview')])
                with closing(self.database.connect()) as c:
                    store_artifact(c,self.store,result.preview_pdf,p,attempt_id=attempt_id,provenance={'docx_artifact_id':aid})
            qa_id='render-qa-'+uuid4().hex
            qa={**result.qa,'source_version_id':source_version_id,'model_revision_id':model_revision,
                'render_artifact_id':aid,'requested_format':result.format,'language':language,
                'page_images_sha256':[self.store.put(path.read_bytes()).sha256 for path in result.page_images]}
            staged.append(dict(artifact_id=aid,artifact_pair_id=pair,format=result.format,language=language,
                file_name=f'report.{source_version_id[-12:]}.{language}.{EXTENSIONS.get(result.format,result.format)}',
                qa_id=qa_id,qa=qa,preview_artifact_id=preview,model_revision_id=model_revision))
        for format in formats:
            group=[s for s in staged if s['format']==format]
            if len(group)==2:
                pairs.append(ArtifactPair(artifact_pair_id=group[0]['artifact_pair_id'],format=format,source_version_id=source_version_id,
                    english_artifact_id=next(s['artifact_id'] for s in group if s['language']=='en'),
                    chinese_artifact_id=next(s['artifact_id'] for s in group if s['language']=='zh-CN')))
        with closing(self.database.connect()) as c,transaction(c):
            task=require_current_attempt(c,task_id,attempt_id,contract_version); checkpoint=checkpoint_for(task)
            if (task['cancel_requested'] or checkpoint.get('stale') or checkpoint.get('publication_blocked')
                    or json_bytes(checkpoint.get('public_release'))!=original_release): raise ValueError('BUNDLE_STAGE_VERSION_CHANGED')
            require_publication_fence(c,task_id,attempt_id,release['dependency_fence'])
            if _review(c,task,source_version_id,review_check_id,self.evidence_root)!=review: raise ValueError('BUNDLE_REVIEW_CHANGED')
            extra=[]
            for aid in extra_artifact_ids:
                row=c.execute('SELECT * FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?',(aid,task_id,attempt_id)).fetchone()
                data=read_artifact(c,self.store,aid)
                format=row['artifact_kind']
                if format=='csv':
                    import csv,io
                    records=list(csv.DictReader(io.StringIO(data.decode())))
                    if not records: raise ValueError('EXTRA_CSV_EMPTY')
                elif format=='python': compile(data.decode(),'<artifact>','exec')
                elif format=='png':
                    import pymupdf
                    if not data.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('EXTRA_PNG_INVALID')
                    image=pymupdf.Pixmap(data)
                    if image.width<1 or image.height<1: raise ValueError('EXTRA_PNG_INVALID')
                else: raise ValueError('EXTRA_FORMAT_UNSUPPORTED')
                if not is_current_revision(c,task_id,attempt_id,aid): raise ValueError('EXTRA_ARTIFACT_STALE')
                qid='extra-qa-'+uuid4().hex
                c.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES (?,?,?,?,'document.extra','pass',?,?)",
                    (qid,task_id,attempt_id,aid,contract_version,json_bytes({'byte_sha256':digest(data),'format':format,'actual_bytes_verified':True}).decode()))
                extra.append(dict(artifact_id=aid,artifact_pair_id=None,format=format,language=row['language'],
                    file_name=f'source.{aid[-12:]}.{EXTENSIONS.get(format,format)}',qa_id=qid,preview_artifact_id=None))
            for s in staged:
                c.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES (?,?,?,?,'document.render','pass',?,?)",
                    (s['qa_id'],task_id,attempt_id,s['artifact_id'],contract_version,json_bytes(s['qa']).decode()))
                upstream={_logical(c,task_id,attempt_id,v):v for v in {s['model_revision_id'],source_version_id}}
                activate_revision(c,self.store,task_id,attempt_id,'delivery.'+s['format']+'.'+s['language'],s['artifact_id'],upstream)
                if s['preview_artifact_id']:
                    activate_revision(c,self.store,task_id,attempt_id,'preview.'+s['format']+'.'+s['language'],s['preview_artifact_id'],
                        {'delivery.'+s['format']+'.'+s['language']:s['artifact_id'],
                         _logical(c,task_id,attempt_id,source_version_id):source_version_id})
            members=staged+extra
            revisions=[source_version_id]+([translation_revision_id] if translation_revision_id else [])+[s['artifact_id'] for s in members]+[s['preview_artifact_id'] for s in staged if s['preview_artifact_id']]
            fence=snapshot_fence(c,task_id,attempt_id,revisions)
            task=require_current_attempt(c,task_id,attempt_id); checkpoint=checkpoint_for(task)
            release=checkpoint['public_release']
            release['dependency_fence']=snapshot_fence(c,task_id,attempt_id,list(release['dependency_fence']['revisions']))
            checkpoint['public_release']=release
            c.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task_id,attempt_id))
            bundle=DeliveryBundle(id=bid,task_id=task_id,turn_id=task['turn_id'],spec_version='1.0',route_snapshot_id=route['id'],
                source_version_ids=[source_version_id],translation_version_ids=[translation_revision_id] if translation_revision_id else [],
                format_pairs=pairs,qa_ids=[s['qa_id'] for s in members],approval_id=release['approval_id'],state='STAGING',published_at=None)
            manifest={'bundle':bundle.model_dump(mode='json'),'members':members,'review':review}
            serialized=json_bytes(manifest)
            conversation=c.execute('SELECT conversation_id FROM turns WHERE id=?',(task['turn_id'],)).fetchone()[0]
            c.execute('INSERT INTO delivery_bundles(id,task_id,attempt_id,conversation_id,turn_id,source_version_id,route_snapshot_id,title,state,bundle_json,manifest_sha256,requested_formats_json,dependency_fence_json,approval_id,review_check_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (bid,task_id,attempt_id,conversation,task['turn_id'],source_version_id,route['id'],title,'STAGING',serialized.decode(),digest(serialized),json.dumps(formats),json.dumps(fence),release['approval_id'],review_check_id))
            for s in members:
                c.execute('INSERT INTO delivery_bundle_artifacts(bundle_id,artifact_id,source_version_id,artifact_pair_id,format,language,file_name,qa_check_id,preview_artifact_id) VALUES (?,?,?,?,?,?,?,?,?)',
                    (bid,s['artifact_id'],source_version_id,s['artifact_pair_id'],s['format'],s['language'],s['file_name'],s['qa_id'],s['preview_artifact_id']))
            _verify_bundle(c,self.store,bid,self.evidence_root,current=True)
            c.execute("UPDATE delivery_bundles SET state='VERIFIED' WHERE id=?",(bid,))
        return bid

    def publish(self,bundle_id,*,answer_releaser):
        with closing(self.database.connect()) as c,transaction(c):
            row=c.execute('SELECT * FROM delivery_bundles WHERE id=?',(bundle_id,)).fetchone()
            if row is None: raise ValueError('BUNDLE_NOT_FOUND')
            if row['state']=='PUBLISHED': return bundle_card(c,self.store,row)
            if row['state']!='VERIFIED': raise ValueError('VERIFIED_BUNDLE_REQUIRED')
            task=require_current_attempt(c,row['task_id'],row['attempt_id'])
            from app.operations.controller import assert_publication_allowed
            assert_publication_allowed(c,task)
            if task['state']!='READY' or task['cancel_requested']: raise ValueError('READY_UNCANCELLED_BUNDLE_REQUIRED')
            _verify_bundle(c,self.store,bundle_id,self.evidence_root,current=True)
            checkpoint=checkpoint_for(task); release=checkpoint.get('public_release',{})
            if (release.get('approval_id')!=row['approval_id'] or (release.get('source_revision_id') or release.get('revision_id'))!=row['source_version_id']
                    or release.get('review_check_id')!=row['review_check_id']): raise ValueError('ANSWER_BUNDLE_APPROVAL_MISMATCH')
            if not callable(answer_releaser): raise ValueError('ATOMIC_ANSWER_RELEASER_REQUIRED')
            result=answer_releaser(c,task,bundle_id=bundle_id)
            if result.get('state')!='PUBLISHED': raise ValueError('ANSWER_NOT_PUBLISHED')
            now=datetime.now(timezone.utc).isoformat()
            c.execute("UPDATE delivery_bundles SET state='PUBLISHED',published_at=? WHERE id=?",(now,bundle_id))
            c.execute('INSERT INTO delivery_bundle_heads(turn_id,bundle_id) VALUES (?,?) ON CONFLICT(turn_id) DO UPDATE SET bundle_id=excluded.bundle_id',(row['turn_id'],bundle_id))
            row=c.execute('SELECT * FROM delivery_bundles WHERE id=?',(bundle_id,)).fetchone(); card=bundle_card(c,self.store,row,require_publication=False)
            payload={'bundle_id':bundle_id,'version_id':row['source_version_id'],'artifacts':[
                {k:a[k] for k in ('artifact_id','artifact_pair_id','format','language','file_name','size_bytes')} for a in card['artifacts']]}
            event=enqueue_event(c,row['task_id'],row['attempt_id'],'artifacts.published',{'bundle_id':bundle_id,'approval_id':row['approval_id']},
                deduplication_key='publish-bundle:'+bundle_id,public_payload=payload)
            c.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES (?,?,?,?,'bundle.publication','pass',?,?)",
                ('bundle-publication-'+event['event_id'],row['task_id'],row['attempt_id'],row['source_version_id'],task['contract_version'],
                    json_bytes({'event_id':event['event_id'],'bundle_id':bundle_id,'manifest_sha256':row['manifest_sha256'],'approval_id':row['approval_id'],
                        'public_event_sha256':digest(json_bytes(PublicEvent.model_validate_json(event['public_event_json']).model_dump(mode='json')))}).decode()))
            return card


def _verify_bundle(c,store,bundle_id,evidence_root,*,current):
    row=c.execute('SELECT * FROM delivery_bundles WHERE id=?',(bundle_id,)).fetchone()
    if row is None or digest(row['bundle_json'].encode())!=row['manifest_sha256']: raise ValueError('BUNDLE_MANIFEST_CHANGED')
    manifest=json.loads(row['bundle_json']); bundle=DeliveryBundle.model_validate(manifest['bundle'])
    if (bundle.task_id,bundle.turn_id,bundle.route_snapshot_id,bundle.source_version_ids,bundle.approval_id)!=(row['task_id'],row['turn_id'],row['route_snapshot_id'],[row['source_version_id']],row['approval_id']):
        raise ValueError('BUNDLE_SCOPE_OR_VERSION_MISMATCH')
    require_canonical(c,store,row['source_version_id'])
    if bundle.translation_version_ids: require_translation(c,store,bundle.translation_version_ids[0],row['source_version_id'],historical=not current)
    task=c.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?',(row['task_id'],row['attempt_id'])).fetchone()
    if current:
        require_publication_fence(c,row['task_id'],row['attempt_id'],json.loads(row['dependency_fence_json']))
        if _review(c,task,row['source_version_id'],row['review_check_id'],evidence_root)!=manifest['review']:
            raise ValueError('BUNDLE_APPROVAL_CHANGED')
    rows=c.execute('SELECT * FROM delivery_bundle_artifacts WHERE bundle_id=?',(bundle_id,)).fetchall()
    expected=manifest['members']
    if {r['artifact_id'] for r in rows}!={s['artifact_id'] for s in expected}: raise ValueError('BUNDLE_MEMBERSHIP_CHANGED')
    formats=json.loads(row['requested_formats_json']); route=json.loads(task['route_snapshot_json'])
    languages=['en','zh-CN'] if route['model_family']=='claude' else [c.execute('SELECT language FROM artifact_revisions WHERE id=?',(row['source_version_id'],)).fetchone()[0]]
    for format in formats:
        selected=[r for r in rows if r['format']==format]
        if sorted(r['language'] for r in selected)!=sorted(languages): raise ValueError('COMPLETE_FORMAT_LANGUAGE_SET_REQUIRED')
        if len(languages)==2:
            pair=next((p for p in bundle.format_pairs if p.format==format),None)
            if pair is None or pair.source_version_id!=row['source_version_id'] or {pair.english_artifact_id,pair.chinese_artifact_id}!={r['artifact_id'] for r in selected} or {r['artifact_pair_id'] for r in selected}!={pair.artifact_pair_id}:
                raise ValueError('FORMAT_PAIR_VERSION_MISMATCH')
    for member in rows:
        frozen=next(s for s in expected if s['artifact_id']==member['artifact_id'])
        if any(member[key]!=frozen[key if key!='qa_check_id' else 'qa_id'] for key in ('format','language','file_name','artifact_pair_id','preview_artifact_id','qa_check_id')):
            raise ValueError('BUNDLE_MEMBER_METADATA_CHANGED')
        artifact=c.execute('SELECT * FROM artifact_revisions WHERE id=?',(member['artifact_id'],)).fetchone()
        if (artifact['task_id'],artifact['attempt_id'],member['source_version_id'])!=(row['task_id'],row['attempt_id'],row['source_version_id']): raise ValueError('BUNDLE_ARTIFACT_SCOPE_MISMATCH')
        data=read_artifact(c,store,member['artifact_id'])
        qa=c.execute("SELECT * FROM checks WHERE id=? AND artifact_version_id=? AND result='pass'",(member['qa_check_id'],member['artifact_id'])).fetchone()
        if qa is None or qa['task_id']!=row['task_id'] or qa['attempt_id']!=row['attempt_id'] or qa['check_version']!=task['contract_version']: raise ValueError('BUNDLE_QA_REQUIRED')
        proof=json.loads(qa['details_json'])
        if proof.get('byte_sha256')!=digest(data) or (current and proof.get('stale')): raise ValueError('BUNDLE_QA_BYTES_MISMATCH')
        if member['format'] in ('pdf','docx','markdown'):
            original_proof={k:v for k,v in proof.items() if current or k not in ('stale','invalidated_by_graph_version')}
            if original_proof!=frozen['qa'] or artifact['source_version_id']!=row['source_version_id']: raise ValueError('BUNDLE_RENDER_QA_CHANGED')
            model=read_model(c,proof['model_revision_id'])
            if proof.get('content_sha256')!=model.content_sha256: raise ValueError('BUNDLE_RENDER_CONTENT_MISMATCH')
            for sha in proof.get('page_images_sha256',[]): store.read(sha)
        if member['preview_artifact_id']: read_artifact(c,store,member['preview_artifact_id'])
    return row,manifest,rows


def bundle_card(c,store,row,*,require_publication=True):
    row,manifest,members=_verify_bundle(c,store,row['id'],None,current=False)
    if row['state']!='PUBLISHED': raise ValueError('PUBLISHED_BUNDLE_REQUIRED')
    if require_publication:
        publication=c.execute("SELECT * FROM checks WHERE task_id=? AND attempt_id=? AND check_kind='bundle.publication' AND result='pass' AND json_extract(details_json,'$.bundle_id')=?",
            (row['task_id'],row['attempt_id'],row['id'])).fetchone()
        if publication is None or json.loads(publication['details_json']).get('manifest_sha256')!=row['manifest_sha256']:
            raise ValueError('BUNDLE_PUBLICATION_PROOF_REQUIRED')
    historical=not is_current_revision(c,row['task_id'],row['attempt_id'],row['source_version_id'])
    artifacts=[]
    for member in members:
        artifact=c.execute('SELECT * FROM artifact_revisions WHERE id=?',(member['artifact_id'],)).fetchone()
        preview_format='pdf' if member['format']=='docx' and member['preview_artifact_id'] else member['format']
        preview=member['format'] in ('pdf','markdown','png') or member['preview_artifact_id'] is not None
        artifacts.append(dict(artifact_id=member['artifact_id'],artifact_pair_id=member['artifact_pair_id'],format=member['format'],language=member['language'],
            file_name=member['file_name'],size_bytes=artifact['size_bytes'],sha256=artifact['byte_sha256'],preview_available=preview,
            preview_content_type='text/plain; charset=utf-8' if preview_format=='markdown' else CONTENT_TYPES.get(preview_format) if preview else None))
    return dict(bundle_id=row['id'],version_id=row['source_version_id'],turn_id=row['turn_id'],title=row['title'],approval_id=row['approval_id'],
        published_at=row['published_at'],historical=historical,format_pairs=manifest['bundle']['format_pairs'],artifacts=artifacts)


def frozen_event_payload(connection,store,event_id):
    """Root public projection calls this for the exact immutable outbox event."""
    event=connection.execute("SELECT * FROM outbox_events WHERE event_id=? AND kind='artifacts.published'",(event_id,)).fetchone()
    check=connection.execute("SELECT * FROM checks WHERE id=? AND check_kind='bundle.publication' AND result='pass'",('bundle-publication-'+event_id,)).fetchone()
    if event is None or check is None or event['public_event_json'] is None: return None
    proof=json.loads(check['details_json']); public=PublicEvent.model_validate_json(event['public_event_json']).model_dump(mode='json')
    if digest(json_bytes(public))!=proof.get('public_event_sha256'): return None
    row=connection.execute('SELECT * FROM delivery_bundles WHERE id=? AND conversation_id=? AND turn_id=? AND task_id=? AND attempt_id=?',
        (proof.get('bundle_id'),event['conversation_id'],event['turn_id'],event['task_id'],event['attempt_id'])).fetchone()
    if row is None or row['state']!='PUBLISHED' or row['approval_id']!=proof.get('approval_id'): return None
    envelope={'schema_version':'1.0','event_id':event_id,'conversation_id':event['conversation_id'],
        'turn_id':event['turn_id'],'task_id':event['task_id'],'attempt_id':event['attempt_id'],
        'sequence':event['conversation_sequence'],'kind':'artifacts.published'}
    if any(public.get(k)!=v for k,v in envelope.items()): return None
    if ((check['task_id'],check['attempt_id'],check['artifact_version_id'],check['check_version'])
            !=(event['task_id'],event['attempt_id'],row['source_version_id'],event['contract_version'])
            or proof.get('event_id')!=event_id or proof.get('manifest_sha256')!=row['manifest_sha256']): return None
    card=bundle_card(connection,store,row)
    expected={'bundle_id':row['id'],'version_id':row['source_version_id'],'artifacts':[{k:a[k] for k in ('artifact_id','artifact_pair_id','format','language','file_name','size_bytes')} for a in card['artifacts']]}
    if public['payload']!=expected or json.loads(event['internal_payload_json'])!={'bundle_id':row['id'],'approval_id':row['approval_id']}:
        return None
    return expected
