import asyncio
import json
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AllProvidersFailedError
from app.db.models import ProviderHealth
from app.providers.base import ChatRequest, ChatResponse, ProviderError
from app.providers.registry import ModelConfig, get_model_registry


@dataclass
class PipelineResult:
    response: ChatResponse
    provider_used: str
    fallback_used: bool
    provider_latency_ms: int


async def update_provider_health(
    provider_name: str,
    status: str,  # ok | degraded | down
    last_error: str | None,
    db: AsyncSession | None,
) -> None:
    if db is None:
        return
    try:
        stmt = select(ProviderHealth).where(ProviderHealth.provider == provider_name)
        result = await db.execute(stmt)
        record = result.scalars().first()
        if record:
            record.status = status
            record.last_error = last_error
        else:
            record = ProviderHealth(
                provider=provider_name,
                status=status,
                last_error=last_error,
            )
            db.add(record)
        await db.commit()
    except Exception:
        # Avoid crashing pipeline if health DB update fails
        await db.rollback()


class RequestPipeline:
    def __init__(
        self,
        base_backoff_seconds: float = 0.05,  # fast for low overhead / tests
        max_backoff_seconds: float = 2.0,
    ) -> None:
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds

    async def execute(
        self,
        req: ChatRequest,
        model_config: ModelConfig,
        db: AsyncSession | None = None,
    ) -> PipelineResult:
        settings = get_settings()
        registry = get_model_registry()

        last_error: Exception | None = None

        for route_idx, route in enumerate(model_config.providers):
            provider = registry.get_provider(route.provider)
            if not provider:
                continue

            fallback_used = route_idx > 0
            req.upstream_model = route.upstream_model

            attempts = 0
            max_attempts = 1 + settings.max_retries

            while attempts < max_attempts:
                attempts += 1
                try:
                    start_time = asyncio.get_running_loop().time()
                    resp = await asyncio.wait_for(
                        provider.chat(req),
                        timeout=float(settings.provider_attempt_timeout_seconds),
                    )
                    end_time = asyncio.get_running_loop().time()
                    latency_ms = int((end_time - start_time) * 1000)

                    # Update provider health to ok
                    await update_provider_health(provider.name, "ok", None, db)

                    return PipelineResult(
                        response=resp,
                        provider_used=provider.name,
                        fallback_used=fallback_used,
                        provider_latency_ms=latency_ms,
                    )

                except ProviderError as pe:
                    last_error = pe
                    # 4xx client errors (except 429) must never be retried
                    if not pe.retryable:
                        break

                    # If retryable and attempts remaining, apply backoff with jitter
                    if attempts < max_attempts:
                        delay = min(
                            self.max_backoff_seconds,
                            self.base_backoff_seconds * (2 ** (attempts - 1)),
                        ) + random.uniform(0.001, 0.05)
                        await asyncio.sleep(delay)

                except TimeoutError:
                    last_error = ProviderError(
                        message=f"Timeout after {settings.provider_attempt_timeout_seconds}s",
                        kind="timeout",
                        status_code=504,
                        retryable=True,
                        provider=provider.name,
                    )
                    if attempts < max_attempts:
                        delay = min(
                            self.max_backoff_seconds,
                            self.base_backoff_seconds * (2 ** (attempts - 1)),
                        ) + random.uniform(0.001, 0.05)
                        await asyncio.sleep(delay)

                except Exception as ex:
                    last_error = ex
                    break

            # If all attempts for this provider failed, mark as degraded or down
            await update_provider_health(
                provider.name,
                "down",
                str(last_error) if last_error else "Failed after retries",
                db,
            )

        # All providers exhausted
        err_msg = f"All providers failed to fulfill request. Last error: {last_error}"
        raise AllProvidersFailedError(err_msg)

    async def execute_stream(
        self,
        req: ChatRequest,
        model_config: ModelConfig,
        db: AsyncSession | None = None,
    ) -> AsyncIterator[str]:
        registry = get_model_registry()
        last_error: Exception | None = None

        for _route_idx, route in enumerate(model_config.providers):
            provider = registry.get_provider(route.provider)
            if not provider:
                continue

            req.upstream_model = route.upstream_model
            first_chunk_sent = False

            try:
                stream_iter = provider.chat_stream(req)
                async for chunk in stream_iter:
                    first_chunk_sent = True
                    # Serialize chunk to OpenAI SSE event format
                    chunk_dict = {
                        "id": chunk.id,
                        "object": chunk.object,
                        "created": chunk.created,
                        "model": req.model,
                        "choices": [
                            {
                                "index": c.index,
                                "delta": {
                                    k: v
                                    for k, v in [
                                        ("role", c.delta.role),
                                        ("content", c.delta.content),
                                    ]
                                    if v is not None
                                },
                                "finish_reason": c.finish_reason,
                            }
                            for c in chunk.choices
                        ],
                    }
                    yield f"data: {json.dumps(chunk_dict)}\n\n"

                # Stream completed successfully
                yield "data: [DONE]\n\n"
                await update_provider_health(provider.name, "ok", None, db)
                return

            except Exception as e:
                last_error = e
                await update_provider_health(provider.name, "down", str(e), db)

                if first_chunk_sent:
                    # Stream already started, cannot fallback: emit error event and end cleanly
                    err_payload = {
                        "error": {
                            "message": f"Stream interrupted: {e}",
                            "type": "server_error",
                            "code": "stream_error",
                        }
                    }
                    yield f"data: {json.dumps(err_payload)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                # Otherwise, fallback to next provider route

        # All providers failed before first chunk was sent
        err_payload = {
            "error": {
                "message": (
                    f"All providers failed to fulfill streaming request. Last error: {last_error}"
                ),
                "type": "bad_gateway",
                "code": "all_providers_failed",
            }
        }
        yield f"data: {json.dumps(err_payload)}\n\n"
        yield "data: [DONE]\n\n"
