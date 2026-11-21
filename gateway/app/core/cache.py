import hashlib
import json
from typing import Any

from app.core.limits import get_redis


def build_cache_key(
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    stop: Any = None,
    tools: Any = None,
) -> str:
    """
    Builds a deterministic SHA-256 cache key from canonical JSON of request parameters.
    """
    canonical_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "stop": stop,
        "tools": tools,
    }
    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"cache:{digest}"


def should_cache(temperature: float | None = None) -> bool:
    """
    Determines if the request is eligible for caching.
    By default, only deterministic requests (temperature == 0 or None) are cached.
    """
    if temperature is None:
        return True
    return temperature == 0.0


class ResponseCache:
    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    @property
    def redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        return get_redis()

    async def get(self, cache_key: str) -> dict[str, Any] | None:
        try:
            raw = await self.redis.get(cache_key)
            if raw:
                val = json.loads(raw)
                if isinstance(val, dict):
                    return val
        except Exception:
            # Per ADR 1: fail open on cache errors
            pass
        return None

    async def set(self, cache_key: str, data: dict[str, Any], ttl_seconds: int = 3600) -> None:
        try:
            payload = json.dumps(data)
            await self.redis.set(cache_key, payload, ex=ttl_seconds)
        except Exception:
            pass
