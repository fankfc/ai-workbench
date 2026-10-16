from importlib import import_module
from pathlib import Path


def handler():
    assert Path('tests/support/scenarios/evaluation_protocol.py').exists(), 'protocol evaluator missing'
    return import_module('support.scenarios.evaluation_protocol')


def test_draft_protocol_cannot_become_frozen_from_an_option(tmp_path):
    result = handler().run(tmp_path, {})
    assert not result['frozen']
    assert 'PILOT_EVIDENCE_MISSING' in result['issues']
    assert 'FORMAL_SAMPLE_SIZE_UNREGISTERED' in result['issues']


def test_tuning_holdout_overlap_is_rejected(tmp_path):
    result = handler().run(tmp_path, {'fault': 'tuning_in_holdout'})
    assert not result['frozen']
    assert 'HOLDOUT_CONTAMINATED' in result['issues']


def test_registration_hash_tampering_invalidates_protocol(tmp_path):
    result = handler().run(tmp_path, {'fault': 'registration_changed'})
    assert not result['registration_hash_valid']
    assert 'REGISTRATION_HASH_MISMATCH' in result['issues']


def test_holdout_contamination_invalidates_protocol(probe):
    result=probe('evaluation_protocol',fault='pilot_reused_in_holdout')
    assert not result['registration_valid']
    assert 'HOLDOUT_CONTAMINATED' in result['reason_codes']
