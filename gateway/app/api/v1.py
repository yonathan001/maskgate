from decimal import Decimal
import time
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import AuthenticatedKey, authenticate_bearer_key
from app.core.errors import BadRequestError, ModelNotFoundError
from app.db.models import RequestRecord
from app.db.session import get_db
from app.providers.base import ChatMessage, ChatRequest
from app.providers.registry import get_model_registry

router = APIRouter(prefix="/v1", tags=["v1"])


class MessageInput(BaseModel):
    role: str
    content: str
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[MessageInput]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | str | None = None
    stream: bool = False
    user: str | None = None
    tools: list[dict[str, Any]] | None = None


@router.get("/models")
async def list_models(
    auth: AuthenticatedKey = Depends(authenticate_bearer_key),
) -> dict[str, Any]:
    registry = get_model_registry()
    model_names = registry.list_models()
    created_ts = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": name,
                "object": "model",
                "created": created_ts,
                "owned_by": "maskgate",
                "permission": [],
                "root": name,
                "parent": None,
            }
            for name in model_names
        ],
    }


@router.post("/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    response: Response,
    auth: AuthenticatedKey = Depends(authenticate_bearer_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    start_time = time.perf_counter()
    settings = get_settings()
    registry = get_model_registry()

    model_config = registry.get_model(req.model)
    if not model_config:
        raise ModelNotFoundError(req.model)

    if not req.messages:
        raise BadRequestError("Messages array cannot be empty")

    total_chars = sum(len(m.content) for m in req.messages)
    if total_chars > settings.max_prompt_chars:
        raise BadRequestError(
            f"Prompt exceeds maximum character length of {settings.max_prompt_chars}"
        )

    # For Phase 1: resolve the primary route and provider
    route = model_config.providers[0]
    provider = registry.get_provider(route.provider)
    if not provider:
        raise ModelNotFoundError(f"Provider '{route.provider}' is not configured")

    chat_req = ChatRequest(
        model=req.model,
        messages=[
            ChatMessage(role=m.role, content=m.content, name=m.name)
            for m in req.messages
        ],
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
        stop=req.stop,
        stream=req.stream,
        user=req.user,
        tools=req.tools,
        upstream_model=route.upstream_model,
    )

    prov_start = time.perf_counter()
    chat_resp = await provider.chat(chat_req)
    prov_end = time.perf_counter()

    end_time = time.perf_counter()
    total_latency_ms = int((end_time - start_time) * 1000)
    provider_ms = int((prov_end - prov_start) * 1000)
    gateway_overhead_ms = max(0, total_latency_ms - provider_ms)

    request_id = str(uuid.uuid4())

    # Set response headers as specified in Section 8
    response.headers["X-Maskgate-Provider"] = provider.name
    response.headers["X-Maskgate-Fallback"] = "false"
    response.headers["X-Maskgate-Cache"] = "miss"
    response.headers["X-Maskgate-PII-Count"] = "0"
    response.headers["X-Request-Id"] = request_id

    # Calculate cost
    cost_usd = Decimal("0.0")
    if model_config.price_per_1k:
        input_cost = (
            Decimal(chat_resp.usage.prompt_tokens)
            / Decimal(1000)
            * model_config.price_per_1k.input
        )
        output_cost = (
            Decimal(chat_resp.usage.completion_tokens)
            / Decimal(1000)
            * model_config.price_per_1k.output
        )
        cost_usd = input_cost + output_cost

    # Record request metadata in database (no raw prompt/response logged)
    request_record = RequestRecord(
        id=uuid.UUID(request_id),
        key_id=auth.id,
        model=req.model,
        provider_used=provider.name,
        fallback_used=False,
        cache_hit=False,
        streamed=False,
        status_code=200,
        latency_ms=total_latency_ms,
        gateway_overhead_ms=gateway_overhead_ms,
        input_tokens=chat_resp.usage.prompt_tokens,
        output_tokens=chat_resp.usage.completion_tokens,
        cost_usd=cost_usd,
        pii_count=0,
        pii_types=[],
        trace_id=None,
    )
    db.add(request_record)
    await db.commit()

    return {
        "id": chat_resp.id,
        "object": chat_resp.object,
        "created": chat_resp.created,
        "model": req.model,
        "choices": [
            {
                "index": c.index,
                "message": {
                    "role": c.message.role,
                    "content": c.message.content,
                },
                "finish_reason": c.finish_reason,
            }
            for c in chat_resp.choices
        ],
        "usage": {
            "prompt_tokens": chat_resp.usage.prompt_tokens,
            "completion_tokens": chat_resp.usage.completion_tokens,
            "total_tokens": chat_resp.usage.total_tokens,
        },
    }
