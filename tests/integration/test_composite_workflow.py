"""Full product workflow; fixtures replace only external A/B responses."""
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path

import pytest

from app.contracts.providers import ProviderContract,ProviderIdentityRecord
from app.documents.composite import CompositePipeline
from app.documents.parse import parse_document
from app.documents.translate import DocumentTranslator
from app.documents.publish import BundlePublisher
from app.documents.invalidation import reconcile_bundles
from app.providers.fake import FakeProvider
from app.runtime.answer_publication import AnswerPublisher
from app.runtime.workflow import Workflow
from app.runtime.workspace import WorkspaceManager
from app.storage.revisions import is_current_revision
from app.storage.blobs import read_artifact
from app.usage.budgets import check_budget
from artifacts.conftest import document_task
from artifacts.helpers import external_translation_service
from support.contracts import make_contract


FIXTURES=Path(__file__).parents[1]/'fixtures/composite'


def _execute_and_publish(ctx,data,*,report_override=None,formats=('markdown','pdf')):
    client=ctx['client']; database=client.app.state.database.path; manager=WorkspaceManager(database.parent/'workspaces')
    pipeline=CompositePipeline(database,manager)
    run=pipeline.run(ctx['task'],ctx['attempt'],data)
    values=run['results']; months=list(values['monthly_totals'].values())
    report=report_override or f'# Report\n\nJanuary {months[0]}. February {months[1]}. Increase {values["increase"]}.\n\n## Appendix\n\nSource data.\n'
    contract=make_contract(ctx['task'],ctx['attempt'],ctx['route']['id'],domain='document',model_family='claude')
    # The complete C proof now receives B translation and independent semantic
    # QA before A review. This journey exercises delivery, with enough budget
    # for those real requests; the fixed-budget rejection has its own regression.
    contract['budget']['total_tokens']=20000
    contract['inputs']=[dict(id='CSV',ref=run['source_ref'],sha256=run['source_sha256']),dict(id='CODE',ref=run['code_ref'],sha256=run['code_sha256'])]
    contract['dependencies']=[run['computed_results'],run['figures']]
    contract['source_unit_ids']=['CSV','CODE']; contract['full_read_required']=True
    contract['acceptance'][0]['condition']='Recompute the actual CSV and bind January, February and increase report fields'
    b=FakeProvider(executions=[dict(text=report,language='en',usage=dict(input_tokens=12,output_tokens=12))])
    a=FakeProvider(takeovers=[dict(text=report,language='en',usage=dict(input_tokens=12,output_tokens=12,total_tokens=24,cache_read_input_tokens=0,cache_creation_input_tokens=0))],
        reviews=[dict(decision='PASS',canonical_author='A',criterion_results={'AC2':True},
            read_unit_ids=contract['source_unit_ids'],source_refs=[i['ref'] for i in contract['inputs']],usage=dict(input_tokens=12,output_tokens=12,total_tokens=24,cache_read_input_tokens=0,cache_creation_input_tokens=0))])
    route=ctx['route']
    a.provider=ProviderContract(schema_version='1.0',provider_id=route['provider_id'],
        identity=ProviderIdentityRecord(adapter=route['adapter_id'],model_id=route['model_id'],family='claude',connection_id=route['provider_id']),
        identity_status='verified',identity_source=route['identity_source'],connection_version=route['connection_version'])
    service=external_translation_service(ctx)
    workflow=Workflow(database,manager,b,pipeline.validator(run),a,check_budget,
        estimated_tokens={'B.execution':64,'A.review':64,'A.takeover':64},
        profile_ids={'A':'fake-claude','B':'fake-glm'},translation_service=service)
    result=asyncio.run(workflow.run(contract))
    if report_override is not None:
        assert result.state in ('BLOCKED','NEEDS_INPUT')
        return dict(result=result,run=run,b=b,a=a)
    assert result.state=='OUTPUT_PREPARING',result.reason_codes
    source=result.current_revision_id
    model=parse_document(report.encode(),'markdown',source_version_id=source,language='en')
    translated=asyncio.run(DocumentTranslator(database,service).translate(ctx['task'],ctx['attempt'],model))
    answer=AnswerPublisher(database,Path(result.evidence_root),service)
    asyncio.run(answer.stage(ctx['task'],ctx['attempt'],'1.0',source,result.review_check_id))
    bundle=BundlePublisher(database,Path(result.evidence_root))
    bid=bundle.stage(ctx['task'],ctx['attempt'],'1.0',source,list(formats),title='Monthly report',translation_revision_id=translated['revision_id'],
        review_check_id=result.review_check_id,extra_artifact_ids=[run[k] for k in ('source_data','analysis_code','figures')])
    workflow.machine.transition(ctx['task'],ctx['attempt'],'OUTPUT_PREPARING','READY','1.0')
    card=bundle.publish(bid,answer_releaser=answer.publish_in_transaction)
    return dict(result=result,run=run,b=b,a=a,card=card,source=source,translation=translated['revision_id'])


