import pytest
from app.contracts.providers import ProviderIdentity,ProviderContract
from app.translation.router import needs_translation,snapshot_from_provider

@pytest.mark.parametrize('alias,family,expected',[('claude_code','gpt',False),('codex','claude',True)])
def test_verified_family_controls_route_even_when_adapter_name_disagrees(alias,family,expected):
    identity=ProviderIdentity(alias,'verified-model',family,'fixture')
    assert needs_translation(identity) is expected

@pytest.mark.parametrize('status',['unknown','mismatch'])
def test_unverified_identity_never_becomes_executable_route(status):
    provider=ProviderContract(schema_version='1.0',provider_id='fixture',identity=dict(adapter='claude_code',model_id='gpt-name',family='gpt',connection_id='fixture'),identity_status=status,identity_source=None,connection_version='1')
    with pytest.raises(ValueError,match='UNVERIFIED'): snapshot_from_provider(provider,task_id='task',turn_id='turn',attempt_id='attempt')
