"""Adapter protocol only: real providers must establish their own evidence."""
from typing import AsyncIterator, Protocol

from app.contracts.events import AgentEvent
from app.contracts.providers import AgentRequest, ProviderIdentity


class AgentAdapter(Protocol):
    async def probe(self) -> ProviderIdentity: ...

    def run(self, request: AgentRequest) -> AsyncIterator[AgentEvent]: ...

    async def cancel(self, task_id: str, attempt_id: str) -> None: ...
