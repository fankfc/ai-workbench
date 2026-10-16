from typing import Literal
from fastapi import APIRouter, HTTPException
from app.contracts.providers import ContractModel
from app.profiles.registry import get_profile, preflight

router = APIRouter()


class ProfileInputs(ContractModel):
    inputs: dict
    model_family: Literal['claude', 'gpt']


@router.get('/v1/profiles')
def list_profiles():
    return dict(items=[get_profile(domain) for domain in ('code', 'paper', 'document', 'mixed')])


@router.post('/v1/profiles/{domain}/preflight')
def profile_preflight(domain: str, body: ProfileInputs):
    try:
        return preflight(domain, body.inputs, body.model_family)
    except (ValueError, TypeError):
        raise HTTPException(422, '领域资料、格式或文件引用无效。') from None
