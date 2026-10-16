"""Only external responses are fixtures; glossary, jobs, QA and cache are real."""
import asyncio
import hashlib

import pytest

from app.translation.glossary import GlossaryStore
from translation.fakes import claude_turn, service


CONTEXT = hashlib.sha256(b'river-bank-context').hexdigest()
SOURCE = '岸。'


def glossary_translation(request):
    term = next((entry['target'] for entry in request.glossary if entry['source'] == '岸'), 'bank')
    return {block['block_id']: block['source'].replace(SOURCE, term + '.') for block in request.blocks}


def translate(translation, task, attempt, **options):
    return asyncio.run(translation.translate(
        task_id=task, attempt_id=attempt, source=SOURCE,
        source_language='zh-CN', target_language='en', purpose='input',
        context_sha256=CONTEXT, glossary_version='1', **options,
    ))


def put(glossary, task, target):
    glossary.put(task, '1', 'geography', [
        {'source': '岸', 'target': target, 'sense': 'river edge'},
    ], reason='Use the geographical sense.')


@pytest.mark.parametrize('explicit_retry', [False, True])
def test_installing_v1_after_default_empty_glossary_changes_translation(client, explicit_retry):
    _, task, attempt = claude_turn(client, text=SOURCE)
    translation = service(client, transform=glossary_translation)
    first = translate(translation, task, attempt)
    assert first.status == 'READY' and first.text == 'bank.'

    put(GlossaryStore(client.app.state.database.path), task, 'shore')
    revised = translate(translation, task, attempt, explicit_retry=explicit_retry)

    assert revised.status == 'READY' and revised.text == 'shore.'
    assert revised.job_id != first.job_id and not revised.cache_hit
    assert len(translation.translator.calls) == 2
    again = translate(translation, task, attempt, explicit_retry=True)
    assert again.status == 'READY' and again.text == 'shore.' and again.cache_hit
    assert len(translation.translator.calls) == 2


def test_same_context_and_version_do_not_share_different_task_glossary_terms(client):
    _, first_task, first_attempt = claude_turn(client, text=SOURCE, key='bank')
    _, second_task, second_attempt = claude_turn(client, text=SOURCE, key='shore')
    glossary = GlossaryStore(client.app.state.database.path)
    put(glossary, first_task, 'bank')
    put(glossary, second_task, 'shore')
    translation = service(client, transform=glossary_translation)

    first = translate(translation, first_task, first_attempt)
    second = translate(translation, second_task, second_attempt)

    assert first.status == second.status == 'READY'
    assert first.text == 'bank.' and second.text == 'shore.'
    assert not second.cache_hit and len(translation.translator.calls) == 2


def test_task_scope_is_kept_even_with_identical_glossary_contents(client):
    _, first_task, first_attempt = claude_turn(client, text=SOURCE, key='first')
    _, second_task, second_attempt = claude_turn(client, text=SOURCE, key='second')
    glossary = GlossaryStore(client.app.state.database.path)
    put(glossary, first_task, 'shore')
    put(glossary, second_task, 'shore')
    translation = service(client, transform=glossary_translation)

    first = translate(translation, first_task, first_attempt)
    second = translate(translation, second_task, second_attempt)

    assert first.status == second.status == 'READY' and first.text == second.text == 'shore.'
    assert not second.cache_hit and len(translation.translator.calls) == 2


def test_installed_empty_v1_has_distinct_scope_from_uninstalled_default(client):
    _, task, attempt = claude_turn(client, text=SOURCE)
    translation = service(client, transform=glossary_translation)
    first = translate(translation, task, attempt)
    GlossaryStore(client.app.state.database.path).put(
        task, '1', 'geography', [], reason='Explicitly accept no geographical terms.',
    )

    installed = translate(translation, task, attempt, explicit_retry=True)

    assert first.status == installed.status == 'READY' and installed.text == 'bank.'
    assert not installed.cache_hit and len(translation.translator.calls) == 2
