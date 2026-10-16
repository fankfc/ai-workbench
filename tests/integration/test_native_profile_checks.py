"""Frozen C profile conditions exercise real files, renderers and child tests."""
from contextlib import closing
import hashlib
import json

import pytest

from app.contracts.artifacts import ArtifactVersion
from app.contracts.tasks import validate_contract
from app.profiles.registry import get_profile,validate_profile_contract
from app.runtime.native_validation import NativeRegistryValidator
from app.runtime.workflow import CandidateContext
from app.runtime.workspace import WorkspaceManager
from app.storage.blobs import store_artifact
from app.storage.revisions import activate_revision
from support.contracts import make_contract


DOC=b'# Report\n\nJanuary 30. February 40. Increase 10.\n'
PAPER=b'# Results\n\nn=3; sum=6; mean=2; sample_sd=1. Observations [1].\n\n# References\n\n[1] Supplied study. https://example.org/paper-a\n'
GOOD_CODE=b'def add(a, b):\n    return a + b\n'
BAD_CODE=b'def add(a, b):\n    return a - b\n'
TESTS=b'''import importlib.util, sys, unittest
spec = importlib.util.spec_from_file_location("candidate", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class ActualCases(unittest.TestCase):
    def test_positive(self): self.assertEqual(module.add(2, 3), 5)
    def test_negative(self): self.assertEqual(module.add(-2, 3), 1)
unittest.main(argv=["qualified-tests"])
'''


def case(client,domain,content,*,formats=None,measurements=None,attachment=None,research_question=None):
    source_files={
        'document':{'input/source.md':DOC},
        'paper':{'input/study.md':b'Source: https://example.org/paper-a\n\n# Supplied study\n\nSource material.',
                 'input/measurements.csv':b'value\n1\n2\n3\n'},
        'code':{'input/requirements.md':b'Implement addition and verify both positive and negative cases.',
                'input/tests.py':TESTS},
    }[domain]
    inputs={
        'document':dict(audience='research group',purpose='explain source data',source_refs=['input/source.md'],formats=formats or ['markdown','pdf']),
        'paper':dict(research_question='reproduce supplied measurements',evidence_refs=['input/study.md'],data_refs=['input/measurements.csv'],formats=['markdown']),
        'code':dict(requirements='Implement addition',workspace_ref='input/requirements.md',test_command='fixed_python_tests'),
    }[domain]
    cid=client.post('/v1/conversations',json={'title':'strict C checks'}).json()['id']
    attachment_ids=[]
    if measurements is not None: source_files['input/measurements.csv']=measurements
    if research_question is not None: inputs['research_question']=research_question
    if attachment is not None:
        name,data=attachment
        uploaded=client.post(f'/v1/conversations/{cid}/attachments',content=data,
            headers={'Content-Type':'application/octet-stream','X-Filename':name})
        assert uploaded.status_code==201,uploaded.text
        attachment_id=uploaded.json()['id'];attachment_ids=[attachment_id]
        inputs['source_refs']=['input/attachment_'+attachment_id+'.'+name.rsplit('.',1)[1]]
        source_files={}
    accepted=client.post(f'/v1/conversations/{cid}/turns',json=dict(text='Verify supplied inputs',provider_profile_id='fake-gpt',
        client_request_id='profile',domain=domain,profile_inputs=inputs,attachment_ids=attachment_ids)).json()
    with closing(client.app.state.database.connect()) as c:
        task=c.execute('SELECT * FROM task_runs WHERE task_id=?',(accepted['task_id'],)).fetchone()
    workspace=WorkspaceManager(client.app.state.database.path.parent/'workspaces').create(task['task_id'],task['attempt_id'])
    for ref,data in source_files.items(): workspace.ingest_source(ref.removeprefix('input/'),data)
    if attachment is not None:
        from app.runtime.conversation_context import prepare_conversation_source
        with closing(client.app.state.database.connect()) as c:
            _,manifest=prepare_conversation_source(c,client.app.state.database.path,task,workspace)
            checkpoint=json.loads(task['checkpoint_json']);checkpoint['input_materials']=manifest
            c.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?',(json.dumps(checkpoint),task['task_id']))
        source_files={item['text_ref']:workspace.read('service',item['text_ref']) for item in manifest}
    profile=get_profile(domain)
    contract=make_contract(task['task_id'],task['attempt_id'],json.loads(task['route_snapshot_json'])['id'],domain=domain)
    contract['acceptance']=profile['acceptance']
    contract['inputs']=[dict(id='source'+str(index),ref=ref,sha256=hashlib.sha256(data).hexdigest()) for index,(ref,data) in enumerate(source_files.items())]
    contract['source_unit_ids']=[s['id'] for s in contract['inputs']]
    validate_profile_contract(contract,profile_version=profile['version'],inputs=inputs)
    contract=validate_contract(contract)
    sha=hashlib.sha256(content).hexdigest(); aid='candidate-'+task['task_id']
    artifact=ArtifactVersion(id=aid,task_id=task['task_id'],artifact_kind='code' if domain=='code' else 'document',language='en',
        immutable_uri=client.app.state.blobs.uri_for(sha),byte_sha256=sha,canonical_content_sha256=sha,
        source_version_id=None,origin_authors=['B'],canonical_issued_by='B',reviewed_by=[],rendered_by='none',a_response_ref=None,dependencies=[])
    with closing(client.app.state.database.connect()) as c:
        store_artifact(c,client.app.state.blobs,content,artifact,attempt_id=task['attempt_id'],provenance={'fixture_source':True})
        activate_revision(c,client.app.state.blobs,task['task_id'],task['attempt_id'],'answer',aid,{})
    candidate=CandidateContext(contract,workspace,aid,client.app.state.blobs.path_for(sha),sha,content)
    return candidate,source_files


