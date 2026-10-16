import asyncio
from contextlib import closing
import hashlib
import json

from app.providers.fake import FakeProvider
from app.runtime.workflow import Workflow
from app.runtime.workspace import WorkspaceManager
from app.usage.budgets import check_budget
from app.usage.ledger import UsageLedger
from support.contracts import make_contract


def test_unqualified_route_has_a_generate_candidate_and_no_b_execution(client):
    cid = client.post('/v1/conversations',json={'title':'A 主导负资格 fixture'}).json()['id']
    tid = client.post(f'/v1/conversations/{cid}/turns',json=dict(text='检查材料',provider_profile_id='fake-gpt',client_request_id='quality-route')).json()['task_id']
    database=client.app.state.database
    with closing(database.connect()) as connection:
        row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(tid,)).fetchone()
        attempt=row['attempt_id']; route=json.loads(row['route_snapshot_json'])
    manager=WorkspaceManager(database.path.parent/'workspaces')
    workspace=manager.create(tid,attempt)
    source=workspace.ingest_source('source.txt',b'value = 6\n')
    contract=make_contract(tid,attempt,route['id'])
    contract['inputs']=[dict(id='source',ref='input/source.txt',sha256=hashlib.sha256(source.read_bytes()).hexdigest())]
    b=FakeProvider(executions=[dict(text='value = 6\n',usage={'total_tokens':20})])
    a=FakeProvider(takeovers=[dict(text='value = 6\n',usage={'total_tokens':30})],reviews=[dict(decision='PASS',criterion_results={'AC2':True},read_unit_ids=['body'],source_refs=['input/source.txt'],usage={'total_tokens':10})])
    def validate(candidate):
        assert candidate.content==b'value = 6\n'
        return [dict(criterion_id='AC1',passed=True,evidence={'actual_sha256':candidate.byte_sha256})]
    workflow=Workflow(database.path,manager,b,validate,a,check_budget,estimated_tokens={'B.execution':20,'A.takeover':30,'A.review':10})
    workflow._production_a_led=True  # Private production assembly policy, tested using fake ports.
    result=asyncio.run(workflow.run(contract))
    assert result.state=='OUTPUT_PREPARING'
    assert b.starts==[]
    assert [r.role for r in a.starts]==['A','A']
    summary=UsageLedger(database.path).summary(tid)
    assert summary['total_tokens']==40 and summary['a_tokens']==40
    assert {r['function'] for r in summary['requests']}=={'takeover','review'}
    with closing(database.connect()) as connection:
        artifact=connection.execute('SELECT canonical_issued_by,a_response_ref FROM artifact_revisions WHERE id=?',(result.current_revision_id,)).fetchone()
    assert artifact['canonical_issued_by']=='A' and artifact['a_response_ref']
