import json
from contextlib import closing

from app.documents.canonical import CanonicalCapture
from app.documents.composite import CompositePipeline
from app.documents.invalidation import reconcile_bundles
from app.documents.publish import BundlePublisher
from app.runtime.workspace import WorkspaceManager
from app.storage.revisions import is_current_revision
from artifacts.helpers import prepare_bilingual
from artifacts.conftest import document_task, record_a_response
import pytest


@pytest.mark.parametrize('document_task',['claude'],indirect=True)
def test_upstream_change_invalidates_chart_report_translation_render_and_approval_but_preserves_published_history(document_task):
    ctx=document_task; client=ctx['client']; db=client.app.state.database.path
    pipeline=CompositePipeline(db,WorkspaceManager(db.parent/'workspaces'))
    v1=pipeline.run(ctx['task'],ctx['attempt'],b'month,category,amount\n2026-01,A,10\n2026-01,B,20\n2026-02,A,15\n2026-02,B,25\n')
    ready=prepare_bilingual(ctx,dependencies={k:v1[k] for k in ('computed_results','figures')})
    publisher=BundlePublisher(db,db.parent/'evidence')
    bid=publisher.stage(ctx['task'],ctx['attempt'],'1.0',ready['source'],['markdown'],title='Report',translation_revision_id=ready['translation'],review_check_id=ready['review'],extra_artifact_ids=[v1[k] for k in ('source_data','analysis_code','figures')])
    ready['machine'].transition(ctx['task'],ctx['attempt'],'OUTPUT_PREPARING','READY','1.0')
    publisher.publish(bid,answer_releaser=ready['answer'].publish_in_transaction)
    v2=pipeline.run(ctx['task'],ctx['attempt'],b'month,category,amount\n2026-01,A,10\n2026-01,B,20\n2026-02,A,15\n2026-02,B,35\n')
    with closing(client.app.state.database.connect()) as c:
        reconcile_bundles(c,ctx['task'],ctx['attempt'])
        assert not is_current_revision(c,ctx['task'],ctx['attempt'],ready['source'])
        assert not is_current_revision(c,ctx['task'],ctx['attempt'],ready['translation'])
        assert json.loads(c.execute('SELECT details_json FROM checks WHERE id=?',(ready['review'],)).fetchone()[0])['stale']
        assert c.execute('SELECT stale FROM delivery_bundles WHERE id=?',(bid,)).fetchone()[0]==1
    card=client.get(f'/v1/conversations/{ctx["cid"]}/bundles').json()['items'][0]
    assert card['bundle_id']==bid and card['historical']
    assert v2['results']['monthly_totals']['2026-02']=='50' and v2['results']['increase']=='20'
