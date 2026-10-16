import asyncio
from contextlib import closing
from dataclasses import replace
import pytest
from app.usage.ledger import UsageLedger
from app.translation.ports import TranslationResponse
from translation.fakes import claude_turn,service
from app.contracts.providers import ProviderContract
CLAUDE=ProviderContract(schema_version='1.0',provider_id='fake-claude',identity=dict(adapter='fake',model_id='fixture-claude',family='claude',connection_id='fake-claude'),identity_status='verified',identity_source='fixture:fake',connection_version='1')

@pytest.mark.parametrize('fence',['cancel','route_identity','response_identity'])
def test_reported_b_receipt_survives_late_fences(client,fence):
    _,task,attempt=claude_turn(client); svc=service(client)
    async def invoke(request):
        svc.translator.calls.append(request)
        if fence=='cancel': client.post(f'/v1/tasks/{task}/cancel')
        if fence=='route_identity': svc.router.check_identity(task,attempt,CLAUDE.model_copy(update={'connection_version':'changed'}))
        response=TranslationResponse(blocks={b['block_id']:'Keep the original file.' for b in request.blocks},
            identity=svc.translator.identity.model_copy(update={'connection_version':'wrong'}) if fence=='response_identity' else svc.translator.identity,
            usage={'input_tokens':12,'output_tokens':12})
        svc.translator.responses[request.request_id]=response
        return response
    svc.translator.invoke=invoke
    try:
        result=asyncio.run(svc.translate(task_id=task,attempt_id=attempt,source='保留原文件。',
            source_language='zh-CN',target_language='en',purpose='input'))
        assert result.status!='READY'
    except ValueError:
        pass
    summary=UsageLedger(svc.database_path).summary(task)
    assert summary['known_lower_bound']==24
    assert svc.checker.calls==[]
    with closing(svc.database.connect()) as connection:
        call=connection.execute('SELECT * FROM translation_calls').fetchone()
        assert call['status']!='pending' and call['usage_json'] is not None
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind IN ('answer.published','artifacts.published')").fetchone()[0]==0
