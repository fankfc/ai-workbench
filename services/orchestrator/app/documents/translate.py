"""Block translation through the persistent, independently checked B lane."""
from contextlib import closing
import json
from uuid import uuid4

from app.contracts.artifacts import ArtifactDependency, ArtifactVersion
from app.storage.blobs import BlobStore, read_artifact, store_artifact
from app.storage.database import Database, transaction
from app.storage.revisions import activate_revision, is_current_revision
from .canonical import require_canonical
from .model import DocumentModel, digest, json_bytes


def persist_model(connection, model, revision_id):
    data = json_bytes(model.model_dump(mode='json'))
    old = connection.execute('SELECT * FROM document_models WHERE revision_id=?', (revision_id,)).fetchone()
    if old:
        if old['model_sha256'] != digest(data): raise ValueError('DOCUMENT_MODEL_CHANGED')
        return
    connection.execute('INSERT INTO document_models(revision_id,source_version_id,model_json,model_sha256) VALUES (?,?,?,?)',
        (revision_id, model.source_version_id, data.decode(), digest(data)))


def read_model(connection, revision_id):
    row = connection.execute('SELECT * FROM document_models WHERE revision_id=?', (revision_id,)).fetchone()
    if row is None or digest(row['model_json'].encode()) != row['model_sha256']:
        raise ValueError('DOCUMENT_MODEL_UNAVAILABLE_OR_CHANGED')
    return DocumentModel.model_validate_json(row['model_json'])


class DocumentTranslator:
    def __init__(self, database_path, translation_service):
        self.database = Database(database_path)
        self.store = BlobStore(self.database.path.parent / 'blobs')
        self.service = translation_service

    async def translate(self, task_id, attempt_id, model, *, explicit_bilingual=True, logical_id='report_zh', glossary_version='1'):
        model = DocumentModel.model_validate(model.model_dump())
        if not model.complete: raise ValueError('DOCUMENT_PARSE_INCOMPLETE')
        with closing(self.database.connect()) as c:
            task = c.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?', (task_id, attempt_id)).fetchone()
            if task is None: raise ValueError('TASK_ATTEMPT_NOT_FOUND')
            route = json.loads(task['route_snapshot_json'])
            if route['model_family'] == 'gpt' and not explicit_bilingual: return None
            if route['model_family'] == 'gpt': raise ValueError('EXPLICIT_TRANSLATION_TASK_REQUIRED')
            require_canonical(c, self.store, model.source_version_id)
            if not is_current_revision(c, task_id, attempt_id, model.source_version_id):
                raise ValueError('DOCUMENT_SOURCE_STALE')
            persist_model(c, model, model.source_version_id)
        evidence, blocks = {}, []
        context = digest(json_bytes(model.model_dump(mode='json')))
        for source in model.blocks:
            if not source.translatable:
                blocks.append(source)
                evidence[source.block_id] = {'preserved': True, 'source_sha256': source.source_sha256,
                    'reason': source.preservation_reason}
                continue
            result = await self.service.translate(task_id=task_id, attempt_id=attempt_id, source=source.content,
                source_language=model.language, target_language='zh-CN', purpose='document_block',
                source_version_id=model.source_version_id, source_locator=source.source_locator,
                context_sha256=context, glossary_version=glossary_version, format='markdown')
            if result.status != 'READY' or not result.text or result.source_sha256 != source.source_sha256 or not result.qa_id:
                raise ValueError('DOCUMENT_TRANSLATION_NOT_READY:' + source.block_id)
            evidence[source.block_id] = {'job_id': result.job_id, 'qa_id': result.qa_id,
                'source_sha256': result.source_sha256, 'target_sha256': result.target_sha256,
                'source_version_id': model.source_version_id}
            blocks.append(source.model_copy(update={'content': result.text}))
        target = model.model_copy(update={'language': 'zh-CN', 'blocks': blocks, 'translation_evidence': evidence})
        revision_id = 'translation-' + uuid4().hex
        data = json_bytes(target.model_dump(mode='json')); sha = digest(data)
        artifact = ArtifactVersion(id=revision_id, task_id=task_id, artifact_kind='document_model', language='zh-CN',
            immutable_uri=self.store.uri_for(sha), byte_sha256=sha, canonical_content_sha256=target.content_sha256,
            source_version_id=model.source_version_id, origin_authors=['A', 'B'], canonical_issued_by='B',
            reviewed_by=[], rendered_by='none', a_response_ref=None,
            dependencies=[ArtifactDependency(artifact_version_id=model.source_version_id, relationship='translation_source')])
        with closing(self.database.connect()) as c:
            # A source change during the external calls prevents registration.
            if not is_current_revision(c, task_id, attempt_id, model.source_version_id): raise ValueError('DOCUMENT_SOURCE_STALE')
            store_artifact(c, self.store, data, artifact, attempt_id=attempt_id, provenance={'block_evidence': evidence})
            with transaction(c):
                persist_model(c, target, revision_id)
                require_translation(c, self.store, revision_id, model.source_version_id)
                graph = json.loads(c.execute('SELECT checkpoint_json FROM task_runs WHERE task_id=? AND attempt_id=?', (task_id, attempt_id)).fetchone()[0])['dependency_graph']
                logical = next(k for k, v in graph['nodes'].items() if v['revision_id'] == model.source_version_id)
                activate_revision(c, self.store, task_id, attempt_id, logical_id, revision_id, {logical: model.source_version_id})
        return {'revision_id': revision_id, 'source_version_id': model.source_version_id, 'model': target,
            'block_map': evidence, 'qa_ids': [v['qa_id'] for v in evidence.values() if 'qa_id' in v]}