def test_frozen_document_profile_has_real_source_and_complete_format_checks(client):
    candidate,_=case(client,'document',DOC)
    results=NativeRegistryValidator(client.app.state.database.path)(candidate)
    assert len(results)==2 and all(r['passed'] for r in results)
    assert results[0]['evidence']['reason_code']=='SOURCE_PARSE_AND_NUMBERS_VERIFIED'
    assert {r['format'] for r in results[1]['evidence']['details']['rendered_formats']}=={'markdown','pdf'}
    assert all(r['byte_sha256'] for r in results[1]['evidence']['details']['rendered_formats'])


def test_document_source_numbers_cannot_be_dropped(client):
    candidate,_=case(client,'document',b'# Report\n\nJanuary 30.\n')
    result=NativeRegistryValidator(client.app.state.database.path)(candidate)[0]
    assert not result['passed']
    assert result['evidence']['reason_code']=='SOURCE_NUMBERS_MISSING'


def test_document_missing_requested_font_blocks_the_real_format_check(client,tmp_path):
    from app.documents.render import DocumentRenderer
    candidate,_=case(client,'document',DOC)
    results=NativeRegistryValidator(client.app.state.database.path,renderer=DocumentRenderer(font_path=tmp_path/'missing.ttf'))(candidate)
    assert results[0]['passed'] and not results[1]['passed']
    assert results[1]['evidence']['reason_code']=='REQUESTED_FORMAT_RENDER_FAILED'


def test_document_original_source_mutation_is_detected(client):
    import os
    candidate,_=case(client,'document',DOC)
    path=candidate.workspace.resolve('input/source.md')
    os.chmod(path,0o666);path.write_bytes(b'changed source')
    results=NativeRegistryValidator(client.app.state.database.path)(candidate)
    assert all(not r['passed'] for r in results)
    assert all(r['evidence']['reason_code']=='SOURCE_BYTES_CHANGED' for r in results)


def test_paper_trace_and_statistics_use_actual_pinned_sources_and_csv(client):
    candidate,_=case(client,'paper',PAPER)
    results=NativeRegistryValidator(client.app.state.database.path)(candidate)
    assert len(results)==2 and all(r['passed'] for r in results)
    stats=results[1]['evidence']['details']['recomputed_statistics']
    assert stats=={'n':3,'sum':'6','mean':'2','min':'1','max':'3','range':'2','sample_sd':'1'}
    assert results[0]['evidence']['details']['citation_bindings']['1']['source_sha256']
    assert 'bibliographic_authenticity' in results[0]['evidence']['pending_A_review']


def test_paper_unbound_citation_and_wrong_mean_cannot_be_passed(client):
    candidate,_=case(client,'paper',PAPER.replace(b'example.org/paper-a',b'example.org/invented').replace(b'mean=2',b'mean=9'))
    results=NativeRegistryValidator(client.app.state.database.path)(candidate)
    assert all(not r['passed'] for r in results)
    assert results[0]['evidence']['reason_code']=='CITATION_SOURCE_BINDING_MISSING'
    assert results[1]['evidence']['reason_code']=='RECOMPUTED_STATISTICS_MISMATCH'


def test_code_without_qualified_port_is_explicitly_unavailable_even_when_python_parses(client):
    candidate,_=case(client,'code',GOOD_CODE)
    results=NativeRegistryValidator(client.app.state.database.path)(candidate)
    assert len(results)==2 and all(not r['passed'] for r in results)
    assert all(r['evidence']['reason_code']=='EXECUTION_PORT_UNAVAILABLE' for r in results)


