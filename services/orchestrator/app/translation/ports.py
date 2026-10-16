"""Independent B translation and semantic checking boundaries."""
from dataclasses import dataclass, field
from typing import Protocol
from app.contracts.providers import ProviderContract


@dataclass(frozen=True)
class TranslationRequest:
    request_id: str
    job_id: str
    task_id: str
    attempt_id: str
    candidate: int
    phase: str
    source_language: str
    target_language: str
    blocks: tuple[dict,...]
    context_sha256: str
    glossary: tuple[dict,...]=()
    previous: dict=field(default_factory=dict)
    findings: tuple[dict,...]=()
    high_impact_blocks: tuple[str,...]=()
    estimated_tokens: int | None=None
    token_budget_remaining: int | None=None
    role_prompt: dict=field(default_factory=dict)


@dataclass(frozen=True)
class TranslationResponse:
    blocks: dict[str,str]=field(default_factory=dict)
    findings: tuple[dict,...]=()
    complete: bool=True
    usage: dict | None=None
    identity: ProviderContract | None=None


class TranslationPort(Protocol):
    identity: ProviderContract
    async def invoke(self, request: TranslationRequest) -> TranslationResponse: ...
    async def request_status(self, request_id: str) -> str: ...


class PortUnavailable(RuntimeError):
    pass


class UnavailableTranslationPort:
    def __init__(self,identity): self.identity=identity
    async def invoke(self,request): raise PortUnavailable('TRANSLATION_PROVIDER_UNAVAILABLE')
    async def request_status(self,request_id): return 'unknown'