def require_translation(connection, store, revision_id, source_version_id, *, historical=False):
    source, target = read_model(connection, source_version_id), read_model(connection, revision_id)
    if source.source_version_id != source_version_id or target.source_version_id != source_version_id or target.language != 'zh-CN':
        raise ValueError('TRANSLATION_SOURCE_VERSION_MISMATCH')
    data=read_artifact(connection, store, revision_id)
    artifact=connection.execute('SELECT * FROM artifact_revisions WHERE id=?',(revision_id,)).fetchone()
    if data!=json_bytes(target.model_dump(mode='json')) or artifact['canonical_content_sha256']!=target.content_sha256:
        raise ValueError('TRANSLATION_MODEL_BYTES_MISMATCH')
    if [b.block_id for b in source.blocks] != [b.block_id for b in target.blocks] or set(target.translation_evidence) != {b.block_id for b in source.blocks}:
        raise ValueError('TRANSLATION_BLOCK_COVERAGE_MISMATCH')
    for src, dst in zip(source.blocks, target.blocks):
        proof = target.translation_evidence[src.block_id]
        if (src.kind, src.parent_id, src.order, src.metadata, src.resource_ids) != (dst.kind, dst.parent_id, dst.order, dst.metadata, dst.resource_ids):
            raise ValueError('TRANSLATION_STRUCTURE_CHANGED')
        if not src.translatable:
            if src.content != dst.content or proof.get('preserved') is not True: raise ValueError('PROTECTED_DOCUMENT_BLOCK_CHANGED')
            continue
        job = connection.execute('SELECT * FROM translation_jobs WHERE id=? AND task_id=(SELECT task_id FROM artifact_revisions WHERE id=?)', (proof.get('job_id'), revision_id)).fetchone()
        qa = connection.execute("SELECT * FROM checks WHERE id=? AND check_kind='translation.qa' AND result='pass'", (proof.get('qa_id'),)).fetchone()
        if (job is None or qa is None or job['status'] not in (('READY','STALE') if historical else ('READY',)) or job['source_version_id'] != source_version_id
                or job['source_sha256'] != src.source_sha256 or job['qa_id'] != qa['id']
                or job['target_sha256'] != digest(dst.content.encode()) or qa['job_id'] != job['id']):
            raise ValueError('TRANSLATION_QA_OR_SOURCE_BINDING_REQUIRED')
        if ((job['task_id'],job['attempt_id'],qa['task_id'],qa['attempt_id'])
                !=(artifact['task_id'],artifact['attempt_id'],artifact['task_id'],artifact['attempt_id'])
                or qa['check_version']!=json.loads(qa['details_json']).get('check_version')):
            raise ValueError('TRANSLATION_QA_ATTEMPT_BINDING_REQUIRED')
        details = json.loads(qa['details_json'])
        if (details.get('stale') and not historical) or store.read(job['target_sha256']).decode() != dst.content:
            raise ValueError('TRANSLATION_STALE_OR_BYTES_CHANGED')
    return target
