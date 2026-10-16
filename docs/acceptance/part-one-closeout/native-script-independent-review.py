"""New script branches only: native launch forbidden, synthetic projections."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'services/orchestrator'))
from app.providers.native_rpc import NativeRpcClient
from app.providers.zcode_protocol import ZCodeProtocolClient


def hashes():
    names=['scripts/probe_native_connections.py']+['services/orchestrator/app/providers/'+value+'.py'
        for value in ('native_rpc','native_rpc_worker','codex_protocol','zcode_protocol')]
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def main():
    destination=Path(__file__).with_name('native-script-independent-review.json')
    if destination.exists():
        raise RuntimeError('PRESERVE_INDEPENDENT_EVIDENCE')
    before=hashes()
    spec=importlib.util.spec_from_file_location('independent_expanded_native_script',ROOT/'scripts/probe_native_connections.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original_start=NativeRpcClient.start
    launches=[]
    def forbidden_start(self):
        launches.append(True)
        raise AssertionError('INDEPENDENT_REVIEW_FORBIDS_ALL_NATIVE_PROVIDER_LAUNCH')
    NativeRpcClient.start=forbidden_start
    original_zcode=module.ZCodeProtocolClient
    original_codex=module.CodexProtocolClient
    original_environment=os.environ.get('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE')
    checks=[]
    with tempfile.TemporaryDirectory(prefix='native-script-review-',dir=ROOT/'.tools') as temporary:
        directory=Path(temporary)
        def invoke(provider,label,extra=()):
            path=directory/(label+'.json')
            with redirect_stdout(io.StringIO()):
                result=module.main(['--provider',provider,'--cwd',str(directory),'--output',str(path),*extra])
            return result,json.loads(path.read_text(encoding='utf-8'))
        try:
            class WrongZCodeCommand:
                @staticmethod
                def fixed_command(cwd):
                    return [sys._base_executable,'unrelated-entry.py','app-server']
                def __new__(cls,command,cwd,**kwargs):
                    return ZCodeProtocolClient(command,cwd,**kwargs)
            module.ZCodeProtocolClient=WrongZCodeCommand
            exit_code,report=invoke('zcode','zcode-negative-entry')
            value=report['providers']['zcode']
            checks.append(dict(name='new-zcode-script-negative-entry',passed=exit_code==1
                and value['reason_code']=='SUPPORTED_PROTOCOL_ENTRY_REQUIRED' and not value['protocol_probe_completed']
                and not launches,reason_code=value.get('reason_code'),exit_code=exit_code,launcher_attempts=len(launches)))
            checks.append(dict(name='zcode-private-config-reference-restored-after-error',
                passed=os.environ.get('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE')==original_environment))
            cleanup=dict(local_state='exited',remote_state='unknown',cleanup_complete=True,forced=False,
                output_limited=False,running=0,open_handles=0,temp_dirs=0)
            class SyntheticCodex:
                def __init__(self,*args,**kwargs):pass
                def metadata(self):
                    return dict(actual_model_id=None,identity_status='unknown',scope_enforced=False,production_enabled=False,
                                model_turn_starts=0,cleanup=cleanup,synthetic_only=True)
            class SyntheticZCode:
                mode='ok'
                @staticmethod
                def fixed_command(cwd):return ['synthetic-not-executed']
                def __init__(self,*args,**kwargs):pass
                def probe(self):
                    result=dict(metadata_status='observed',reason_code='HOST_ACCOUNT_CONTEXT_REQUIRED',
                        actual_model_id=None,identity_status='unknown',scope_enforced=False,production_enabled=False,
                        model_turn_starts=0,cleanup=dict(cleanup),synthetic_only=True)
                    if self.mode=='cleanup-failed':result['cleanup']['cleanup_complete']=False
                    if self.mode=='unknown-model-count':result['model_turn_starts']=None
                    return result
            module.CodexProtocolClient=SyntheticCodex
            module.ZCodeProtocolClient=SyntheticZCode
            exit_code,report=invoke('all','all-synthetic')
            checks.append(dict(name='expanded-all-mode-projects-both-providers-without-qualifying-model',
                passed=exit_code==0 and set(report['providers'])=={'codex','zcode'}
                    and report['production_enabled'] is False and report['model_identity_verified'] is False
                    and report['model_turn_submissions']==0,
                exit_code=exit_code,provider_names=sorted(report['providers']),synthetic_only=True))
            for mode in ('cleanup-failed','unknown-model-count'):
                SyntheticZCode.mode=mode
                exit_code,report=invoke('all',mode)
                checks.append(dict(name='expanded-script-fails-'+mode,passed=exit_code==1
                    and report['protocol_probe_completed'] is False
                    and report['providers']['zcode']['protocol_probe_completed'] is False,
                    exit_code=exit_code,synthetic_only=True))
            checks.append(dict(name='nonsecret-config-reference-restored-after-all-cases',
                passed=os.environ.get('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE')==original_environment))
        finally:
            NativeRpcClient.start=original_start
            module.ZCodeProtocolClient=original_zcode
            module.CodexProtocolClient=original_codex
            if original_environment is None:os.environ.pop('ZCODE_BUILTIN_PROVIDER_CONFIG_FILE',None)
            else:os.environ['ZCODE_BUILTIN_PROVIDER_CONFIG_FILE']=original_environment
    after=hashes()
    evidence=dict(at_utc=datetime.now(timezone.utc).isoformat(),scope='Only newly expanded entry-script branches',
        mode='Actual default negative ZCode constructor plus explicit in-memory metadata fixtures; native start spy forbids launch',
        actual_native_provider_starts=0,actual_model_starts=0,auth_or_ui_operations=0,
        launcher_attempts=len(launches),checks=checks,passed_count=sum(item['passed'] for item in checks),
        check_count=len(checks),source_hashes_before=before,source_hashes_after=after,source_unchanged=before==after,
        command='services/orchestrator/.venv/Scripts/python.exe docs/acceptance/part-one-closeout/native-script-independent-review.py',exit_code=0)
    destination.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if launches or before!=after or not all(item['passed'] for item in checks):
        raise AssertionError('EXPANDED_SCRIPT_REVIEW_FAILED')
    print(json.dumps(dict(passed=evidence['passed_count'],checks=len(checks),source_unchanged=before==after,
        launcher_attempts=0,evidence=str(destination))))


if __name__=='__main__':main()
