import json
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.limits import InMemoryRedis, set_redis
from app.db.models import APIKey
from app.providers.base import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    ChunkChoice,
    ChunkDelta,
    ProviderError,
    Usage,
)
from app.providers.registry import ModelConfig, PricePer1K, ProviderRoute, get_model_registry


@pytest.fixture(autouse=True)
def fresh_redis() -> None:
    set_redis(InMemoryRedis())


class StreamProvider:
    def __init__(
        self,
        name: str,
        fail_midway: bool = False,
        fail_before_first: bool = False,
    ) -> None:
        self.name = name
        self.fail_midway = fail_midway
        self.fail_before_first = fail_before_first
        self.chat_calls = 0

    async def chat(self, req: ChatRequest) -> ChatResponse:
        self.chat_calls += 1
        return ChatResponse(
            id=f"chatcmpl-{self.name}",
            model=req.model,
            usage=Usage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )

    async def chat_stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        if self.fail_before_first:
            raise ProviderError(
                "Failed before first chunk",
                kind="server",
                status_code=500,
                provider=self.name,
            )

        # Chunk 1
        yield ChatChunk(
            id="stream-1",
            model=req.model,
            choices=[ChunkChoice(index=0, delta=ChunkDelta(role="assistant"))],
        )

        if self.fail_midway:
            raise ProviderError(
                "Stream dropped midway",
                kind="network",
                status_code=500,
                provider=self.name,
            )

        # Chunk 2
        yield ChatChunk(
            id="stream-1",
            model=req.model,
            choices=[ChunkChoice(index=0, delta=ChunkDelta(content="Hello stream!"))],
        )

        # Final chunk
        yield ChatChunk(
            id="stream-1",
            model=req.model,
            choices=[ChunkChoice(index=0, delta=ChunkDelta(), finish_reason="stop")],
        )


@pytest.mark.asyncio
async def test_cache_hit_on_repeated_request(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    registry = get_model_registry()

    prov = StreamProvider(name="cacheable-mock")
    registry.register_provider("cacheable-mock", prov)
    registry.models["test-cache-model"] = ModelConfig(
        name="test-cache-model",
        providers=[ProviderRoute(provider="cacheable-mock", upstream_model="m1")],
        price_per_1k=PricePer1K(Decimal("0.0"), Decimal("0.0")),
    )

    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {
        "model": "test-cache-model",
        "messages": [{"role": "user", "content": "repeat me"}],
        "temperature": 0.0,
    }

    # 1st request -> Cache MISS
    resp1 = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp1.status_code == 200
    assert resp1.headers["X-Maskgate-Cache"] == "miss"
    assert prov.chat_calls == 1

    # 2nd identical request -> Cache HIT (no provider call!)
    resp2 = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp2.status_code == 200
    assert resp2.headers["X-Maskgate-Cache"] == "hit"
    assert prov.chat_calls == 1  # call count did NOT increase!


@pytest.mark.asyncio
async def test_streaming_success_and_done(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    registry = get_model_registry()

    prov = StreamProvider(name="stream-success-mock")
    registry.register_provider("stream-success-mock", prov)
    registry.models["test-stream-model"] = ModelConfig(
        name="test-stream-model",
        providers=[ProviderRoute(provider="stream-success-mock", upstream_model="m1")],
        price_per_1k=PricePer1K(Decimal("0.0"), Decimal("0.0")),
    )

    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {
        "model": "test-stream-model",
        "messages": [{"role": "user", "content": "stream this"}],
        "stream": True,
    }

    resp = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    content = resp.text
    events = [line for line in content.split("\n\n") if line.strip()]

    # Assert last event is [DONE]
    assert events[-1] == "data: [DONE]"

    # Assert middle chunks are valid json
    first_data = json.loads(events[0].replace("data: ", ""))
    assert first_data["object"] == "chat.completion.chunk"


@pytest.mark.asyncio
async def test_streaming_midway_drop_produces_error_event(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    registry = get_model_registry()

    prov = StreamProvider(name="stream-drop-mock", fail_midway=True)
    registry.register_provider("stream-drop-mock", prov)
    registry.models["test-stream-drop"] = ModelConfig(
        name="test-stream-drop",
        providers=[ProviderRoute(provider="stream-drop-mock", upstream_model="m1")],
        price_per_1k=PricePer1K(Decimal("0.0"), Decimal("0.0")),
    )

    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {
        "model": "test-stream-drop",
        "messages": [{"role": "user", "content": "drop me"}],
        "stream": True,
    }

    resp = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp.status_code == 200

    content = resp.text
    assert "Stream interrupted" in content
    assert "data: [DONE]" in content


@pytest.mark.asyncio
async def test_streaming_fallback_before_first_chunk(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    registry = get_model_registry()

    prov1 = StreamProvider(name="stream-fail-init", fail_before_first=True)
    prov2 = StreamProvider(name="stream-backup-ok")
    registry.register_provider("stream-fail-init", prov1)
    registry.register_provider("stream-backup-ok", prov2)

    registry.models["test-stream-fallback"] = ModelConfig(
        name="test-stream-fallback",
        providers=[
            ProviderRoute(provider="stream-fail-init", upstream_model="m1"),
            ProviderRoute(provider="stream-backup-ok", upstream_model="m2"),
        ],
        price_per_1k=PricePer1K(Decimal("0.0"), Decimal("0.0")),
    )

    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {
        "model": "test-stream-fallback",
        "messages": [{"role": "user", "content": "stream with fallback"}],
        "stream": True,
    }

    resp = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp.status_code == 200
    content = resp.text
    assert "Hello stream!" in content
    assert "data: [DONE]" in content
