from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient

from app.db.models import APIKey
from app.providers.base import (
    ChatChoice,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ProviderError,
    Usage,
)
from app.providers.registry import ModelConfig, PricePer1K, ProviderRoute, get_model_registry


class CountingMockProvider:
    """Mock provider that records attempt counts and simulates failures."""

    def __init__(self, name: str, fail_times: int = 0, fail_kind: str = "server") -> None:
        self.name = name
        self.fail_times = fail_times
        self.fail_kind = fail_kind
        self.call_count = 0

    async def chat(self, req: ChatRequest) -> ChatResponse:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            if self.fail_kind == "client":
                raise ProviderError(
                    message="Client error 400",
                    kind="client",
                    status_code=400,
                    retryable=False,
                    provider=self.name,
                )
            if self.fail_kind == "rate_limit":
                raise ProviderError(
                    message="Rate limit 429",
                    kind="rate_limit",
                    status_code=429,
                    retryable=True,
                    provider=self.name,
                )
            if self.fail_kind == "timeout":
                raise ProviderError(
                    message="Timeout 504",
                    kind="timeout",
                    status_code=504,
                    retryable=True,
                    provider=self.name,
                )
            raise ProviderError(
                message="Server error 500",
                kind="server",
                status_code=500,
                retryable=True,
                provider=self.name,
            )

        return ChatResponse(
            id=f"chatcmpl-{self.name}-resp",
            model=req.model,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=f"Hello from {self.name}"),
                )
            ],
            usage=Usage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
        )

    async def chat_stream(self, req: ChatRequest) -> Any:
        yield  # type: ignore[misc]


@pytest.mark.asyncio
async def test_retry_on_server_error_and_succeed(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    registry = get_model_registry()

    provider = CountingMockProvider(name="mock-retry-srv", fail_times=1, fail_kind="server")
    registry.register_provider("mock-retry-srv", provider)
    registry.models["test-retry-model"] = ModelConfig(
        name="test-retry-model",
        providers=[ProviderRoute(provider="mock-retry-srv", upstream_model="m1")],
        price_per_1k=PricePer1K(Decimal("0.0"), Decimal("0.0")),
    )

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "test-retry-model", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 200
    assert provider.call_count == 2  # 1 initial failure + 1 retry success
    assert resp.headers["X-Maskgate-Fallback"] == "false"
    assert resp.headers["X-Maskgate-Provider"] == "mock-retry-srv"


@pytest.mark.asyncio
async def test_retry_on_rate_limit_and_succeed(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    registry = get_model_registry()

    provider = CountingMockProvider(name="mock-retry-429", fail_times=1, fail_kind="rate_limit")
    registry.register_provider("mock-retry-429", provider)
    registry.models["test-429-model"] = ModelConfig(
        name="test-429-model",
        providers=[ProviderRoute(provider="mock-retry-429", upstream_model="m1")],
        price_per_1k=PricePer1K(Decimal("0.0"), Decimal("0.0")),
    )

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "test-429-model", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 200
    assert provider.call_count == 2  # 429 was retried and succeeded
    assert resp.headers["X-Maskgate-Fallback"] == "false"


@pytest.mark.asyncio
async def test_fallback_when_primary_fails(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    registry = get_model_registry()

    prov_a = CountingMockProvider(name="prov-fail-a", fail_times=10, fail_kind="server")
    prov_b = CountingMockProvider(name="prov-ok-b", fail_times=0)

    registry.register_provider("prov-fail-a", prov_a)
    registry.register_provider("prov-ok-b", prov_b)

    registry.models["test-fallback-model"] = ModelConfig(
        name="test-fallback-model",
        providers=[
            ProviderRoute(provider="prov-fail-a", upstream_model="a"),
            ProviderRoute(provider="prov-ok-b", upstream_model="b"),
        ],
        price_per_1k=PricePer1K(Decimal("0.0"), Decimal("0.0")),
    )

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "test-fallback-model", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 200
    # Provider A had 1 initial attempt + 2 retries = 3 attempts total
    assert prov_a.call_count == 3
    # Provider B was invoked and succeeded
    assert prov_b.call_count == 1
    assert resp.headers["X-Maskgate-Fallback"] == "true"
    assert resp.headers["X-Maskgate-Provider"] == "prov-ok-b"
    data = resp.json()
    assert "Hello from prov-ok-b" in data["choices"][0]["message"]["content"]


@pytest.mark.asyncio
async def test_client_error_not_retried(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    registry = get_model_registry()

    prov_400 = CountingMockProvider(name="prov-client-400", fail_times=10, fail_kind="client")
    prov_backup = CountingMockProvider(name="prov-backup-ok", fail_times=0)

    registry.register_provider("prov-client-400", prov_400)
    registry.register_provider("prov-backup-ok", prov_backup)

    registry.models["test-client-err-model"] = ModelConfig(
        name="test-client-err-model",
        providers=[
            ProviderRoute(provider="prov-client-400", upstream_model="a"),
            ProviderRoute(provider="prov-backup-ok", upstream_model="b"),
        ],
        price_per_1k=PricePer1K(Decimal("0.0"), Decimal("0.0")),
    )

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "test-client-err-model", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 200
    # 400 client error MUST NOT be retried: call_count is exactly 1
    assert prov_400.call_count == 1
    assert prov_backup.call_count == 1
    assert resp.headers["X-Maskgate-Fallback"] == "true"


@pytest.mark.asyncio
async def test_all_providers_failed_returns_502(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    registry = get_model_registry()

    prov_down_1 = CountingMockProvider(name="prov-down-1", fail_times=10, fail_kind="server")
    prov_down_2 = CountingMockProvider(name="prov-down-2", fail_times=10, fail_kind="timeout")

    registry.register_provider("prov-down-1", prov_down_1)
    registry.register_provider("prov-down-2", prov_down_2)

    registry.models["test-all-down-model"] = ModelConfig(
        name="test-all-down-model",
        providers=[
            ProviderRoute(provider="prov-down-1", upstream_model="a"),
            ProviderRoute(provider="prov-down-2", upstream_model="b"),
        ],
        price_per_1k=PricePer1K(Decimal("0.0"), Decimal("0.0")),
    )

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "test-all-down-model", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 502
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "all_providers_failed"
