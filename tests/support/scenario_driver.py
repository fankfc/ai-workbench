"""Test-only service integration. Only the external provider is a fixture.

The driver never registers a production provider or bypasses a Claude gate.
All local operations use the production API/storage/runtime/validator modules.
"""
import argparse
import asyncio
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

if hasattr(sys.stdout,'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from support.contracts import make_contract

CASES=('backend_normal','backend_repair','backend_need_evidence','backend_cancel_late','backend_restart','backend_old_approval','backend_duplicate','backend_budget','backend_budget_after_repair','backend_connection_failure','backend_language_gate','backend_upstream_change')
DOMAINS=('code','paper','document','mixed')

def fixed_material(domain):
    if domain=='code':
        return 'Specification: compute 2 + 3.\n','def add(a,b):\n    return a+b\nassert add(2,3)==5\nprint(add(2,3))\n','assert 2+3==6\n'
    if domain=='paper':
        text='# Fixed fixture report\nMeasured sum=6. The provided dataset supports this arithmetic [1].\n\n## References\n[1] Local fixed CSV dataset; synthetic test material, not a published study.\n'
        return 'Provided fixture values: 1, 2, 3.\n',text,text.replace('[1]','[9]',1)
    if domain=='mixed':
        text='# Integrated report\nVerified CSV sum=6.\nFigure: values.svg from the current result revision.\n'
        return 'Specification: recompute the CSV sum and link the corresponding chart revision.\n',text,text.replace('6','7')
    text='# Result\n\nname: Alice\nVerified total: 5.\n'
    return text,text,text.replace('5','6')

def run_case(case,root,domain='code'):
    from fastapi.testclient import TestClient
    from app.api.application import create_app
    from app.config import AppSettings
    from app.providers.fake import FakeProvider
    from app.runtime.workflow import Workflow
    from app.runtime.workspace import WorkspaceManager
    from app.runtime.processes import ProcessManager
    from app.runtime.resources import ResourceLimits
    from app.runtime.publication import NativePublisher,PublicationBlocked
    from app.runtime.recovery import Recovery
    from app.runtime.state_machine import StateMachine,checkpoint_for
    from app.storage.blobs import store_artifact
    from app.storage.database import transaction
    from app.storage.revisions import activate_revision
    from app.contracts.artifacts import ArtifactVersion
    from app.usage.ledger import UsageLedger
    from app.usage.budgets import check_budget
    from app.validation.base import ArtifactSnapshot,ValidationContext,NativeMechanicalRunner
    from app.validation.registry import Registry

    # Keep the Windows test paths below MAX_PATH without changing machine policy.
    data_root=root/('r'+uuid4().hex[:8])
    app=create_app(AppSettings(data_root,'qa-scenario-local-token','fake',False))
    database=app.state.database
    ledger=UsageLedger(database.path)
    manager=WorkspaceManager(data_root)
    registry=Registry()
    source_text,good,bad=fixed_material(domain)
    mechanical_results=[]
    publication_rejected=False
    restart_decision=None
    starts_before_restart=None
    cancel_start_count=None
    restart_conservation=None
    mixed_pipeline=None
    result=None
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer qa-scenario-local-token'
        conversation=client.post('/v1/conversations',json={'title':case+' '+domain}).json()['id']
        payload=dict(text='核对固定材料并给出结果。',provider_profile_id='fake-gpt',client_request_id='fixed-request')
        endpoint=f'/v1/conversations/{conversation}/turns'
        accepted=client.post(endpoint,json=payload)
        assert accepted.status_code==202
        task_id=accepted.json()['task_id']
        if case=='backend_duplicate':
            assert client.post(endpoint,json=payload).json()==accepted.json()
        with closing(database.connect()) as connection:
            row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task_id,)).fetchone()
            attempt_id=row['attempt_id']
            route=json.loads(row['route_snapshot_json'])
        workspace=manager.create(task_id,attempt_id)
        source_path=workspace.ingest_source('source.txt',source_text.encode('utf-8'))
        contract=make_contract(task_id,attempt_id,route['id'],domain)
        contract['inputs']=[dict(id='input',ref='input/source.txt',sha256=hashlib.sha256(source_path.read_bytes()).hexdigest())]
        # Native GPT requires A judgment; it does not mandate Claude's English original.
        contract['deliverables'][0]['require_a_canonical']=False
        if domain=='paper':
            data_path=workspace.ingest_source('data.csv',b'value\n1\n2\n3\n')
            contract['inputs'].append(dict(id='data',ref='input/data.csv',sha256=hashlib.sha256(data_path.read_bytes()).hexdigest()))
            contract['acceptance'][0]['evidence_type']='artifact'
            contract['acceptance'].append(dict(id='AC3',mandatory=True,verifier='C',evidence_type='execution',condition='Recompute sum=6 from the provided CSV',semantic=False))
        elif domain=='document':
            contract['acceptance'][0]['evidence_type']='artifact'
        elif domain=='mixed':
            contract['acceptance'][0]['evidence_type']='dependency'
        else:
            data_path=None
        usage=dict(input_tokens=10,output_tokens=5)
        pass_review=dict(decision='PASS',criterion_results={'AC2':True},read_unit_ids=contract['source_unit_ids'],source_refs=[item['ref'] for item in contract['inputs']],usage=dict(input_tokens=12,output_tokens=6))
        executions=[dict(text=good,reported_complete=True,usage=usage)]
        reviews=[pass_review]
        if case in ('backend_repair','backend_budget_after_repair'):
            executions=[dict(text=bad,reported_complete=True,usage=usage),executions[0]]
            reviews=[dict(decision='REPAIR',issues=['mechanical-fail'],usage=usage),pass_review]
        elif case=='backend_need_evidence':
            reviews=[dict(decision='NEED_EVIDENCE',issues=['source-support-missing'],usage=usage)]
        elif case=='backend_budget':
            contract['budget']=dict(total_tokens=10,reserved_a_tokens=5)
        elif case=='backend_language_gate':
            contract['model_family']='claude'
            contract['deliverables'][0]['require_a_canonical']=True
        if case=='backend_budget_after_repair':
            contract['budget']=dict(total_tokens=100,reserved_a_tokens=20)

        b=a=None
        def on_start(request):
            nonlocal cancel_start_count
            if case=='backend_cancel_late':
                cancel_start_count=len(b.starts)+len(a.starts)
                assert client.post(f'/v1/tasks/{task_id}/cancel').status_code==202
            elif case=='backend_connection_failure':
                raise ConnectionError('fixed external transport unavailable')
        b=FakeProvider(executions=executions,on_start=on_start)
        def a_on_start(request):
            if case=='backend_restart':
                with closing(database.connect()) as connection:
                    connection.execute('UPDATE task_runs SET external_request_id=? WHERE task_id=? AND attempt_id=?',(Path(request.prompt_path).stem,task_id,attempt_id))
                raise ConnectionError('fixed external A transport disconnected after B execution')
        a=FakeProvider(reviews=reviews,on_start=a_on_start)

        with ProcessManager(data_root/'process-leases.sqlite3',ResourceLimits(max_output_bytes=65536)) as processes:
            runner=NativeMechanicalRunner(processes,task_id,attempt_id)
            if domain=='mixed':
                from support.mixed_pipeline import prepare_mixed
                mixed_pipeline=prepare_mixed(database.path,app.state.blobs,workspace,runner)
                contract['inputs'].extend(mixed_pipeline['source_inputs'])
                contract['dependencies']=mixed_pipeline['dependency_revision_ids']
                pass_review['source_refs']=[item['ref'] for item in contract['inputs']]
                mechanical_results.extend(mixed_pipeline['validator_results'])
            trusted_hashes={hashlib.sha256(value.encode()).hexdigest() for value in (good,bad)}
            def validate(candidate):
                # This explicit fixture trust applies only to fixed local test bytes.
                execution_authorized=candidate.byte_sha256 in trusted_hashes
                commands={'AC1':[sys.executable,str(candidate.artifact_path)]} if domain=='code' else {}
                with closing(database.connect()) as connection:
                    context=ValidationContext(task_id=task_id,attempt_id=attempt_id,
                        artifact=ArtifactSnapshot(candidate.revision_id,candidate.byte_sha256,candidate.artifact_path),
                        criteria=candidate.contract.acceptance,workspace=workspace.root,
                        source=ArtifactSnapshot('fixed-source',hashlib.sha256(source_path.read_bytes()).hexdigest(),source_path),
                        runner=runner,commands=commands,
                        data_inputs={'dataset':ArtifactSnapshot('fixed-data',hashlib.sha256(data_path.read_bytes()).hexdigest(),data_path)} if domain=='paper' else {},
                        connection=connection,store=app.state.blobs,environment={'test_only':True,'fixture_trust':'fixed-hash-allowlist'},execution_authorized=execution_authorized)
                    checks=registry.validate(domain,context)
                mechanical_results.extend(check.to_dict() for check in checks)
                return [dict(criterion_id=check.criterion_id,passed=check.status=='pass',evidence=check.to_dict()) for check in checks if not any(c.id==check.criterion_id and c.semantic for c in candidate.contract.acceptance)]

            workflow=Workflow(database.path,manager,b,validate,a,check_budget,ledger,
                estimated_tokens={'B.execution':64,'A.review':64,'A.takeover':64},profile_ids={'A':'fake-gpt','B':'fake-glm'})
            result=asyncio.run(workflow.run(contract))
            if case=='backend_restart':
                before_summary=ledger.summary(task_id)
                with closing(database.connect()) as connection:
                    artifact=dict(connection.execute('SELECT * FROM artifact_revisions WHERE id=?',(result.current_revision_id,)).fetchone())
                before_bytes=app.state.blobs.read(artifact['byte_sha256'])
                starts_before_restart=len(b.starts)+len(a.starts)
                restored=create_app(AppSettings(data_root,'qa-scenario-local-token','fake',True))
                restart_decision=restored.state.recovery_results[0]['decision']
                after_summary=UsageLedger(restored.state.database.path).summary(task_id)
                restart_conservation=dict(request_count_before=len(before_summary['requests']),request_count_after=len(after_summary['requests']),unknown_requests_before=before_summary['unknown_requests'],unknown_requests_after=after_summary['unknown_requests'],artifact_sha256_before=hashlib.sha256(before_bytes).hexdigest(),artifact_sha256_after=hashlib.sha256(restored.state.blobs.read(artifact['byte_sha256'])).hexdigest(),recovery_mode='factory reconstruction with existing workflow artifacts and disconnected external request')
            else:
                if result.state=='OUTPUT_PREPARING':
                    publisher=NativePublisher(database.path,Path(result.evidence_root))
                    publisher.stage(task_id,attempt_id,'1.0',result.current_revision_id,result.review_check_id)
                    machine=StateMachine(database.path)
                    machine.transition(task_id,attempt_id,'OUTPUT_PREPARING','READY','1.0')
                    if case in ('backend_old_approval','backend_upstream_change'):
                        with closing(database.connect()) as connection:
                            changed_id=mixed_pipeline['revision_ids']['data'] if case=='backend_upstream_change' else result.current_revision_id
                            old=dict(connection.execute('SELECT * FROM artifact_revisions WHERE id=?',(changed_id,)).fetchone())
                            content=b'value\n1\n2\n4\n' if case=='backend_upstream_change' else (good+'\nchanged source revision\n').encode()
                            sha=hashlib.sha256(content).hexdigest()
                            revised=ArtifactVersion(id=uuid4().hex,task_id=task_id,artifact_kind=old['artifact_kind'],language=old['language'],immutable_uri=app.state.blobs.uri_for(sha),byte_sha256=sha,canonical_content_sha256=sha,source_version_id=None,origin_authors=['B'],canonical_issued_by='B',reviewed_by=[],rendered_by='none',a_response_ref=None,dependencies=[])
                            store_artifact(connection,app.state.blobs,content,revised,attempt_id=attempt_id,provenance={'test_only':True,'change':'fixed-new-version'})
                            with transaction(connection):
                                activate_revision(connection,app.state.blobs,task_id,attempt_id,'data' if case=='backend_upstream_change' else 'answer',revised.id,{})
                                current=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task_id,)).fetchone()
                                checkpoint=checkpoint_for(current)
                                if case=='backend_old_approval':
                                    checkpoint['current_revision_id']=revised.id
                                connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?',(json.dumps(checkpoint),task_id))
                        try:
                            publisher.publish(task_id,attempt_id,'1.0')
                        except PublicationBlocked:
                            publication_rejected=True
                            machine.transition(task_id,attempt_id,'READY','BLOCKED','1.0',{'reason':'stale approval'})
                    else:
                        publisher.publish(task_id,attempt_id,'1.0')
                if case=='backend_cancel_late':
                    Recovery(database.path).ingest(dict(task_id=task_id,attempt_id=attempt_id,sequence=1,kind='provider.completed',payload={'text':'INTERNAL_LATE_CANARY'}),'1.0')

        if case=='backend_duplicate':
            first=ledger.summary(task_id)['requests'][0]
            event=first['events'][0]
            ledger.record(task_id=task_id,attempt_id=attempt_id,provider_profile_id=first['provider_profile_id'],external_request_id=first['external_request_id'],event_id=event['event_id'],provider=first['provider'],raw=event['raw'],source=event['normalized']['source'],mode=event['mode'],sequence=event['sequence'],role=first['role'],function=first['function'],domain=first['domain'],status=event['status'],cumulative_scope=event['cumulative_scope'])
        messages=client.get(f'/v1/conversations/{conversation}/messages').json()['items']
        sse=client.get(f'/v1/conversations/{conversation}/events').text
        assert 'INTERNAL_LATE_CANARY' not in sse
        with closing(database.connect()) as connection:
            task=dict(connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task_id,)).fetchone())
            candidate_count=connection.execute('SELECT COUNT(*) FROM artifact_revisions WHERE task_id=?',(task_id,)).fetchone()[0]
            artifact_count=candidate_count
            candidate_count=connection.execute("SELECT COUNT(*) FROM artifact_revisions WHERE task_id=? AND id LIKE 'candidate-%'",(task_id,)).fetchone()[0]
            turn_count=connection.execute('SELECT COUNT(*) FROM turns WHERE conversation_id=?',(conversation,)).fetchone()[0]
        summary=ledger.summary(task_id)
        starts=len(b.starts)+len(a.starts)
        with closing(database.connect()) as connection:
            current_revision=json.loads(task['checkpoint_json']).get('current_revision_id')
            artifact=connection.execute('SELECT byte_sha256 FROM artifact_revisions WHERE id=?',(current_revision,)).fetchone()
        artifact_path=app.state.blobs.path_for(artifact[0]) if artifact else None
        output=dict(case=case,domain=domain,task_state=task['state'],task_id=task_id,attempt_id=attempt_id,
            database_path=str(database.path),artifact_path=str(artifact_path) if artifact_path else None,
            public_answer_count=sum(item['kind']=='answer.published' for item in messages),public_messages=messages,
            model_starts=starts,model_starts_after_cancel=starts-cancel_start_count if cancel_start_count is not None else 0,
            model_starts_after_restart=starts-starts_before_restart if starts_before_restart is not None else 0,recovery_decision=restart_decision,
            total_tokens=summary['total_tokens'],request_count=len(summary['requests']),unknown_requests=summary['unknown_requests'],qualified_deliveries=summary['qualified_deliveries'],
            forced_translation_starts=sum(r['function']=='translation' for r in summary['requests']),mechanical_check_count=sum(c['status'] in ('pass','fail') for c in mechanical_results),
            candidate_count=candidate_count,artifact_count=artifact_count,turn_count=turn_count,quality_repairs=result.quality_repairs if result else 0,
            connection_retries=result.connection_retries if result else 0,publication_rejected=publication_rejected,
            provider_boundary='fake',real_provider_verified=False,reason_codes=list(result.reason_codes) if result else ['REMOTE_UNKNOWN'])
        output['restart_conservation']=restart_conservation
        output['dependency_graph']=json.loads(task['checkpoint_json']).get('dependency_graph')
        (data_root/'scenario-result.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (data_root/'request-ledger.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (data_root/'validator-results.json').write_text(json.dumps(mechanical_results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (data_root/'public-events.sse').write_text(sse,encoding='utf-8')
        return output

def legacy_main():
    parser=argparse.ArgumentParser()
    parser.add_argument('case',choices=(*CASES,'backend_vertical'))
    parser.add_argument('--root',required=True)
    parser.add_argument('--options',required=True)
    args=parser.parse_args()
    options=json.loads(args.options)
    if not isinstance(options,dict) or set(options)-{'provider_mode','domain'} or options.get('provider_mode')!='fake':
        raise ValueError('TEST_DRIVER_REQUIRES_EXPLICIT_FAKE_MODE; real prerequisites remain blocked')
    domain=options.get('domain','code')
    if args.case=='backend_upstream_change':
        domain='mixed'
    if domain not in DOMAINS:
        raise ValueError('UNSUPPORTED_FIXED_DOMAIN')
    root=Path(args.root).resolve()
    root.mkdir(parents=True,exist_ok=True)
    if args.case=='backend_vertical':
        domains={value:run_case('backend_normal',root,value) for value in DOMAINS}
        faults={case:run_case(case,root,'mixed' if case=='backend_upstream_change' else 'code') for case in CASES if case!='backend_normal'}
        passed=all(r['task_state']=='PUBLISHED' and r['public_answer_count']==1 for r in domains.values())
        expectations={
            'backend_repair':lambda r:r['task_state']=='PUBLISHED' and r['quality_repairs']==1 and r['candidate_count']==2 and r['mechanical_check_count']>=2,
            'backend_need_evidence':lambda r:r['task_state'] in ('NEEDS_INPUT','BLOCKED') and r['public_answer_count']==0,
            'backend_cancel_late':lambda r:r['task_state']=='CANCELLED' and r['public_answer_count']==0 and r['model_starts_after_cancel']==0,
            'backend_restart':lambda r:r['task_state']=='BLOCKED' and r['recovery_decision']=='blocked_unknown' and r['model_starts_after_restart']==0 and r['candidate_count']>=1 and r['request_count']==2 and r['restart_conservation']['artifact_sha256_before']==r['restart_conservation']['artifact_sha256_after'],
            'backend_old_approval':lambda r:r['publication_rejected'] and r['public_answer_count']==0,
            'backend_duplicate':lambda r:r['turn_count']==1 and r['request_count']==r['model_starts'] and r['public_answer_count']==1,
            'backend_budget':lambda r:r['task_state']=='BLOCKED' and r['model_starts']==0 and r['public_answer_count']==0,
            'backend_budget_after_repair':lambda r:r['task_state']=='BLOCKED' and r['quality_repairs']>=1 and r['candidate_count']>=2 and r['model_starts']>0 and r['public_answer_count']==0,
            'backend_connection_failure':lambda r:r['task_state'] in ('FAILED','BLOCKED') and r['model_starts']<=3 and r['request_count']==r['model_starts'] and r['public_answer_count']==0,
            'backend_language_gate':lambda r:r['task_state']=='BLOCKED' and r['model_starts']==0 and r['public_answer_count']==0,
            'backend_upstream_change':lambda r:r['publication_rejected'] and r['public_answer_count']==0 and len(r['dependency_graph']['nodes'])==5 and all(r['dependency_graph']['nodes'][node]['stale'] is True for node in ('analysis','result','figure','answer')),
        }
        checks={case:bool(expectations[case](value)) for case,value in faults.items()}
        passed=passed and all(checks.values())
        result=dict(domains=domains,faults=faults,fault_expectations=checks,all_local_cases_passed=bool(passed),real_handoff_complete=False,provider_boundary='fake')
    else:
        result=run_case(args.case,root,domain)
    print(json.dumps(result,ensure_ascii=False,separators=(',',':')))

def archive_files(root: Path) -> list[Path]:
    """Finish SQLite writes before hashing; only verified DB sidecars are transient.

    sqlite3 connection context managers end transactions without closing their
    handles. Collect abandoned handles first, then explicitly checkpoint every
    SQLite file (including lease stores and legacy nested runs). An active
    reader/writer that prevents truncation must fail the evidence run.
    """
    import gc
    import sqlite3
    from app.runtime.workspace import _reject_reparse

    gc.collect()
    databases = []
    for path in sorted(root.rglob('*')):
        _reject_reparse(path)
        if path.is_file():
            # Check the complete discovery set before any writable connection:
            # checkpointing also mutates WAL/SHM, which are omitted below.
            if path.stat().st_nlink != 1:
                raise ValueError('QA_EVIDENCE_HARDLINK_DENIED: ' + str(path.relative_to(root)))
            with path.open('rb') as stream:
                if stream.read(16) == b'SQLite format 3\x00':
                    databases.append(path)
    sidecars = set()
    for database in databases:
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=rw', uri=True,
                                         timeout=0.25, isolation_level=None)) as connection:
                checkpoint = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                if checkpoint is None or checkpoint[0] != 0:
                    raise RuntimeError('QA_SQLITE_CHECKPOINT_BUSY: ' + str(database.relative_to(root)))
                if checkpoint[1:] not in ((0, 0), (-1, -1)):
                    raise RuntimeError('QA_SQLITE_CHECKPOINT_INCOMPLETE: ' + str(database.relative_to(root)))
        except sqlite3.Error as error:
            reason = ('QA_SQLITE_CHECKPOINT_BUSY' if error.sqlite_errorcode in
                      (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) else 'QA_SQLITE_CHECKPOINT_FAILED')
            raise RuntimeError(reason + ': ' + str(database.relative_to(root))) from error
        sidecars.update(database.with_name(database.name + suffix) for suffix in ('-wal', '-shm'))
    # A surviving connection can keep empty WAL/SHM files alive until process
    # exit; their disappearance must not invalidate the archive. A nonempty WAL
    # means a writer raced finalization, so fail instead of silently losing rows.
    for path in sidecars:
        _reject_reparse(path)
        if path.name.endswith('-wal') and path.exists() and path.stat().st_size:
            raise RuntimeError('QA_SQLITE_WAL_NOT_EMPTY: ' + str(path.relative_to(root)))
    return [path for path in sorted(root.rglob('*'))
            if path.is_file() and path.name != 'run-manifest.json' and path not in sidecars]


def main():
    from contextlib import redirect_stdout
    import io
    from jsonschema.exceptions import ValidationError
    from app.runtime.workspace import _reject_reparse
    from support.manifest import create_manifest, validate_manifest, write_json
    from support.scenarios.registry import get_case, invoke, validate_options
    parser = argparse.ArgumentParser()
    parser.add_argument('case')
    parser.add_argument('--root', required=True)
    parser.add_argument('--options', required=True)
    args = parser.parse_args()
    legacy = args.case in (*CASES, 'backend_vertical')
    try:
        options = json.loads(args.options)
        if legacy:
            if (not isinstance(options, dict) or set(options) - {'provider_mode', 'domain'}
                    or options.get('provider_mode') != 'fake' or options.get('domain', 'code') not in DOMAINS):
                raise ValueError('INVALID_LEGACY_OPTIONS')
        else:
            module = get_case(args.case)
            validate_options(module, options)
    except (ValueError, ValidationError) as error:
        parser.error('INVALID_SCENARIO_OR_OPTIONS: ' + type(error).__name__)
    root = Path(args.root).absolute()
    _reject_reparse(root)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError('QA_ROOT_MUST_BE_EMPTY')
    write_json(root / '.qa-run.json', dict(run_id=uuid4().hex, task_id=uuid4().hex, case=args.case, seed=4317))
    if legacy:
        captured = io.StringIO()
        with redirect_stdout(captured):
            legacy_main()
        result = json.loads(captured.getvalue())
    else:
        result = invoke(module, root, options)
    write_json(root / 'scenario-result.json', result)
    files = archive_files(root)
    manifest = create_manifest(root, files)
    write_json(root / 'run-manifest.json', manifest)
    if not validate_manifest(root, manifest)['valid']:
        raise RuntimeError('QA_EVIDENCE_INVALID')
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    main()
