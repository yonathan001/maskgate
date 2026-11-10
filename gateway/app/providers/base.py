from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
import uuid


@dataclass
class ChatMessage:
    role: str
    content: str
    name: str | None = None


@dataclass
class ChatRequest:
    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | str | None = None
    stream: bool = False
    user: str | None = None
    tools: list[dict[str, Any]] | None = None
    upstream_model: str | None = None


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatChoice:
    index: int
    message: ChatMessage
    finish_reason: str = "stop"


@dataclass
class ChatResponse:
    id: str = field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list[ChatChoice] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class ChunkDelta:
    role: str | None = None
    content: str | None = None


@dataclass
class ChunkChoice:
    index: int
    delta: ChunkDelta
    finish_reason: str | None = None


@dataclass
class ChatChunk:
    id: str
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: list[ChunkChoice] = field(default_factory=list)


ProviderErrorKind = Literal["timeout", "rate_limit", "server", "client", "network"]


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        kind: ProviderErrorKind,
        status_code: int = 500,
        retryable: bool = False,
        provider: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.status_code = status_code
        self.retryable = retryable
        self.provider = provider


class Provider(Protocol):
    name: str

    async def chat(self, req: ChatRequest) -> ChatResponse: ...

    def chat_stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]: ...