@pytest.mark.parametrize('program,passed',[(GOOD_CODE,True),(BAD_CODE,False)])
def test_code_profile_runs_actual_tests_and_retains_exit_status(client,program,passed):
    from app.profiles.newprofile_checks import WhitelistedPythonTestsPort
    candidate,_=case(client,'code',program)
    port=WhitelistedPythonTestsPort(test_ref='input/tests.py',test_sha256=hashlib.sha256(TESTS).hexdigest(),
        allowed_program_sha256={hashlib.sha256(GOOD_CODE).hexdigest(),hashlib.sha256(BAD_CODE).hexdigest()})
    results=NativeRegistryValidator(client.app.state.database.path,execution_port=port)(candidate)
    assert all(r['passed'] is passed for r in results)
    assert port.executions==1
    receipt=results[0]['evidence']['details']['execution']
    assert receipt['tests_run']==2 and receipt['executed']
    assert receipt['exit_code']==(0 if passed else 1)
    assert receipt['program_sha256']==candidate.byte_sha256


def test_code_port_qualification_cannot_be_claimed_with_a_boolean(client):
    from types import SimpleNamespace
    candidate,_=case(client,'code',GOOD_CODE)
    port=SimpleNamespace(require_qualified=lambda _:True,run_tests=lambda _:None)
    results=NativeRegistryValidator(client.app.state.database.path,execution_port=port)(candidate)
    assert all(not r['passed'] for r in results)
    assert all(r['evidence']['reason_code']=='EXECUTION_PORT_UNQUALIFIED' for r in results)


def original_attachment(format):
    if format=='docx':
        import io
        from docx import Document
        value=Document();value.add_paragraph('January 30. February 40. Increase 10.')
        stream=io.BytesIO();value.save(stream);return stream.getvalue()
    import pymupdf
    with pymupdf.open() as value:
        value.new_page().insert_text((72,72),'January 30. February 40. Increase 10.')
        return value.tobytes()


@pytest.mark.parametrize('format',['docx','pdf'])
def test_binary_attachment_requires_actual_raw_parse_and_pinned_full_derived_view(client,format):
    candidate,_=case(client,'document',DOC,formats=['markdown'],attachment=('source.'+format,original_attachment(format)))
    results=NativeRegistryValidator(client.app.state.database.path)(candidate)
    assert all(result['passed'] for result in results)
    source=results[0]['evidence']['details']['sources'][0]
    assert source['ref'].endswith('.'+format) and source['derived_text_ref'].endswith('.parsed.md')
    assert source['derived_text_sha256'] and source['blocks']==1


@pytest.mark.parametrize('field,value,reason',[
    ('block_scope',[],'ATTACHMENT_BLOCK_COVERAGE_MISMATCH'),
    ('source_sha256','0'*64,'ATTACHMENT_SOURCE_BINDING_MISMATCH'),
    ('text_sha256','0'*64,'ATTACHMENT_DERIVED_SOURCE_NOT_PINNED'),
])
def test_binary_attachment_manifest_cannot_claim_unverified_coverage_or_hash(client,field,value,reason):
    candidate,_=case(client,'document',DOC,formats=['markdown'],attachment=('source.docx',original_attachment('docx')))
    with closing(client.app.state.database.connect()) as c:
        checkpoint=json.loads(c.execute('SELECT checkpoint_json FROM task_runs WHERE task_id=?',(candidate.contract.task_id,)).fetchone()[0])
        checkpoint['input_materials'][0][field]=value
        c.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?',(json.dumps(checkpoint),candidate.contract.task_id))
    results=NativeRegistryValidator(client.app.state.database.path)(candidate)
    assert all(not result['passed'] and result['evidence']['reason_code']==reason for result in results)


@pytest.mark.parametrize('body',[
    b'mean=2.5',b'mean=2.5; range=3',b'mean=2.5; sample_sd=1.291',
])
def test_paper_supported_requested_statistics_and_explicit_sd_rounding(client,body):
    candidate,_=case(client,'paper',b'# Results\n\n'+body+b'. Observations [1].\n\n# References\n\n[1] Study https://example.org/paper-a\n',
        measurements=b'value\n1\n2\n3\n4\n')
    result=NativeRegistryValidator(client.app.state.database.path)(candidate)[1]
    assert result['passed'],result
    statistics=result['evidence']['details']['recomputed_statistics']
    assert statistics['mean']=='2.5' and statistics['range']=='3'
    if b'sample_sd' in body:
        rounding=result['evidence']['details']['reported_checks']['sample_sd'][0]
        assert rounding['half_unit_tolerance']=='0.0005' and rounding['comparison']=='declared_precision_half_unit'


@pytest.mark.parametrize('body,reason',[(b'mean=6','RECOMPUTED_STATISTICS_MISMATCH'),
    (b'Only a narrative result.','RECOMPUTED_STATISTICS_NOT_REPORTED')])
