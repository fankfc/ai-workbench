import json
from importlib import import_module
from pathlib import Path


def handler():
    assert Path('tests/support/scenarios/translation_corpus.py').exists(), 'corpus evaluator missing'
    return import_module('support.scenarios.translation_corpus')


def test_draft_references_do_not_count_as_approved_golden(tmp_path):
    result = handler().run(tmp_path, {})
    assert result['expected_blocks'] >= 60
    assert result['reviewed_blocks'] == 0
    assert not result['published']
    assert 'HUMAN_REVIEW_MISSING' in result['issue_codes']


def test_known_critical_error_is_blocked_by_product_checker(tmp_path):
    result = handler().run(tmp_path, {'fault': 'critical_semantic'})
    assert not result['published']
    assert result['critical_negative_rejected'] >= 1
    assert result['product_evaluations'] >= 60


def test_corpus_preserves_original_ids_and_balanced_drafts():
    rows = [json.loads(line) for line in Path('tests/fixtures/translation/golden.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(rows) == 60
    assert len({r['id'] for r in rows}) == 60
    assert {'neg-num', 'uncertain', 'valid'} <= {r['id'] for r in rows}
    assert all(r.get('reference_status') == 'unreviewed_draft' for r in rows)
    assert {domain: sum(r['domain'] == domain for r in rows) for domain in ('code', 'paper', 'document')} == {'code': 20, 'paper': 20, 'document': 20}


def test_material_mistranslation_is_not_published(probe):
    result=probe('translation_corpus',case_id='en-zh-negation-number',candidate='当差值小于 0.03 时允许发布。')
    assert not result['published']
    assert {'NEGATION_CHANGED','NUMBER_CHANGED'}<=set(result['issue_codes'])
    assert result['translator_calls']==0 and result['gpt_native_status']=='NATIVE'
