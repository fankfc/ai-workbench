"""Explicit external-response fixtures; never a production provider."""
import asyncio
import inspect
import json
from pathlib import Path

from app.contracts.events import AgentEvent
from app.contracts.providers import ModelFamily, ProviderIdentity


class FakeProvider:
    test_only = True

    def __init__(self, executions=None, reviews=None, takeovers=None, on_start=None):
        self.executions = list(executions or [])
        self.reviews = list(reviews or [])
        self.takeovers = list(takeovers or [])
        self.on_start = on_start
        self.starts = []
        self.cancellations = []

    async def probe(self):
        return ProviderIdentity("fake", "fixture-gpt", ModelFamily.GPT, "fake-gpt")

    async def run(self, request):
        prompt = json.loads(Path(request.prompt_path).read_text(encoding="utf-8"))
        phase = prompt["phase"]
        self.starts.append(request)
        if self.on_start:
            observed = self.on_start(request)
            if inspect.isawaitable(observed):
                await observed
        queue = self.reviews if phase == "review" else self.takeovers if phase == "takeover" else self.executions
        if not queue:
            raise RuntimeError("FAKE_RESPONSE_EXHAUSTED")
        response = queue.pop(0)
        sequence = 1
        await asyncio.sleep(0)
        yield AgentEvent(request.task_id, request.attempt_id, sequence, "provider.usage", {
            "raw": response.get("usage"), "source": "reported" if response.get("usage") is not None else "unknown"})
        if response.get("connection_error"):
            raise OSError("FIXTURE_CONNECTION_FAILURE")
        sequence += 1
        if phase == "review":
            yield AgentEvent(request.task_id, request.attempt_id, sequence, "review.decision",
                {key: value for key, value in response.items() if key not in {"usage", "connection_error"}})
        elif response.get("text") is not None:
            yield AgentEvent(request.task_id, request.attempt_id, sequence, "artifact.candidate", {
                "text": response["text"], "language": response.get("language", "und")})
        await asyncio.sleep(0)
        yield AgentEvent(request.task_id, request.attempt_id, sequence + 1, "model.completed",
                         {"reported_complete": response.get("reported_complete", True)})

    async def cancel(self, task_id, attempt_id):
        self.cancellations.append((task_id, attempt_id))
