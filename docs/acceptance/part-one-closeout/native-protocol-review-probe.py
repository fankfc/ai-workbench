"""Independent metadata-policy checks and one local hanging fixture, no provider."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'services/orchestrator'))
from app.providers.native_rpc import NativeRpcClient, NativeRpcError

FILES = ['services/orchestrator/app/providers/' + name + '.py' for name in
         ('native_rpc', 'native_rpc_worker', 'codex_protocol', 'zcode_protocol')]
FILES += ['scripts/probe_native_connections.py']


def hashes():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() if (ROOT/name).exists() else None for name in FILES}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--postfix',action='store_true')
    args=parser.parse_args()
    before=hashes()
    suffix='postfix' if args.postfix else 'before'
    target=Path(__file__).with_name('native-protocol-independent-'+suffix+'.json')
    if target.exists():
        raise RuntimeError('PRESERVE_INDEPENDENT_ORIGINAL_EVIDENCE')
    with tempfile.TemporaryDirectory(prefix='rpc-review-',dir=ROOT/'.tools') as directory:
        directory=Path(directory)
        argv=[sys._base_executable,str(directory/'never-launched.py')]
        policy=NativeRpcClient(argv,directory,metadata_methods={'session/close','thread/read','thread/start','account/read','model/list'})
        checks=[]
        for method,params in [
            ('session/close',{'sessionId':'foreign-durable-session','expectedPersistence':'durable'}),
            ('thread/read',{'threadId':'foreign-thread','includeTurns':False,'extra':'unapproved'}),
            ('thread/start',{'cwd':str(directory.parent),'ephemeral':True,'baseInstructions':'unapproved'}),
            ('account/read',{'refreshToken':False,'unapprovedSecretField':'SYNTHETIC_PRIVATE_PARAMETER'}),
            ('model/list',{'limit':999999999,'includeHidden':True,'extra':'unapproved'}),
        ]:
            try:
                policy._validate_method(method,params)
            except NativeRpcError as error:
                checks.append(dict(method=method,blocked=True,reason_code=error.reason_code))
            else:
                checks.append(dict(method=method,blocked=False,server_starts=policy.diagnostics['server_starts']))
        # Emulate only the private worker wrapper in memory; no server starts.
        diagnostic=NativeRpcClient(argv,directory,metadata_methods={'model/list'})
        diagnostic._handle=SimpleNamespace(stdout=(json.dumps({'method':'nativeRpc/providerFrame',
            'params':{'frame':{'method':'sk-fixture-PRIVATE_DIAGNOSTIC_CANARY','params':{}}}})+'\n').encode())
        diagnostic._drain()
        method_canary_exported='PRIVATE_DIAGNOSTIC_CANARY' in json.dumps(diagnostic.diagnostics)
        activity_checks=[]
        for frame in [
            {'method':'item/agentMessage/delta','params':{'threadId':'synthetic-thread','turnId':'synthetic-turn','itemId':'synthetic-item','delta':'synthetic-only'}},
            {'method':'model.streaming','params':{}},
            {'method':'session/event','params':{'event':{'type':'model.streaming','payload':{'kind':'text_delta','delta':'synthetic-only'}}}},
        ]:
            activity=NativeRpcClient(argv,directory,metadata_methods={'model/list'})
            activity._handle=SimpleNamespace(stdout=(json.dumps({'method':'nativeRpc/providerFrame','params':{'frame':frame}})+'\n').encode())
            try:
                activity._drain()
            except NativeRpcError as failure:
                activity_checks.append(dict(method=frame['method'],blocked=True,reason_code=failure.reason_code,
                    model_turn_starts=activity.diagnostics['model_turn_starts'],
                    observed_model_activity=activity.diagnostics.get('observed_model_activity'),
                    submitted_model_turns=activity.diagnostics.get('submitted_model_turns')))
            else:
                activity_checks.append(dict(method=frame['method'],blocked=False,model_turn_starts=activity.diagnostics['model_turn_starts']))
        fixture=directory/'hanging_fixture.py'
        fixture.write_text("""import json,sys,time
