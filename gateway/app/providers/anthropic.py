import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import get_settings
from app.providers.base import (
    ChatChoice,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ProviderError,
    Usage,
)


class AnthropicProvider:
    name: str = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com/v1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or get_settings().anthropic_api_key
        self.base_url = base_url.rstrip("/")
        self._client = client

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=get_settings().provider_attempt_timeout_seconds,
        )

    def _normalize_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, httpx.TimeoutException):
            return ProviderError(
                message=f"Anthropic request timeout: {exc}",
                kind="timeout",
                status_code=504,
                retryable=True,
                provider=self.name,
            )
        if isinstance(exc, httpx.NetworkError):
            return ProviderError(
                message=f"Anthropic network error: {exc}",
                kind="network",
                status_code=502,
                retryable=True,
                provider=self.name,
            )
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in [429, 529]:
                return ProviderError(
                    message="Anthropic rate limit or overloaded",
                    kind="rate_limit",
                    status_code=429,
                    retryable=True,
                    provider=self.name,
                )
            if status >= 500:
                return ProviderError(
                    message=f"Anthropic server error ({status})",
                    kind="server",
                    status_code=status,
                    retryable=True,
                    provider=self.name,
                )
            return ProviderError(
                message=f"Anthropic client error ({status})",
                kind="client",
                status_code=status,
                retryable=False,
                provider=self.name,
            )
        return ProviderError(
            message=str(exc),
            kind="server",
            status_code=500,
            retryable=False,
            provider=self.name,
        )

    async def chat(self, req: ChatRequest) -> ChatResponse:
        model_name = req.upstream_model or req.model

        # Extract system messages for Anthropic top-level 'system' parameter
        system_prompts: list[str] = []
        anthropic_messages: list[dict[str, str]] = []

        for m in req.messages:
            if m.role == "system":
                system_prompts.append(m.content)
            else:
                # Anthropic expects "user" or "assistant"
                role = "user" if m.role not in ["assistant"] else "assistant"
                anthropic_messages.append({"role": role, "content": m.content})

        if not anthropic_messages:
            # Handle edge case where only system prompt was provided
            anthropic_messages.append({"role": "user", "content": "Hello"})

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": anthropic_messages,
            "max_tokens": req.max_tokens or 4096,
        }
        if system_prompts:
            payload["system"] = "\n\n".join(system_prompts)
        if req.temperature is not None:
            payload["temperature"] = req.temperature
        if req.top_p is not None:
            payload["top_p"] = req.top_p

        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        client = self._get_client()
        should_close = self._client is None
        try:
            resp = await client.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            # Extract text from content blocks
            content_blocks = data.get("content", [])
            text_chunks = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
            full_reply = "".join(text_chunks)

            raw_usage = data.get("usage", {})
            input_tokens = raw_usage.get("input_tokens", 0)
            output_tokens = raw_usage.get("output_tokens", 0)

            return ChatResponse(
                id=data.get("id", f"msg-{int(time.time())}"),
                object="chat.completion",
                created=int(time.time()),
                model=req.model,
                choices=[
                    ChatChoice(
                        index=0,
                        message=ChatMessage(role="assistant", content=full_reply),
                        finish_reason="stop",
                    )
                ],
                usage=Usage(
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                ),
            )
        except Exception as e:
            raise self._normalize_error(e) from e
        finally:
            if should_close:
                await client.aclose()

    async def chat_stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        yield ChatChunk(id="stub")