def test_paper_wrong_or_unreported_statistics_never_pass(client,body,reason):
    candidate,_=case(client,'paper',b'# Results\n\n'+body+b' [1].\n\n# References\n\n[1] Study https://example.org/paper-a\n',
        measurements=b'value\n1\n2\n3\n4\n')
    result=NativeRegistryValidator(client.app.state.database.path)(candidate)[1]
    assert not result['passed'] and result['evidence']['reason_code']==reason


def test_paper_mean_for_one_actual_observation_does_not_require_a_sample_sd(client):
    candidate,_=case(client,'paper',PAPER.replace(b'n=3; sum=6; mean=2; sample_sd=1',b'mean=2'),measurements=b'value\n2\n')
    result=NativeRegistryValidator(client.app.state.database.path)(candidate)[1]
    assert result['passed'],result
    assert result['evidence']['details']['recomputed_statistics']['sample_sd'] is None


def test_paper_explicit_requested_range_cannot_be_silently_omitted(client):
    candidate,_=case(client,'paper',PAPER, research_question='Report mean and range.')
    result=NativeRegistryValidator(client.app.state.database.path)(candidate)[1]
    assert not result['passed'] and result['evidence']['reason_code']=='REQUESTED_STATISTICS_NOT_REPORTED'


def test_binary_attachment_missing_derived_contract_pin_blocks_every_document_check(client):
    from dataclasses import replace
    candidate,_=case(client,'document',DOC,formats=['markdown'],attachment=('source.docx',original_attachment('docx')))
    candidate.workspace.ingest_source('unrelated.md',DOC)
    source=candidate.contract.inputs[0].model_copy(update={'ref':'input/unrelated.md','sha256':hashlib.sha256(DOC).hexdigest()})
    candidate=replace(candidate,contract=candidate.contract.model_copy(update={'inputs':[source]}))
    results=NativeRegistryValidator(client.app.state.database.path)(candidate)
    assert all(not result['passed'] and result['evidence']['reason_code']=='ATTACHMENT_DERIVED_SOURCE_NOT_PINNED' for result in results)


def test_binary_attachment_derived_hash_alone_cannot_authorize_different_text(client):
    from dataclasses import replace
    candidate,_=case(client,'document',DOC,formats=['markdown'],attachment=('source.docx',original_attachment('docx')))
    source=candidate.contract.inputs[0];poison=b'January 30. February 40. Increase 10.\n\nInvented appendix.'
    workspace=WorkspaceManager(client.app.state.database.path.parent/'adversarial').create(candidate.contract.task_id,candidate.contract.attempt_id)
    sha=hashlib.sha256(poison).hexdigest()
    with closing(client.app.state.database.connect()) as c:
        checkpoint=json.loads(c.execute('SELECT checkpoint_json FROM task_runs WHERE task_id=?',(candidate.contract.task_id,)).fetchone()[0])
        original=checkpoint['input_materials'][0]['source_ref']
        workspace.ingest_source(original.removeprefix('input/'),candidate.workspace.read('service',original))
        workspace.ingest_source(source.ref.removeprefix('input/'),poison)
        checkpoint['input_materials'][0]['text_sha256']=sha
        c.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?',(json.dumps(checkpoint),candidate.contract.task_id))
    candidate=replace(candidate,workspace=workspace,contract=candidate.contract.model_copy(update={'inputs':[source.model_copy(update={'sha256':sha})]}))
    results=NativeRegistryValidator(client.app.state.database.path)(candidate)
    assert all(not result['passed'] and result['evidence']['reason_code']=='ATTACHMENT_DERIVED_TEXT_MISMATCH' for result in results),results


def test_attachment_manifest_cannot_map_a_different_conversation_attachment(client):
    candidate,_=case(client,'document',DOC,formats=['markdown'],attachment=('source.docx',original_attachment('docx')))
    other=client.post('/v1/conversations',json={'title':'unrelated'}).json()['id']
    uploaded=client.post(f'/v1/conversations/{other}/attachments',content=original_attachment('docx'),
        headers={'Content-Type':'application/octet-stream','X-Filename':'source.docx'}).json()
    with closing(client.app.state.database.connect()) as c:
        checkpoint=json.loads(c.execute('SELECT checkpoint_json FROM task_runs WHERE task_id=?',(candidate.contract.task_id,)).fetchone()[0])
        checkpoint['input_materials'][0]['attachment_id']=uploaded['id']
        c.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?',(json.dumps(checkpoint),candidate.contract.task_id))
    results=NativeRegistryValidator(client.app.state.database.path)(candidate)
    assert all(not result['passed'] and result['evidence']['reason_code']=='ATTACHMENT_SOURCE_BINDING_MISMATCH' for result in results)
