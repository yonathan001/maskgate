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


class OpenAIProvider:
    name: str = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or get_settings().openai_api_key
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
                message=f"OpenAI request timeout: {exc}",
                kind="timeout",
                status_code=504,
                retryable=True,
                provider=self.name,
            )
        if isinstance(exc, httpx.NetworkError):
            return ProviderError(
                message=f"OpenAI network error: {exc}",
                kind="network",
                status_code=502,
                retryable=True,
                provider=self.name,
            )
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status == 429:
                return ProviderError(
                    message="OpenAI rate limit exceeded",
                    kind="rate_limit",
                    status_code=429,
                    retryable=True,
                    provider=self.name,
                )
            if status >= 500:
                return ProviderError(
                    message=f"OpenAI server error ({status})",
                    kind="server",
                    status_code=status,
                    retryable=True,
                    provider=self.name,
                )
            return ProviderError(
                message=f"OpenAI client error ({status})",
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
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": m.role, "content": m.content, **({"name": m.name} if m.name else {})}
                for m in req.messages
            ],
            "stream": False,
        }
        if req.temperature is not None:
            payload["temperature"] = req.temperature
        if req.top_p is not None:
            payload["top_p"] = req.top_p
        if req.max_tokens is not None:
            payload["max_tokens"] = req.max_tokens
        if req.stop is not None:
            payload["stop"] = req.stop
        if req.tools is not None:
            payload["tools"] = req.tools
        if req.user is not None:
            payload["user"] = req.user

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        client = self._get_client()
        should_close = self._client is None
        try:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            choices = [
                ChatChoice(
                    index=c.get("index", idx),
                    message=ChatMessage(
                        role=c.get("message", {}).get("role", "assistant"),
                        content=c.get("message", {}).get("content", ""),
                    ),
                    finish_reason=c.get("finish_reason", "stop"),
                )
                for idx, c in enumerate(data.get("choices", []))
            ]

            raw_usage = data.get("usage", {})
            usage = Usage(
                prompt_tokens=raw_usage.get("prompt_tokens", 0),
                completion_tokens=raw_usage.get("completion_tokens", 0),
                total_tokens=raw_usage.get("total_tokens", 0),
            )

            return ChatResponse(
                id=data.get("id", f"chatcmpl-oai-{int(time.time())}"),
                object=data.get("object", "chat.completion"),
                created=data.get("created", int(time.time())),
                model=req.model,
                choices=choices,
                usage=usage,
            )
        except Exception as e:
            raise self._normalize_error(e) from e
        finally:
            if should_close:
                await client.aclose()

    async def chat_stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        # Implementation for Phase 4 streaming
        yield ChatChunk(id="stub")
