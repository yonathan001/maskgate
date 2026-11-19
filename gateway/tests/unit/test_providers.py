import httpx
import pytest
import respx

from app.providers.anthropic import AnthropicProvider
from app.providers.base import ChatMessage, ChatRequest, ProviderError
from app.providers.openai import OpenAIProvider


@pytest.mark.asyncio
async def test_openai_provider_success() -> None:
    provider = OpenAIProvider(api_key="test-key", base_url="https://api.openai.com/v1")
    req = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hello OpenAI")],
    )

    with respx.mock(base_url="https://api.openai.com/v1") as respx_mock:
        respx_mock.post("/chat/completions").respond(
            200,
            json={
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "created": 1234567,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello from OpenAI mock!"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11},
            },
        )

        resp = await provider.chat(req)
        assert resp.id == "chatcmpl-123"
        assert resp.choices[0].message.content == "Hello from OpenAI mock!"
        assert resp.usage.total_tokens == 11


@pytest.mark.asyncio
async def test_openai_provider_errors() -> None:
    provider = OpenAIProvider(api_key="test-key", base_url="https://api.openai.com/v1")
    req = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
    )

    with respx.mock(base_url="https://api.openai.com/v1") as respx_mock:
        # Test 429 rate limit (retryable)
        respx_mock.post("/chat/completions").respond(429)
        with pytest.raises(ProviderError) as exc_info:
            await provider.chat(req)
        assert exc_info.value.kind == "rate_limit"
        assert exc_info.value.retryable is True

        # Test 500 server error (retryable)
        respx_mock.post("/chat/completions").respond(500)
        with pytest.raises(ProviderError) as exc_info:
            await provider.chat(req)
        assert exc_info.value.kind == "server"
        assert exc_info.value.retryable is True

        # Test 401 client error (non-retryable)
        respx_mock.post("/chat/completions").respond(401)
        with pytest.raises(ProviderError) as exc_info:
            await provider.chat(req)
        assert exc_info.value.kind == "client"
        assert exc_info.value.retryable is False

        # Test timeout error (retryable)
        respx_mock.post("/chat/completions").mock(side_effect=httpx.ReadTimeout("Timeout"))
        with pytest.raises(ProviderError) as exc_info:
            await provider.chat(req)
        assert exc_info.value.kind == "timeout"
        assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_anthropic_provider_success() -> None:
    provider = AnthropicProvider(api_key="test-key", base_url="https://api.anthropic.com/v1")
    req = ChatRequest(
        model="claude-3-5-haiku",
        messages=[
            ChatMessage(role="system", content="You are a helpful assistant"),
            ChatMessage(role="user", content="Hello Anthropic"),
        ],
    )

    with respx.mock(base_url="https://api.anthropic.com/v1") as respx_mock:
        route = respx_mock.post("/messages").respond(
            200,
            json={
                "id": "msg-123",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello from Claude!"}],
                "model": "claude-3-5-haiku",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 8},
            },
        )

        resp = await provider.chat(req)
        assert resp.id == "msg-123"
        assert resp.choices[0].message.content == "Hello from Claude!"
        assert resp.usage.prompt_tokens == 10
        assert resp.usage.completion_tokens == 8

        # Verify system prompt was passed top-level in payload
        assert route.called
        import json

        sent_payload = json.loads(route.calls.last.request.read().decode("utf-8"))
        assert sent_payload.get("system") == "You are a helpful assistant"


@pytest.mark.asyncio
async def test_anthropic_provider_errors() -> None:
    provider = AnthropicProvider(api_key="test-key", base_url="https://api.anthropic.com/v1")
    req = ChatRequest(
        model="claude-3-5-haiku",
        messages=[ChatMessage(role="user", content="Hi")],
    )

    with respx.mock(base_url="https://api.anthropic.com/v1") as respx_mock:
        # Test 529 overloaded (retryable)
        respx_mock.post("/messages").respond(529)
        with pytest.raises(ProviderError) as exc_info:
            await provider.chat(req)
        assert exc_info.value.kind == "rate_limit"
        assert exc_info.value.retryable is True

        # Test 400 bad request (non-retryable)
        respx_mock.post("/messages").respond(400)
        with pytest.raises(ProviderError) as exc_info:
            await provider.chat(req)
        assert exc_info.value.kind == "client"
        assert exc_info.value.retryable is False
