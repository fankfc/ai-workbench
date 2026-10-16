from contextlib import closing
import json

import pytest

from artifacts.helpers import prepare_bilingual


@pytest.mark.parametrize('document_task',['claude'],indirect=True)
def test_real_pair_bytes_and_answer_publish_once_in_one_transaction(document_task):
    from app.documents.publish import BundlePublisher
    ctx=document_task; ready=prepare_bilingual(ctx)
    publisher=BundlePublisher(ctx['client'].app.state.database.path, ctx['client'].app.state.settings.data_root/'evidence')
    bid=publisher.stage(ctx['task'],ctx['attempt'],'1.0',ready['source'],['markdown','pdf'],title='Report',
        translation_revision_id=ready['translation'],review_check_id=ready['review'])
    assert ctx['client'].get(f'/v1/conversations/{ctx["cid"]}/bundles').json()['items']==[]
    ready['machine'].transition(ctx['task'],ctx['attempt'],'OUTPUT_PREPARING','READY','1.0')
    card=publisher.publish(bid,answer_releaser=ready['answer'].publish_in_transaction)
    publisher.publish(bid,answer_releaser=ready['answer'].publish_in_transaction)
    assert card['bundle_id']==bid and len(card['format_pairs'])==2 and len(card['artifacts'])==4
    with closing(ctx['client'].app.state.database.connect()) as c:
        assert c.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0]==1
        assert c.execute("SELECT count(*) FROM outbox_events WHERE kind='artifacts.published'").fetchone()[0]==1
        answer=json.loads(c.execute("SELECT public_event_json FROM outbox_events WHERE kind='answer.published'").fetchone()[0])
        assert answer['payload']['approval_id']==card['approval_id']
    for artifact in card['artifacts']:
        response=ctx['client'].get(f'/v1/conversations/{ctx["cid"]}/bundles/{bid}/artifacts/{artifact["artifact_id"]}/download')
        import hashlib
        assert response.status_code==200
        assert hashlib.sha256(response.content).hexdigest()==artifact['sha256']==response.headers['X-Content-SHA256']


@pytest.mark.parametrize('document_task',['claude'],indirect=True)
def test_half_v2_render_and_transaction_failure_leave_only_complete_v1_visible(document_task):
    from app.documents.publish import BundlePublisher
    from app.documents.render import DocumentRenderer
    ctx=document_task; ready=prepare_bilingual(ctx)
    publisher=BundlePublisher(ctx['client'].app.state.database.path,ctx['client'].app.state.settings.data_root/'evidence')
    first=publisher.stage(ctx['task'],ctx['attempt'],'1.0',ready['source'],['markdown'],title='Report',translation_revision_id=ready['translation'],review_check_id=ready['review'])
    ready['machine'].transition(ctx['task'],ctx['attempt'],'OUTPUT_PREPARING','READY','1.0')
    publisher.publish(first,answer_releaser=ready['answer'].publish_in_transaction)
    new=prepare_bilingual(ctx,'# Report\n\nJanuary 30. February 50. Increase 20.\n')
    class FailingRenderer(DocumentRenderer):
        def render(self,model,format,*,evidence_dir):
            if model.language=='zh-CN': raise OSError('disk full after English bytes')
            return super().render(model,format,evidence_dir=evidence_dir)
    with pytest.raises(OSError):
        publisher.stage(ctx['task'],ctx['attempt'],'1.0',new['source'],['markdown'],title='Report',translation_revision_id=new['translation'],review_check_id=new['review'],renderer=FailingRenderer())
    assert [i['bundle_id'] for i in ctx['client'].get(f'/v1/conversations/{ctx["cid"]}/bundles').json()['items']]==[first]
    second=publisher.stage(ctx['task'],ctx['attempt'],'1.0',new['source'],['markdown'],title='Report',translation_revision_id=new['translation'],review_check_id=new['review'])
    new['machine'].transition(ctx['task'],ctx['attempt'],'OUTPUT_PREPARING','READY','1.0')
    def crash(c,task,*,bundle_id):
        new['answer'].publish_in_transaction(c,task,bundle_id=bundle_id)
        raise RuntimeError('crash before artifact event commit')
    with pytest.raises(RuntimeError): publisher.publish(second,answer_releaser=crash)
    assert [i['bundle_id'] for i in ctx['client'].get(f'/v1/conversations/{ctx["cid"]}/bundles').json()['items']]==[first]


