from contextlib import closing
import json

import pytest

from artifacts.conftest import capture
from artifacts.helpers import actual_review
from app.documents.parse import parse_document
from app.runtime.publication import NativePublisher,PublicationBlocked
from app.runtime.state_machine import StateMachine


def ready_native(ctx):
    text='# Report\n\nJanuary 30. February 40. Increase 10.'
    source=capture(ctx,text,logical_id='answer')['revision_id']
    model=parse_document(text.encode(),'markdown',source_version_id=source,language='en')
    review,root=actual_review(ctx,source,model)
    machine=StateMachine(ctx['client'].app.state.database.path)
    before='RECEIVED'
    for state in ('INPUT_PREPARING','PLANNING','EXECUTING','VALIDATING','REVIEWING','OUTPUT_PREPARING'):
        machine.transition(ctx['task'],ctx['attempt'],before,state,'1.0');before=state
    with closing(ctx['client'].app.state.database.connect()) as c:
        row=c.execute('SELECT * FROM task_runs WHERE task_id=?',(ctx['task'],)).fetchone()
        checkpoint=json.loads(row['checkpoint_json']);checkpoint['requested_formats']=['markdown']
        c.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?',(json.dumps(checkpoint),ctx['task']))
    publisher=NativePublisher(ctx['client'].app.state.database.path,root)
    publisher.stage(ctx['task'],ctx['attempt'],'1.0',source,review)
    return publisher,machine,source,review,root


def test_gpt_file_request_cannot_publish_answer_without_complete_bundle(document_task):
    ctx=document_task; publisher,machine,*_=ready_native(ctx)
    machine.transition(ctx['task'],ctx['attempt'],'OUTPUT_PREPARING','READY','1.0')
    with pytest.raises(PublicationBlocked,match='BUNDLE'):
        publisher.publish(ctx['task'],ctx['attempt'],'1.0')


def test_gpt_bundle_and_answer_share_original_native_gates_and_no_translator(document_task):
    from app.documents.publish import BundlePublisher
    ctx=document_task; publisher,machine,source,review,root=ready_native(ctx)
    bundles=BundlePublisher(ctx['client'].app.state.database.path,root)
    bid=bundles.stage(ctx['task'],ctx['attempt'],'1.0',source,['markdown'],title='GPT report',review_check_id=review)
    machine.transition(ctx['task'],ctx['attempt'],'OUTPUT_PREPARING','READY','1.0')
    card=bundles.publish(bid,answer_releaser=publisher.publish_in_transaction)
    assert not card['format_pairs'] and len(card['artifacts'])==1
    with closing(ctx['client'].app.state.database.connect()) as c:
        assert c.execute('SELECT count(*) FROM translation_jobs').fetchone()[0]==0
        assert c.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0]==1
