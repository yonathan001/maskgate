import time
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import AuthenticatedKey, authenticate_bearer_key
from app.core.cache import ResponseCache, build_cache_key, should_cache
from app.core.cost import calculate_cost
from app.core.errors import BadRequestError, ModelNotFoundError
from app.core.limits import LimitManager
from app.core.pipeline import RequestPipeline
from app.db.models import RequestRecord
from app.db.session import get_db
from app.providers.base import ChatMessage, ChatRequest
from app.providers.registry import get_model_registry

router = APIRouter(prefix="/v1", tags=["v1"])
pipeline = RequestPipeline()
limit_manager = LimitManager()
response_cache = ResponseCache()


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
) -> Any:
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

    # Step 2: Rate limits and monthly spend budget check
    await limit_manager.check_rate_limit(auth.id, auth.rate_limit_per_min)
    await limit_manager.check_budget(auth.id, auth.monthly_budget_usd, db)

    chat_req = ChatRequest(
        model=req.model,
        messages=[ChatMessage(role=m.role, content=m.content, name=m.name) for m in req.messages],
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
        stop=req.stop,
        stream=req.stream,
        user=req.user,
        tools=req.tools,
    )

    # Handle streaming request
    if req.stream:
        # Record stream request in background/DB
        stream_id = str(uuid.uuid4())
        request_record = RequestRecord(
            id=uuid.UUID(stream_id),
            key_id=auth.id,
            model=req.model,
            provider_used=model_config.providers[0].provider if model_config.providers else "none",
            fallback_used=False,
            cache_hit=False,
            streamed=True,
            status_code=200,
            latency_ms=0,
            gateway_overhead_ms=0,
            cost_usd=Decimal("0.0"),
            pii_count=0,
            pii_types=[],
            trace_id=None,
        )
        db.add(request_record)
        await db.commit()

        stream_gen = pipeline.execute_stream(chat_req, model_config, db)
        headers = {
            "X-Maskgate-Stream": "true",
            "X-Request-Id": stream_id,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
        return StreamingResponse(
            stream_gen,
            media_type="text/event-stream",
            headers=headers,
        )

    # Step 4: Cache check for non-streaming deterministic requests
    cache_key = None
    if should_cache(req.temperature):
        cache_key = build_cache_key(
            model=req.model,
            messages=[m.model_dump() for m in req.messages],
            temperature=req.temperature,
            top_p=req.top_p,
            max_tokens=req.max_tokens,
            stop=req.stop,
            tools=req.tools,
        )
        cached_data = await response_cache.get(cache_key)
        if cached_data is not None:
            request_id = str(uuid.uuid4())
            response.headers["X-Maskgate-Provider"] = cached_data.get("_provider", "mock")
            response.headers["X-Maskgate-Fallback"] = "false"
            response.headers["X-Maskgate-Cache"] = "hit"
            response.headers["X-Maskgate-PII-Count"] = "0"
            response.headers["X-Request-Id"] = request_id

            # Record cache hit in database (0 provider latency, 0 cost)
            rec = RequestRecord(
                id=uuid.UUID(request_id),
                key_id=auth.id,
                model=req.model,
                provider_used=cached_data.get("_provider", "mock"),
                fallback_used=False,
                cache_hit=True,
                streamed=False,
                status_code=200,
                latency_ms=int((time.perf_counter() - start_time) * 1000),
                gateway_overhead_ms=int((time.perf_counter() - start_time) * 1000),
                cost_usd=Decimal("0.0"),
                pii_count=0,
                pii_types=[],
                trace_id=None,
            )
            db.add(rec)
            await db.commit()

            # Clean internal metadata before returning
            clean_resp = {k: v for k, v in cached_data.items() if not k.startswith("_")}
            return clean_resp

    pipeline_result = await pipeline.execute(chat_req, model_config, db)
    chat_resp = pipeline_result.response

    end_time = time.perf_counter()
    total_latency_ms = int((end_time - start_time) * 1000)
    provider_ms = pipeline_result.provider_latency_ms
    gateway_overhead_ms = max(0, total_latency_ms - provider_ms)

    request_id = str(uuid.uuid4())

    # Set response headers as specified in Section 8
    response.headers["X-Maskgate-Provider"] = pipeline_result.provider_used
    response.headers["X-Maskgate-Fallback"] = "true" if pipeline_result.fallback_used else "false"
    response.headers["X-Maskgate-Cache"] = "miss"
    response.headers["X-Maskgate-PII-Count"] = "0"
    response.headers["X-Request-Id"] = request_id

    # Calculate cost using model pricing
    cost_usd = Decimal("0.0")
    if model_config.price_per_1k:
        cost_usd = calculate_cost(
            prompt_tokens=chat_resp.usage.prompt_tokens,
            completion_tokens=chat_resp.usage.completion_tokens,
            price_input_per_1k=model_config.price_per_1k.input,
            price_output_per_1k=model_config.price_per_1k.output,
        )

    # Record spend in Redis counter
    await limit_manager.record_spend(auth.id, cost_usd)

    # Record request metadata in database (no raw prompt/response logged)
    request_record = RequestRecord(
        id=uuid.UUID(request_id),
        key_id=auth.id,
        model=req.model,
        provider_used=pipeline_result.provider_used,
        fallback_used=pipeline_result.fallback_used,
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

    resp_payload = {
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

    # Store in cache if cacheable
    if cache_key is not None:
        cache_data_to_store = dict(resp_payload)
        cache_data_to_store["_provider"] = pipeline_result.provider_used
        await response_cache.set(cache_key, cache_data_to_store)

    return resp_payload
