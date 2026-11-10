import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import APIKey, RequestRecord


@pytest.mark.asyncio
async def test_chat_completions_missing_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "mock-fast", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_chat_completions_invalid_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer invalid_key_12345"},
        json={"model": "mock-fast", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_chat_completions_model_not_found(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "non-existent-model", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "model_not_found"


@pytest.mark.asyncio
async def test_chat_completions_empty_messages(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "mock-fast", "messages": []},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "bad_request"


@pytest.mark.asyncio
async def test_chat_completions_success(
    client: AsyncClient,
    created_api_key: tuple[str, APIKey],
    db_session: AsyncSession,
) -> None:
    raw_key, key_obj = created_api_key
    payload = {
        "model": "mock-fast",
        "messages": [{"role": "user", "content": "Hello Maskgate!"}],
    }

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json=payload,
    )

    assert resp.status_code == 200
    # Check headers
    assert resp.headers["X-Maskgate-Provider"] == "mock"
    assert resp.headers["X-Maskgate-Fallback"] == "false"
    assert resp.headers["X-Maskgate-Cache"] == "miss"
    assert resp.headers["X-Maskgate-PII-Count"] == "0"
    assert "X-Request-Id" in resp.headers

    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["model"] == "mock-fast"
    assert len(data["choices"]) == 1
    assert "Mock response for: Hello Maskgate!" in data["choices"][0]["message"]["content"]
    assert data["usage"]["total_tokens"] > 0

    # Verify request record was persisted without raw prompt/response
    stmt = select(RequestRecord).where(RequestRecord.key_id == key_obj.id)
    result = await db_session.execute(stmt)
    records = result.scalars().all()
    assert len(records) >= 1
    latest = records[-1]
    assert latest.model == "mock-fast"
    assert latest.status_code == 200
    assert latest.provider_used == "mock"


@pytest.mark.asyncio
async def test_list_models(
    client: AsyncClient, created_api_key: tuple[str, APIKey]
) -> None:
    raw_key, _ = created_api_key
    resp = await client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    ids = [item["id"] for item in data["data"]]
    assert "mock-fast" in ids
