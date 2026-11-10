import asyncio
from collections.abc import AsyncIterator
import time
import uuid

from app.providers.base import (
    ChatChoice,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChunkChoice,
    ChunkDelta,
    ProviderError,
    Usage,
)


class MockProvider:
    name: str = "mock"

    def __init__(self, failure_mode: str | None = None, latency_seconds: float = 0.0) -> None:
        self.failure_mode = failure_mode
        self.latency_seconds = latency_seconds

    def set_failure_mode(self, mode: str | None) -> None:
        self.failure_mode = mode

    def _check_failure(self) -> None:
        if not self.failure_mode:
            return
        if self.failure_mode == "500":
            raise ProviderError(
                message="Mock provider internal server error (500)",
                kind="server",
                status_code=500,
                retryable=True,
                provider=self.name,
            )
        if self.failure_mode == "429":
            raise ProviderError(
                message="Mock provider rate limit exceeded (429)",
                kind="rate_limit",
                status_code=429,
                retryable=True,
                provider=self.name,
            )
        if self.failure_mode == "timeout":
            raise ProviderError(
                message="Mock provider request timed out",
                kind="timeout",
                status_code=504,
                retryable=True,
                provider=self.name,
            )
        if self.failure_mode == "400":
            raise ProviderError(
                message="Mock provider client error (400)",
                kind="client",
                status_code=400,
                retryable=False,
                provider=self.name,
            )

    async def chat(self, req: ChatRequest) -> ChatResponse:
        if self.latency_seconds > 0:
            await asyncio.sleep(self.latency_seconds)

        self._check_failure()

        last_user_content = ""
        for m in reversed(req.messages):
            if m.role == "user":
                last_user_content = m.content
                break

        # Generate a deterministic response
        reply_content = f"Mock response for: {last_user_content}" if last_user_content else "Hello from Mock Provider!"
        
        # Calculate approximate token counts
        input_text = " ".join(m.content for m in req.messages)
        prompt_tokens = max(1, len(input_text.split()))
        completion_tokens = max(1, len(reply_content.split()))

        return ChatResponse(
            id=f"chatcmpl-mock-{uuid.uuid4().hex[:8]}",
            object="chat.completion",
            created=int(time.time()),
            model=req.model,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=reply_content),
                    finish_reason="stop",
                )
            ],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    async def chat_stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        if self.latency_seconds > 0:
            await asyncio.sleep(self.latency_seconds)

        self._check_failure()

        last_user_content = ""
        for m in reversed(req.messages):
            if m.role == "user":
                last_user_content = m.content
                break

        reply_content = f"Mock response for: {last_user_content}" if last_user_content else "Hello from Mock Provider!"
        req_id = f"chatcmpl-mock-{uuid.uuid4().hex[:8]}"
        created = int(time.time())

        # Yield role delta
        yield ChatChunk(
            id=req_id,
            created=created,
            model=req.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=ChunkDelta(role="assistant"),
                    finish_reason=None,
                )
            ],
        )

        # Split reply into words to simulate streaming
        words = reply_content.split(" ")
        for i, word in enumerate(words):
            if self.failure_mode == "stream_cut" and i == 2:
                raise ProviderError(
                    message="Stream cut midway",
                    kind="network",
                    status_code=500,
                    retryable=False,
                    provider=self.name,
                )
            chunk_text = word if i == 0 else " " + word
            yield ChatChunk(
                id=req_id,
                created=created,
                model=req.model,
                choices=[
                    ChunkChoice(
                        index=0,
                        delta=ChunkDelta(content=chunk_text),
                        finish_reason=None,
                    )
                ],
            )

        # Final stop chunk
        yield ChatChunk(
            id=req_id,
            created=created,
            model=req.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=ChunkDelta(),
                    finish_reason="stop",
                )
            ],
        )
