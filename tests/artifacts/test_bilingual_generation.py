import asyncio
from contextlib import closing
from dataclasses import dataclass

import pytest

from conftest import capture


def translation_service(ctx, texts, *, omission=False):
    from app.contracts.providers import ProviderContract, ProviderIdentityRecord
    from app.translation.ports import TranslationResponse
    from app.translation.service import TranslationService
    client = ctx['client']
    identity = ProviderContract(schema_version='1.0', provider_id='fake-glm',
        identity=ProviderIdentityRecord(adapter='fake', model_id='fixture-glm', family='glm', connection_id='fake-glm'),
        identity_status='verified', identity_source='fixture-response', connection_version='test-only')
    class ExternalFixture:
        def __init__(self, phase):
            self.identity = identity; self.phase = phase; self.calls = []
        async def invoke(self, request):
            self.calls.append(request)
            blocks = {}
            for b in request.blocks:
                value=texts.get(b['source'],b['source'])
                for old,new in {'January':'一月','February':'二月','Increase':'增加','Report':'报告','Appendix':'附录','Source data.':'来源数据。'}.items():
                    value=value.replace(old,new)
                blocks[b['block_id']]=value
            if omission and self.phase == 'translate': blocks = {}
            if self.phase == 'check': blocks = dict(request.previous or {})
            return TranslationResponse(blocks=blocks, complete=True, findings=(), identity=self.identity,
                usage={'input_tokens': 8, 'output_tokens': 8})
        async def request_status(self, request_id): return 'not_started'
    translator, checker = ExternalFixture('translate'), ExternalFixture('check')
    return TranslationService(client.app.state.database.path, translator, checker), translator, checker


@pytest.mark.parametrize('document_task', ['claude'], indirect=True)
def test_every_translatable_block_uses_real_translation_jobs_and_qa(document_task):
    from app.documents.parse import parse_document
    from app.documents.translate import DocumentTranslator, require_translation
    ctx = document_task
    text = '# Report\n\nJanuary 30. February 40. Increase 10.\n\n```python\nprint(30)\n```\n\n## Appendix\n\nSource data.\n'
    source = capture(ctx, text)['revision_id']
    model = parse_document(text.encode(), 'markdown', source_version_id=source, language='en')
    service, translator, _ = translation_service(ctx, {'Report': '报告', 'January 30. February 40. Increase 10.': '一月 30。二月 40。增加 10。', 'Appendix': '附录', 'Source data.': '来源数据。'})
    result = asyncio.run(DocumentTranslator(ctx['client'].app.state.database.path, service).translate(ctx['task'], ctx['attempt'], model))
    assert len(translator.calls) == sum(b.translatable for b in model.blocks)
    assert [b.block_id for b in result['model'].blocks] == [b.block_id for b in model.blocks]
    assert result['model'].blocks[2].content == 'print(30)\n'
    assert '一月 30' in result['model'].blocks[1].content
    with closing(ctx['client'].app.state.database.connect()) as c:
        require_translation(c, ctx['client'].app.state.blobs, result['revision_id'], source)
        assert c.execute("SELECT count(*) FROM translation_jobs WHERE status='READY'").fetchone()[0] == 4


@pytest.mark.parametrize('document_task', ['claude'], indirect=True)
def test_omitted_translation_cannot_produce_ready_model(document_task):
    from app.documents.parse import parse_document
    from app.documents.translate import DocumentTranslator
    ctx = document_task
    source = capture(ctx, '# Report\n\nRequired body 30.')['revision_id']
    model = parse_document(b'# Report\n\nRequired body 30.', 'markdown', source_version_id=source, language='en')
    service, _, _ = translation_service(ctx, {}, omission=True)
    with pytest.raises(ValueError, match='TRANSLATION_NOT_READY'):
        asyncio.run(DocumentTranslator(ctx['client'].app.state.database.path, service).translate(ctx['task'], ctx['attempt'], model))


def test_gpt_without_explicit_bilingual_request_calls_no_translator(document_task):
    from app.documents.translate import DocumentTranslator
    from app.documents.parse import parse_document
    ctx = document_task
    source = capture(ctx, '# Report\n\nBody.')['revision_id']
    model = parse_document(b'# Report\n\nBody.', 'markdown', source_version_id=source, language='en')
    class Unused:
        async def translate(self, **kwargs): raise AssertionError('unexpected GPT translation')
    result = asyncio.run(DocumentTranslator(ctx['client'].app.state.database.path, Unused()).translate(ctx['task'], ctx['attempt'], model, explicit_bilingual=False))
    assert result is None
