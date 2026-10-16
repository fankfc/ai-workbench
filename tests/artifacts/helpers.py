"""Fake only the external A/B messages; use product storage and checks."""
import asyncio
from contextlib import closing
import hashlib
import json

from app.contracts.tasks import contract_digest
from app.documents.parse import parse_document
from app.documents.canonical import CanonicalCapture, require_canonical
from app.documents.translate import DocumentTranslator
from app.documents.model import json_bytes, digest
from app.runtime.answer_publication import AnswerPublisher
from app.runtime.state_machine import StateMachine
from app.storage.database import transaction
from support.contracts import make_contract
from artifacts.conftest import record_a_response


def external_translation_service(ctx, *, wrong_number=False):
    from app.contracts.providers import ProviderContract, ProviderIdentityRecord
    from app.translation.ports import TranslationResponse
    from app.translation.service import TranslationService
    identity = ProviderContract(schema_version='1.0',provider_id='fake-glm',
        identity=ProviderIdentityRecord(adapter='fake',model_id='fixture-glm',family='glm',connection_id='fake-glm'),
        identity_status='verified',identity_source='fixture-response',connection_version='test-only')
    replacements={'Report':'报告','January':'一月','February':'二月','Increase':'增加','Appendix':'附录',
        'Source data':'来源数据','Month':'月份','Amount':'金额','Body':'正文','Required':'必要','monthly':'每月','Totals':'合计'}
    class Port:
        def __init__(self): self.identity=identity; self.calls=[]
        async def invoke(self,request):
            self.calls.append(request)
            blocks={}
            for block in request.blocks:
                value=block['source']
                if request.target_language=='zh-CN':
                    for old,new in replacements.items(): value=value.replace(old,new)
                else:
                    value=value.replace('请按月汇总金额并比较增量，提供完整报告和图表。','Summarize monthly amounts and compare the increase; provide a complete report and chart.')
                if wrong_number: value=value.replace('30','999')
                blocks[block['block_id']]=value
            return TranslationResponse(blocks=blocks if request.phase=='translate' else request.previous,
                findings=(),complete=True,identity=self.identity,usage={'input_tokens':12,'output_tokens':12})
        async def request_status(self,request_id): return 'not_started'
    return TranslationService(ctx['client'].app.state.database.path,Port(),Port())


def actual_review(ctx, source, model):
    client=ctx['client']; root=client.app.state.settings.data_root/'evidence'; root.mkdir(exist_ok=True)
    with closing(client.app.state.database.connect()) as c:
        proof=require_canonical(c,client.app.state.blobs,source)
    contract=make_contract(ctx['task'],ctx['attempt'],ctx['route']['id'],domain='document',model_family=ctx['route']['model_family'])
    contract['inputs']=[dict(id='source',ref=client.app.state.blobs.uri_for(proof['body_sha256']),sha256=proof['body_sha256'])]
    contract['source_unit_ids']=[b.block_id for b in model.blocks]
    contract['acceptance'][0]['condition']='Complete parsed source with no known omissions'
    check=root/(source+'-mechanical.json')
    check.write_bytes(json_bytes({'criterion_id':'AC1','passed':model.complete,'revision_id':source,'source_sha256':proof['body_sha256'],
        'complete':model.complete,'block_ids':[b.block_id for b in model.blocks],'issues':[i.model_dump() for i in model.issues]}))
    assert model.complete
    # This decision is the external A fixture. The evidence bytes and their
    # hashes are actual product captures, never fabricated renderer outcomes.
    response={'criterion_id':'AC2','passed':True,'decision':'PASS','revision_id':source,'read_unit_ids':contract['source_unit_ids'],
        'source_refs':[contract['inputs'][0]['ref']]}
    sid=record_a_response(ctx,json.dumps(response))
    review=root/(source+'-review.json'); review.write_bytes(json_bytes(response))
    evidence=[dict(criterion_id='AC1',revision_id=source,ref=check.name,sha256=digest(check.read_bytes()),verifier='C',passed=model.complete),
        dict(criterion_id='AC2',revision_id=source,ref=review.name,sha256=digest(review.read_bytes()),verifier='A',passed=response['decision']=='PASS')]
    decision=dict(task_id=ctx['task'],attempt_id=ctx['attempt'],contract_version='1.0',contract_sha256=contract_digest(contract),
        reviewer='A',decision=response['decision'],revision_id=source,evidence=evidence,read_unit_ids=response['read_unit_ids'],
        source_refs=response['source_refs'],sampling_note=None,canonical_author='A',a_response_ref=sid,issues=[])
    review_id='review-'+source
    with closing(client.app.state.database.connect()) as c,transaction(c):
        task=c.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?',(ctx['task'],ctx['attempt'])).fetchone()
        checkpoint=json.loads(task['checkpoint_json']); checkpoint.update(current_revision_id=source,task_contract=contract,stale=False,publication_blocked=False)
        checkpoint['workflow']={'contract_sha256':contract_digest(contract)}
        c.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),ctx['task'],ctx['attempt']))
        c.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES (?,?,?,?,'A.review','pass','1.0',?)",
            (review_id,ctx['task'],ctx['attempt'],source,json.dumps({'contract':contract,'decision':decision})))
    return review_id,root


def prepare_bilingual(ctx, text='# Report\n\nJanuary 30. February 40. Increase 10.\n', *, dependencies=None, source_logical='answer'):
    client=ctx['client']; database=client.app.state.database.path
    sid=record_a_response(ctx,text)
    source=CanonicalCapture(database).capture(ctx['task'],ctx['attempt'],sid,language='en',logical_id=source_logical,dependencies=dependencies or {})['revision_id']
    model=parse_document(text.encode(),'markdown',source_version_id=source,language='en')
    service=external_translation_service(ctx)
    translated=asyncio.run(DocumentTranslator(database,service).translate(ctx['task'],ctx['attempt'],model))
    review,root=actual_review(ctx,source,model)
    machine=StateMachine(database)
    with closing(client.app.state.database.connect()) as c:
        before=c.execute('SELECT state FROM task_runs WHERE task_id=? AND attempt_id=?',(ctx['task'],ctx['attempt'])).fetchone()[0]
    if before=='RECEIVED':
        for state in ('INPUT_PREPARING','PLANNING','EXECUTING','VALIDATING','REVIEWING','OUTPUT_PREPARING'):
            machine.transition(ctx['task'],ctx['attempt'],before,state,'1.0'); before=state
    else:
        # New immutable source in the same fixture attempt represents resumed
        # recomputation. The fixture's external A result is registered anew.
        with closing(client.app.state.database.connect()) as c:
            c.execute("UPDATE task_runs SET state='OUTPUT_PREPARING' WHERE task_id=? AND attempt_id=?",(ctx['task'],ctx['attempt']))
    publisher=AnswerPublisher(database,root,service)
    asyncio.run(publisher.stage(ctx['task'],ctx['attempt'],'1.0',source,review))
    return dict(source=source,model=model,translation=translated['revision_id'],review=review,answer=publisher,machine=machine)