@pytest.mark.parametrize('document_task',['claude'],indirect=True)
def test_cancelled_missing_format_old_source_and_corrupt_blob_are_not_deliverable(document_task):
    from app.documents.publish import BundlePublisher
    ctx=document_task; ready=prepare_bilingual(ctx)
    publisher=BundlePublisher(ctx['client'].app.state.database.path,ctx['client'].app.state.settings.data_root/'evidence')
    with pytest.raises(ValueError,match='BILINGUAL'):
        publisher.stage(ctx['task'],ctx['attempt'],'1.0',ready['source'],['markdown'],title='Report',review_check_id=ready['review'])
    bid=publisher.stage(ctx['task'],ctx['attempt'],'1.0',ready['source'],['markdown'],title='Report',translation_revision_id=ready['translation'],review_check_id=ready['review'])
    ready['machine'].transition(ctx['task'],ctx['attempt'],'OUTPUT_PREPARING','READY','1.0')
    ctx['client'].post(f'/v1/tasks/{ctx["task"]}/cancel')
    with pytest.raises(ValueError): publisher.publish(bid,answer_releaser=ready['answer'].publish_in_transaction)


@pytest.mark.parametrize('document_task',['claude'],indirect=True)
def test_download_scope_unpublished_and_changed_file_hash_are_enforced(document_task):
    from app.documents.publish import BundlePublisher
    ctx=document_task; ready=prepare_bilingual(ctx)
    publisher=BundlePublisher(ctx['client'].app.state.database.path,ctx['client'].app.state.settings.data_root/'evidence')
    bid=publisher.stage(ctx['task'],ctx['attempt'],'1.0',ready['source'],['markdown'],title='Report',translation_revision_id=ready['translation'],review_check_id=ready['review'])
    with closing(ctx['client'].app.state.database.connect()) as c:
        aid=c.execute('SELECT artifact_id FROM delivery_bundle_artifacts WHERE bundle_id=?',(bid,)).fetchone()[0]
    path=f'/v1/conversations/{ctx["cid"]}/bundles/{bid}/artifacts/{aid}/download'
    assert ctx['client'].get(path).status_code==404
    ready['machine'].transition(ctx['task'],ctx['attempt'],'OUTPUT_PREPARING','READY','1.0')
    card=publisher.publish(bid,answer_releaser=ready['answer'].publish_in_transaction)
    other=ctx['client'].post('/v1/conversations',json={'title':'other'}).json()['id']
    assert ctx['client'].get(path.replace(ctx['cid'],other)).status_code==404
    assert ctx['client'].get(path+'?path=C:/Windows').status_code==422
    artifact=next(a for a in card['artifacts'] if a['artifact_id']==aid)
    ctx['client'].app.state.blobs.path_for(artifact['sha256']).write_bytes(b'corrupted')
    assert ctx['client'].get(path).status_code==409
    assert ctx['client'].get(f'/v1/conversations/{ctx["cid"]}/bundles').json()['items']==[]


@pytest.mark.parametrize('document_task',['claude'],indirect=True)
def test_renderer_claiming_pass_for_corrupt_bytes_cannot_publish(document_task):
    from app.documents.publish import BundlePublisher
    from app.documents.render import RenderedDocument
    from app.documents.model import digest
    ctx=document_task;ready=prepare_bilingual(ctx)
    class CorruptedRenderer:
        def render(self,model,format,*,evidence_dir):
            data=b'%PDF-1.4\nnot a real PDF file'
            return RenderedDocument(format,model.language,data,{'status':'pass','code':'CLAIMED_PASS',
                'byte_sha256':digest(data),'content_sha256':model.content_sha256})
    with pytest.raises(ValueError,match='RENDER_BYTES'):
        BundlePublisher(ctx['client'].app.state.database.path,ctx['client'].app.state.settings.data_root/'evidence').stage(
            ctx['task'],ctx['attempt'],'1.0',ready['source'],['pdf'],title='Report',translation_revision_id=ready['translation'],
            review_check_id=ready['review'],renderer=CorruptedRenderer())