from pathlib import Path
for line in sys.stdin:
    packet=json.loads(line)
    if packet.get('method')=='model/list':
        Path('request-entered').write_text('metadata only')
        time.sleep(10)
""",encoding='utf-8')
        client=NativeRpcClient([sys._base_executable,str(fixture)],directory,metadata_methods={'model/list'},timeout_seconds=5)
        errors=[]
        client.start()
        def request():
            try:
                client.request('model/list',{'limit':50,'includeHidden':False},timeout=3)
            except Exception as failure:
                errors.append(getattr(failure,'reason_code',type(failure).__name__))
        thread=threading.Thread(target=request)
        thread.start()
        deadline=time.monotonic()+2
        while not (directory/'request-entered').exists() and time.monotonic()<deadline:
            time.sleep(0.005)
        if not (directory/'request-entered').exists():
            raise AssertionError('INDEPENDENT_CONCURRENT_REQUEST_NOT_ENTERED')
        started=time.monotonic()
        cleanup=client.cancel()
        cancel_seconds=time.monotonic()-started
        thread.join(timeout=2)
        script_override=None
        zcode_override=None
        if args.postfix:
            # Read the entry script and forbid any launcher even if a guard
            # regresses. This tests its negative override path, not a provider.
            spec=importlib.util.spec_from_file_location('independent_native_entry',ROOT/'scripts/probe_native_connections.py')
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            launcher_attempts=[]
            original_start=NativeRpcClient.start
            def never_start(self):
                launcher_attempts.append(True)
                raise AssertionError('INDEPENDENT_REVIEW_FORBIDS_NATIVE_PROVIDER_START')
            NativeRpcClient.start=never_start
            try:
                override_output=directory/'override-report.json'
                exit_code=module.main(['--codex-executable',sys._base_executable,'--cwd',str(directory),
                    '--output',str(override_output)])
                override=json.loads(override_output.read_text(encoding='utf-8'))
                script_override=dict(exit_code=exit_code,reason_code=override.get('reason_code'),
                    launcher_attempts=len(launcher_attempts),production_enabled=override['production_enabled'])
                from app.providers.zcode_protocol import ZCodeProtocolClient,ZCodeProtocolError
                try:
                    ZCodeProtocolClient([sys._base_executable,'unrelated-entry.py','app-server'],directory)
                except ZCodeProtocolError as failure:
                    zcode_override=dict(blocked=True,reason_code=failure.reason_code,launcher_attempts=len(launcher_attempts))
                else:
                    zcode_override=dict(blocked=False,launcher_attempts=len(launcher_attempts))
            finally:
                NativeRpcClient.start=original_start
        payload=dict(at_utc=datetime.now(timezone.utc).isoformat(),phase=suffix,
            evidence_scope='Pre-start parameter validation, in-memory provider frame, actual Windows local metadata fixture cancellation',
            real_provider_starts=0,real_model_starts=0,real_auth_operations=0,source_hashes_before=before,
            source_hashes_after=hashes(),policy_checks=checks,
            untrusted_method_canary_exported=method_canary_exported,
            unexpected_activity_checks=activity_checks,
            codex_script_override=script_override,zcode_default_entry_override=zcode_override,
            concurrent_cancel=dict(seconds=cancel_seconds,request_thread_alive=thread.is_alive(),request_errors=errors,
                cleanup_complete=cleanup.cleanup_complete,running=cleanup.running,open_handles=cleanup.open_handles,temp_dirs=cleanup.temp_dirs),
            command='services/orchestrator/.venv/Scripts/python.exe docs/acceptance/part-one-closeout/native-protocol-review-probe.py'+(' --postfix' if args.postfix else ''),exit_code=0)
        payload['source_unchanged']=payload['source_hashes_before']==payload['source_hashes_after']
        target.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(evidence=str(target),source_unchanged=payload['source_unchanged'],policy=checks,
            untrusted_method_canary_exported=method_canary_exported,cancel_seconds=cancel_seconds,cleanup_complete=cleanup.cleanup_complete)))


if __name__=='__main__':
    main()
