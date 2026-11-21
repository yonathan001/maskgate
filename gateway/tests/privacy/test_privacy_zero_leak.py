import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import APIKey, RequestRecord
from app.providers.base import (
    ChatChoice,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Usage,
)
from app.providers.registry import ModelConfig, PricePer1K, ProviderRoute, get_model_registry


class InspectionMockProvider:
    """Mock provider that records the exact raw prompt received."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.last_received_messages: list[ChatMessage] = []

    async def chat(self, req: ChatRequest) -> ChatResponse:
        self.last_received_messages = req.messages
        # Echo back placeholders in reply
        content = " ".join(m.content for m in req.messages)
        return ChatResponse(
            id=f"chatcmpl-{self.name}",
            model=req.model,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=f"Echo: {content}"),
                )
            ],
            usage=Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    async def chat_stream(self, req: ChatRequest):  # type: ignore[no-untyped-def]
        yield  # type: ignore[misc]


@pytest.mark.asyncio
async def test_privacy_zero_leak_to_provider_and_database(
    client: AsyncClient, created_api_key: tuple[str, APIKey], db_session: AsyncSession
) -> None:
    raw_key, key_obj = created_api_key
    registry = get_model_registry()

    mock_prov = InspectionMockProvider(name="privacy-inspector")
    registry.register_provider("privacy-inspector", mock_prov)
    registry.models["privacy-model"] = ModelConfig(
        name="privacy-model",
        providers=[ProviderRoute(provider="privacy-inspector", upstream_model="m1")],
        price_per_1k=PricePer1K(),
    )

    # Synthetic PII data: Email and Ethiopian Phone Number
    synthetic_email = "synthetic.user.987@testdomain.com"
    synthetic_phone = "+251911998877"
    raw_prompt = f"Please contact {synthetic_email} or call {synthetic_phone} immediately."

    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {
        "model": "privacy-model",
        "messages": [{"role": "user", "content": raw_prompt}],
    }

    resp = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp.status_code == 200

    # 1. Assert response header records PII count
    assert int(resp.headers.get("X-Maskgate-PII-Count", "0")) >= 2

    # 2. Assert client gets restored output
    data = resp.json()
    reply = data["choices"][0]["message"]["content"]
    assert synthetic_email in reply
    assert synthetic_phone in reply

    # 3. CRITICAL PRIVACY CHECK: Verify what upstream provider received
    upstream_body = " ".join(m.content for m in mock_prov.last_received_messages)
    assert synthetic_email not in upstream_body, (
        "CRITICAL LEAK: Raw email was sent to upstream provider!"
    )
    assert synthetic_phone not in upstream_body, (
        "CRITICAL LEAK: Raw phone was sent to upstream provider!"
    )
    assert "<EMAIL_" in upstream_body or "<EMAIL_ADDRESS_" in upstream_body
    assert "<PHONE_" in upstream_body or "<PHONE_NUMBER_" in upstream_body

    # 4. CRITICAL PRIVACY CHECK: Verify DB requests record contains NO private values
    stmt = select(RequestRecord).where(RequestRecord.key_id == key_obj.id)
    records = (await db_session.execute(stmt)).scalars().all()
    assert len(records) > 0
    latest = records[-1]
    assert latest.pii_count >= 2
    assert "EMAIL_ADDRESS" in latest.pii_types or "EMAIL" in latest.pii_types
    # Verify no raw prompt column exists in RequestRecord
    assert not hasattr(latest, "prompt")
    assert not hasattr(latest, "response")
