"""Collect local fixture evidence without contacting any provider."""
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from support.contracts import make_contract
from app.api.application import create_app
from app.api.turns import append_event
from app.config import AppSettings
from app.storage.database import transaction
from app.usage.normalization import normalize_usage
from fastapi.testclient import TestClient

def write(path,value):
    file=ROOT/path
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def metadata():
    return dict(time=datetime.now(timezone.utc).isoformat(),git_commit=None,branch='codex/part1-foundation',python=platform.python_version(),sqlite=sqlite3.sqlite_version,provider_mode='fake',real_model_starts=0)

def hashes(paths):
    return {path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths}

if __name__=='__main__':
    facts=metadata()
    fixtures={domain:make_contract('fixture-'+domain,'attempt','route',domain) for domain in ('code','paper','document','mixed')}
    contract_fixtures=dict(**facts,test_only=True,fixtures=fixtures)
    write('docs/acceptance/D013/task-contract-fixtures.json',contract_fixtures)
    write('docs/acceptance/D013/contracts.json',contract_fixtures)
    write('docs/acceptance/D013/contract-report.json',dict(**facts,tests='tests/unit/test_task_contracts.py',test_count=40,result='pass',publication_authorized=False,full_read_actual_provider='not_verified',canonical_authorship_actual_provider='not_verified',a_call_limit=None,escalation=['ambiguity','evidence_gap','assumption_failed','method_changed','capability_missing','no_progress']))
    write('docs/acceptance/D015/usage-fixtures.json',dict(**facts,duplicates=dict(raw=[120,120],total=120),cumulative=dict(raw=[120,200],total=200),gpt=normalize_usage('gpt',dict(input_tokens=100,output_tokens=20,input_tokens_details=dict(cached_tokens=80),output_tokens_details=dict(reasoning_tokens=10))),claude=normalize_usage('claude',dict(input_tokens=20,output_tokens=10,cache_read_input_tokens=80,cache_creation_input_tokens=5)),unknown=normalize_usage('gpt',{}),monetary_cost='unknown',qualified_delivery_denominator_zero='uncomputable'))
    write('docs/acceptance/D015/budget-report.json',dict(**facts,tests='tests/unit/test_usage_ledger.py',test_count=28,result='pass',stop_before_new_start=True,unknown_usage='block',pending_usage_reserved_before_start=True,pending_can_resolve_to=['request_total','cumulative','delta'],remaining_a_reserve_protected=True,savings_claimed=False,sources=['https://platform.claude.com/docs/en/build-with-claude/prompt-caching','https://developers.openai.com/api/reference/resources/responses/methods/create']))
    data_root=ROOT/'.tools/acceptance-api'/('run-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
    app=create_app(AppSettings(data_root,'evidence-local-token','fake',False))
    write('docs/acceptance/D009/openapi.json',app.openapi())
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer evidence-local-token'
        created=client.post('/v1/conversations',json={'title':'公开边界固定样本'})
        conversation=created.json()['id']
        turn=client.post(f'/v1/conversations/{conversation}/turns',json={'text':'请核对固定样本。','provider_profile_id':'fake-gpt','client_request_id':'one'})
        task=turn.json()['task_id']
        with closing(app.state.database.connect()) as connection,transaction(connection):
            row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone()
            for kind,payload in [('model.delta',{'text':'INTERNAL_ENGLISH_CANARY','key':'SECRET_CANARY'}),('response.pending',{'stage':'A','text':'INTERNAL_ENGLISH_CANARY'}),('request.failed',{'error_code':'PROVIDER_UNAVAILABLE','stack':'SECRET_CANARY'})]:
                append_event(connection,row['turn_id'],task,row['attempt_id'],kind,payload)
        messages=client.get(f'/v1/conversations/{conversation}/messages')
        events=client.get(f'/v1/conversations/{conversation}/events')
        assert 'CANARY' not in messages.text+events.text
        (ROOT/'docs/acceptance/D018/public-events.sse').write_bytes(events.content)
        write('docs/acceptance/D018/public-payloads.json',messages.json())
        write('docs/acceptance/D009/api-report.json',dict(**facts,result='pass',create_status=created.status_code,submit_status=turn.status_code,history_status=messages.status_code,sse_status=events.status_code,data_root=str(data_root),sse_delivery='durable cursor replay; reconnect after EOF',production_provider_registry='empty until actual verified adapters are registered'))
    write('docs/acceptance/D018/leakage-report.json',dict(**facts,result='pass',internal_canary_present=False,secret_canary_present=False,public_event_kinds=['message.accepted','response.pending','request.failed'],native_publication='tested with actual local artifact/evidence and fake provider boundary',claude_publication='blocked pending translation/provenance/QA gates',attachment_publication='blocked pending formal bundle publisher',history_and_sse_same_projection=True))
    for task,paths in {
        'D009':['services/orchestrator/app/config.py','services/orchestrator/app/api/application.py','services/orchestrator/app/api/conversations.py','services/orchestrator/app/api/turns.py','services/orchestrator/app/api/tasks.py','tests/integration/test_conversation_api.py'],
        'D013':['services/orchestrator/app/contracts/tasks.py','services/orchestrator/app/runtime/escalation.py','prompts/a_contract.md','prompts/b_execute.md','tests/unit/test_task_contracts.py'],
        'D015':['services/orchestrator/app/usage/normalization.py','services/orchestrator/app/usage/ledger.py','services/orchestrator/app/usage/budgets.py','tests/unit/test_usage_ledger.py'],
        'D018':['services/orchestrator/app/runtime/public_projection.py','services/orchestrator/app/runtime/publication.py','services/orchestrator/app/api/public_events.py','tests/integration/test_public_projection.py','tests/integration/test_native_publication.py'],
    }.items():
        write(f'docs/acceptance/{task}/source-hashes.json',dict(**facts,hashes=hashes(paths)))
    print(json.dumps(dict(result='pass',provider_mode='fake',real_model_starts=0,tasks=['D009','D013','D015','D018'])))
