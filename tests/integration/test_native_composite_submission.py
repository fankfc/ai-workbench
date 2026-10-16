"""Normal API/supervisor submission, external responses alone are fixtures."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from app.contracts.providers import ProviderContract
from app.providers.fake import FakeProvider
from app.providers.phase_bridge import PhaseStarted, PhaseCapture, UsageReceipt
from app.runtime.native_backend import build_native_backend
from app.runtime.native_executor import NativeTaskExecutor
from app.runtime.native_validation import NativeRegistryValidator
from app.runtime.planning import NativeTaskPlanner
from app.runtime.supervisor import TaskSupervisor
from app.runtime.workflow import Workflow
from app.runtime.workspace import WorkspaceManager
from app.usage.budgets import check_budget
from support.contracts import make_contract

GPT = ProviderContract(schema_version='1.0', provider_id='fake-gpt',
    identity=dict(adapter='fake',model_id='fixture-gpt',family='gpt',connection_id='fake-gpt'),
    identity_status='verified',identity_source='fixture:fake',connection_version='test-only')
GLM = ProviderContract(schema_version='1.0',provider_id='fake-glm',
    identity=dict(adapter='fake',model_id='fixture-glm',family='glm',connection_id='fake-glm'),
    identity_status='verified',identity_source='fixture:fake',connection_version='test-only')


class CompositePlanner:
    classification='fixture'
    provider=GPT
    def __init__(self, reviewer): self.starts=[]; self.reviewer=reviewer
    async def invoke_text(self,prompt,**kwargs):
        value=json.loads(prompt); self.starts.append(value); fixed=value['required_contract_fields']
        contract=make_contract(fixed['task_id'],fixed['attempt_id'],fixed['route_snapshot_id'],'mixed')
        contract.update(fixed)
        contract['budget']=dict(total_tokens=300000,reserved_a_tokens=60000)
        contract['acceptance']=value['task_profile']['acceptance']
        self.reviewer.reviews[0]['read_unit_ids']=fixed['source_unit_ids']
        self.reviewer.reviews[0]['source_refs']=[item['ref'] for item in fixed['inputs']]
        request=kwargs['request_id']
        yield PhaseStarted(request,request+'-response',request+'-execution')
        yield PhaseCapture(request,self.provider,json.dumps(contract),request+'-response',request+'-execution',
                           (UsageReceipt(request+'-usage',1,{'total_tokens':20},'reported'),))
    async def cancel(self,*args): return True


def native_run(client, cid, data, *, key, report):
    uploaded=client.post(f'/v1/conversations/{cid}/attachments',content=data,
                         headers={'X-Filename':'sales.csv','Content-Type':'application/octet-stream'})
    assert uploaded.status_code==201, uploaded.text
    attachment=uploaded.json()['id']
    accepted=client.post(f'/v1/conversations/{cid}/turns',json=dict(
        text='Recompute the CSV and deliver the complete monthly report and code and chart.',
        domain='mixed',provider_profile_id='fake-gpt',client_request_id=key,attachment_ids=[attachment],
        profile_inputs={'data_refs':['input/attachment_'+attachment+'.csv'],'formats':['markdown','pdf']}))
    assert accepted.status_code==202,accepted.text
    database=client.app.state.database.path
    manager=WorkspaceManager(database.parent/'workspaces')
    b=FakeProvider(executions=[dict(text=report,language='en',usage={'total_tokens':20})]); b.provider=GLM
    a=FakeProvider(takeovers=[dict(text=report,language='en',usage={'total_tokens':20})],
        reviews=[dict(decision='PASS',canonical_author='A',criterion_results={'mixed.A1':True},usage={'total_tokens':20})]); a.provider=GPT
    runtime=CompositePlanner(a)
    planner=NativeTaskPlanner(database,manager,runtime,allow_fixture=True,estimated_tokens=32)
    workflow=Workflow(database,manager,b,NativeRegistryValidator(database),a,check_budget,
        estimated_tokens={'B.execution':32,'A.takeover':32,'A.review':32})
    binding=build_native_backend(planner,NativeTaskExecutor(workflow),allow_fixture=True,
                                 provider_registry={'fake-gpt':runtime,'fake-glm':b})
    supervisor=TaskSupervisor(database,binding,provider_mode='fake'); supervisor.register_profiles()
    card=asyncio.run(supervisor.run_once())
    return accepted.json()['task_id'],card,runtime


def qualified_conversation(client):
    for provider in (GPT,GLM):
        with closing(client.app.state.database.connect()) as connection:
            connection.execute('UPDATE provider_profiles SET identity_status=?,identity_source=?,provider_json=? WHERE id=?',
                               ('verified',provider.identity_source,provider.model_dump_json(),provider.provider_id))
    return client.post('/v1/conversations',json={'title':'Composite normal submission'}).json()['id']


def test_normal_api_composite_submission_recomputes_two_versions_and_downloads_extras(client):
    cid=qualified_conversation(client)
    data=(Path(__file__).parents[1]/'fixtures/composite/sales.csv').read_bytes()
    cards=[]
    for key,raw,report in [('v1',data,'# Report\n\nJanuary 30. February 40. Increase 10.'),
                           ('v2',data.replace(b',25',b',35'),'# Report\n\nJanuary 30. February 50. Increase 20.')]:
        task,card,runtime=native_run(client,cid,raw,key=key,report=report)
        assert isinstance(card,dict),card
        assert sorted(item['format'] for item in card['artifacts'])==['csv','markdown','pdf','png','python']
        assert len(runtime.starts)==1
        assert len(runtime.starts[0]['required_contract_fields']['dependencies'])==4
        for artifact in card['artifacts']:
            response=client.get(f'/v1/conversations/{cid}/bundles/{card["bundle_id"]}/artifacts/{artifact["artifact_id"]}/download')
            assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==artifact['sha256']
        cards.append(card)
    assert len(client.get(f'/v1/conversations/{cid}/bundles').json()['items'])==2
    assert client.get(f'/v1/conversations/{cid}/bundles/{cards[0]["bundle_id"]}/artifacts/{cards[0]["artifacts"][0]["artifact_id"]}/download').status_code==200


def test_normal_api_composite_partial_csv_calls_no_a_and_publishes_nothing(client):
    cid=qualified_conversation(client)
    task,card,runtime=native_run(client,cid,b'month,category,amount\n2026-01,A,10\n',key='partial',report='Wrong report')
    assert card is None and runtime.starts==[]
    assert client.get(f'/v1/conversations/{cid}/bundles').json()['items']==[]


def test_normal_api_composite_stale_conclusion_is_rejected_before_publication(client):
    cid=qualified_conversation(client)
    data=(Path(__file__).parents[1]/'fixtures/composite/sales.csv').read_bytes().replace(b',25',b',35')
    task,card,runtime=native_run(client,cid,data,key='stale-report',
                                report='# Report\n\nJanuary 30. February 40. Increase 10.\n\nAppendix 50,20.')
    assert not isinstance(card,dict)
    assert client.get(f'/v1/conversations/{cid}/bundles').json()['items']==[]
    with closing(client.app.state.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind IN ('answer.published','artifacts.published') AND task_id=?",(task,)).fetchone()[0]==0