def _new_turn(ctx):
    client=ctx['client']; accepted=client.post(f'/v1/conversations/{ctx["cid"]}/turns',json={
        'text':'Deliver the report','provider_profile_id':'fake-claude','client_request_id':'composite-v2'}).json()
    with closing(client.app.state.database.connect()) as c:
        row=c.execute('SELECT * FROM task_runs WHERE task_id=?',(accepted['task_id'],)).fetchone()
    return dict(client=client,cid=ctx['cid'],task=row['task_id'],attempt=row['attempt_id'],turn=row['turn_id'],route=json.loads(row['route_snapshot_json']))


@pytest.mark.parametrize('document_task',['claude'],indirect=True)
def test_csv_code_chart_a_canonical_translation_files_and_reply_have_two_real_recomputed_versions(document_task):
    ctx=document_task; client=ctx['client']; data=(FIXTURES/'sales.csv').read_bytes()
    expected=json.loads((FIXTURES/'expected.json').read_text())
    first=_execute_and_publish(ctx,data)
    assert first['run']['results']==expected['v1']
    updated=data.replace(b',25',b',35')
    pipeline=CompositePipeline(client.app.state.database.path,WorkspaceManager(client.app.state.database.path.parent/'workspaces'))
    # The actual source update invalidates the prior task's descendants. Its
    # next user turn gets a fresh workflow/contract and immutable outputs.
    pipeline.run(ctx['task'],ctx['attempt'],updated)
    with closing(client.app.state.database.connect()) as c:
        reconcile_bundles(c,ctx['task'],ctx['attempt'])
        assert not is_current_revision(c,ctx['task'],ctx['attempt'],first['source'])
    second_ctx=_new_turn(ctx); second=_execute_and_publish(second_ctx,updated)
    assert second['run']['results']==expected['v2']
    cards=client.get(f'/v1/conversations/{ctx["cid"]}/bundles').json()['items']
    assert len(cards)==2 and cards[0]['historical'] and not cards[1]['historical']
    for version,record in [('v1',first),('v2',second)]:
        assert len(record['b'].starts)==1 and len(record['a'].starts)==2
        with closing(client.app.state.database.connect()) as c:
            assert c.execute('SELECT count(*) FROM a_document_responses WHERE revision_id=?',(record['source'],)).fetchone()[0]==1
            source=read_artifact(c,client.app.state.blobs,record['source']).decode()
        for value in expected[version]['monthly_totals'].values(): assert value in source
        for artifact in record['card']['artifacts']:
            response=client.get(f'/v1/conversations/{ctx["cid"]}/bundles/{record["card"]["bundle_id"]}/artifacts/{artifact["artifact_id"]}/download')
            assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==artifact['sha256']
            if artifact['format']=='markdown':
                assert expected[version]['increase'] in response.text
                if artifact['language']=='zh-CN': assert '增加' in response.text
    with closing(client.app.state.database.connect()) as c:
        artifact_events=c.execute("SELECT count(*) FROM outbox_events WHERE kind='artifacts.published'").fetchone()[0]
        assert artifact_events==2
        snapshots=[dict(c.execute('SELECT * FROM task_runs WHERE task_id=?',(x['result'].current_revision_id and task,)).fetchone()) for x,task in ((first,ctx['task']),(second,second_ctx['task']))]
    evidence=os.environ.get('WORKBENCH_COMPOSITE_EVIDENCE')
    if evidence:
        root=Path(evidence);root.mkdir(parents=True,exist_ok=True)
        for name,record in [('v1',first),('v2',second)]:
            (root/f'bundle-{name}.json').write_text(json.dumps(record['card'],ensure_ascii=False,indent=2),encoding='utf-8')
        (root/'reproduction-output.json').write_text(json.dumps({'v1':first['run'],'v2':second['run']},ensure_ascii=False,indent=2),encoding='utf-8')
        (root/'dependency-graph.json').write_text(json.dumps([json.loads(s['checkpoint_json'])['dependency_graph'] for s in snapshots],ensure_ascii=False,indent=2),encoding='utf-8')


@pytest.mark.parametrize('document_task',['claude'],indirect=True)
def test_old_report_conclusion_cannot_be_overruled_by_fixture_a_pass(document_task):
    ctx=document_task; data=(FIXTURES/'sales.csv').read_bytes().replace(b',25',b',35')
    _execute_and_publish(ctx,data,report_override='# Report\n\nJanuary 30. February 40. Increase 10.\n\nAppendix 50 and 20.')
    assert ctx['client'].get(f'/v1/conversations/{ctx["cid"]}/bundles').json()['items']==[]
