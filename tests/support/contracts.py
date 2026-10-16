import hashlib
import json
from pathlib import Path
from app.contracts.tasks import contract_digest

def make_contract(task_id,attempt_id,route_id,domain='code',model_family='gpt'):
    # Success fixtures fund the complete loaded translator/checker role contexts.
    # Budget-boundary cases explicitly override this allowance. GPT stays native.
    fixture_total_tokens = 30000 if model_family == 'claude' else 10000
    return dict(task_id=task_id,attempt_id=attempt_id,contract_version='1.0',domain=domain,model_family=model_family,route_snapshot_id=route_id,objective='Verify fixed source results',method='Check actual evidence',inputs=[dict(id='input',ref='inputs/source.txt',sha256='a'*64)],constraints=[dict(id='preserve',text='Preserve sources',mandatory=True)],deliverables=[dict(id='result',kind='code' if domain=='code' else 'document',write_scope='b/result',require_a_canonical=domain!='code')],acceptance=[dict(id='AC1',mandatory=True,verifier='C',evidence_type='execution',condition='Mechanical check passes',semantic=False),dict(id='AC2',mandatory=True,verifier='A',evidence_type='review',condition='A judges source support',semantic=True)],dependencies=[],budget=dict(total_tokens=fixture_total_tokens,reserved_a_tokens=2000),b_write_scopes=['b'],a_responsibilities=['problem_modeling','core_reasoning','method_choice','evidence_judgment','final_review'],guidance_depth='ordinary',full_read_required=domain=='paper',source_unit_ids=['body','appendix'] if domain=='paper' else ['body'])

def make_decision(contract,revision_id,root:Path,outcome='PASS'):
    root.mkdir(parents=True,exist_ok=True)
    evidence=[]
    for criterion in contract['acceptance']:
        file=root/(revision_id+'-'+criterion['id']+'.json')
        data=json.dumps(dict(criterion_id=criterion['id'],revision_id=revision_id,passed=True)).encode()
        file.write_bytes(data)
        evidence.append(dict(criterion_id=criterion['id'],revision_id=revision_id,ref=file.name,sha256=hashlib.sha256(data).hexdigest(),verifier=criterion['verifier'],passed=True))
    return dict(task_id=contract['task_id'],attempt_id=contract['attempt_id'],contract_version=contract['contract_version'],contract_sha256=contract_digest(contract),reviewer='A',decision=outcome,revision_id=revision_id,evidence=evidence,read_unit_ids=contract['source_unit_ids'],source_refs=['inputs/source.txt'],sampling_note=None,canonical_author='A',a_response_ref='responses/a-final',issues=[])
