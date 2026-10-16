import pytest


@pytest.mark.parametrize('domain,inputs,missing', [
    ('code', {'requirements': 'fix a parser', 'workspace_ref': 'input/project'}, 'test_command'),
    ('paper', {'research_question': 'estimate effect'}, 'evidence_refs'),
    ('document', {'purpose': 'explain results', 'source_refs': ['input/source.md'], 'formats': ['pdf']}, 'audience'),
])
def test_domain_preflight_stops_missing_required_evidence(client, domain, inputs, missing):
    response = client.post('/v1/profiles/' + domain + '/preflight', json={'inputs': inputs, 'model_family': 'claude'})
    assert response.status_code == 200
    assert response.json()['status'] == 'NEEDS_INPUT'
    assert missing in response.json()['missing_inputs']
    assert response.json()['model_started'] is False


def test_profile_semantic_review_cannot_be_replaced_by_a_build(client):
    response = client.get('/v1/profiles')
    assert response.status_code == 200
    code = next(item for item in response.json()['items'] if item['domain'] == 'code')
    assert any(item['verifier'] == 'A' and item['semantic'] for item in code['acceptance'])
    assert 'problem_modeling' in code['a_responsibilities']
    assert code['escalation'] == ['ordinary', 'checkpoint', 'a_takeover']


def test_claude_documents_require_pairs_while_gpt_remains_native(client):
    inputs = {'audience': 'research group', 'purpose': 'report', 'source_refs': ['input/source.md'], 'formats': ['pdf', 'docx']}
    path = '/v1/profiles/document/preflight'
    claude = client.post(path, json={'inputs': inputs, 'model_family': 'claude'}).json()
    gpt = client.post(path, json={'inputs': inputs, 'model_family': 'gpt'}).json()
    assert claude['status'] == gpt['status'] == 'READY_FOR_A_CONTRACT'
    assert claude['require_a_canonical'] and claude['language_policy'] == 'claude_en_bridge'
    assert gpt['language_policy'] == 'native' and not gpt['require_bilingual_pair']
    assert claude['require_a_confirmation'] is True
    assert not claude['eligible_for_publication']
    assert client.post(path, json={'inputs': {**inputs, 'source_refs': ['../other']}, 'model_family': 'gpt'}).status_code == 422


def test_requested_profile_missing_inputs_stops_before_planning(client):
    cid = client.post('/v1/conversations', json={'title': '领域澄清'}).json()['id']
    submitted = client.post(f'/v1/conversations/{cid}/turns', json={
        'text': '请写报告', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'profile',
        'domain': 'document', 'profile_inputs': {'purpose': '报告'},
    })
    assert submitted.status_code == 202
    task = submitted.json()['task_id']
    with client.app.state.database.connect() as connection:
        assert connection.execute('SELECT state FROM task_runs WHERE task_id=?', (task,)).fetchone()[0] == 'NEEDS_INPUT'
        assert connection.execute('SELECT COUNT(*) FROM steps WHERE task_id=?', (task,)).fetchone()[0] == 0
    messages = client.get(f'/v1/conversations/{cid}/messages').json()['items']
    assert any(item['kind'] == 'input.required' and item['language'] == 'zh-CN' for item in messages)
    assert all(item['kind'] != 'answer.published' for item in messages)


def test_profile_inputs_are_frozen_by_submission_key(client):
    cid = client.post('/v1/conversations', json={'title': '合同版本'}).json()['id']
    body = dict(text='写报告', provider_profile_id='fake-gpt', client_request_id='same', domain='document',
        profile_inputs={'audience': '研究组', 'purpose': '报告', 'source_refs': ['input/user_request.txt'], 'formats': ['pdf']})
    first = client.post(f'/v1/conversations/{cid}/turns', json=body)
    assert first.status_code == 202
    assert client.post(f'/v1/conversations/{cid}/turns', json=body).json() == first.json()
    changed = {**body, 'profile_inputs': {**body['profile_inputs'], 'audience': '公众'}}
    assert client.post(f'/v1/conversations/{cid}/turns', json=changed).status_code == 409


def test_profile_criterion_name_cannot_hide_weakened_mechanical_or_semantic_condition():
    from app.profiles.registry import get_profile, validate_profile_contract
    from support.contracts import make_contract
    import pytest
    profile = get_profile('document')
    contract = make_contract('task', 'attempt', 'route', 'document')
    contract['acceptance'] = profile['acceptance']
    inputs = {'audience': '研究组', 'purpose': '结果说明', 'source_refs': ['input/source.txt'], 'formats': ['pdf']}
    validate_profile_contract(contract, profile_version=profile['version'], inputs=inputs)
    contract['acceptance'][0] = {**contract['acceptance'][0], 'condition': 'file_exists_only'}
    with pytest.raises(ValueError, match='PROFILE_ACCEPTANCE_MISSING'):
        validate_profile_contract(contract, profile_version=profile['version'], inputs=inputs)
