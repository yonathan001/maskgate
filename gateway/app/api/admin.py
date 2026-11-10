import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import generate_api_key
from app.core.errors import AuthenticationError
from app.db.models import APIKey, AuditLog, ProviderHealth, RequestRecord
from app.db.session import get_db
from app.providers.mock import MockProvider
from app.providers.registry import get_model_registry

router = APIRouter(prefix="/admin", tags=["admin"])


async def verify_admin_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    settings = get_settings()
    token = x_admin_token
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]

    if not token or token != settings.admin_token:
        raise AuthenticationError("Invalid or missing admin token")


class CreateKeyRequest(BaseModel):
    name: str
    monthly_budget_usd: Decimal = Field(default=Decimal("10.0000"))
    rate_limit_per_min: int = Field(default=60)
    redaction_enabled: bool = Field(default=True)


class KeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    monthly_budget_usd: Decimal
    rate_limit_per_min: int
    redaction_enabled: bool
    active: bool
    created_at: datetime
    key: str | None = None  # Returned only on creation


class UpdateKeyRequest(BaseModel):
    name: str | None = None
    monthly_budget_usd: Decimal | None = None
    rate_limit_per_min: int | None = None
    redaction_enabled: bool | None = None
    active: bool | None = None


@router.post("/keys", response_model=KeyResponse, dependencies=[Depends(verify_admin_token)])
async def create_key(
    req: CreateKeyRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    key_id = uuid.uuid4()
    raw_key, key_prefix, key_hash = generate_api_key()
    key_obj = APIKey(
        id=key_id,
        name=req.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        monthly_budget_usd=req.monthly_budget_usd,
        rate_limit_per_min=req.rate_limit_per_min,
        redaction_enabled=req.redaction_enabled,
        active=True,
    )
    db.add(key_obj)

    audit = AuditLog(
        actor="admin",
        action="key.created",
        entity=f"api_key:{key_id}",
        after={"name": req.name, "key_prefix": key_prefix},
    )
    db.add(audit)
    await db.commit()
    await db.refresh(key_obj)

    return KeyResponse(
        id=key_obj.id,
        name=key_obj.name,
        key_prefix=key_obj.key_prefix,
        monthly_budget_usd=key_obj.monthly_budget_usd,
        rate_limit_per_min=key_obj.rate_limit_per_min,
        redaction_enabled=key_obj.redaction_enabled,
        active=key_obj.active,
        created_at=key_obj.created_at,
        key=raw_key,
    )


@router.get("/keys", response_model=list[KeyResponse], dependencies=[Depends(verify_admin_token)])
async def list_keys(
    db: AsyncSession = Depends(get_db),
) -> Any:
    stmt = select(APIKey).order_by(desc(APIKey.created_at))
    result = await db.execute(stmt)
    keys = result.scalars().all()
    return [
        KeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            monthly_budget_usd=k.monthly_budget_usd,
            rate_limit_per_min=k.rate_limit_per_min,
            redaction_enabled=k.redaction_enabled,
            active=k.active,
            created_at=k.created_at,
            key=None,
        )
        for k in keys
    ]


@router.patch(
    "/keys/{key_id}",
    response_model=KeyResponse,
    dependencies=[Depends(verify_admin_token)],
)
async def update_key(
    key_id: uuid.UUID,
    req: UpdateKeyRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    key_obj = await db.get(APIKey, key_id)
    if not key_obj:
        raise HTTPException(status_code=404, detail="API key not found")

    before = {
        "name": key_obj.name,
        "monthly_budget_usd": float(key_obj.monthly_budget_usd),
        "rate_limit_per_min": key_obj.rate_limit_per_min,
        "redaction_enabled": key_obj.redaction_enabled,
        "active": key_obj.active,
    }

    if req.name is not None:
        key_obj.name = req.name
    if req.monthly_budget_usd is not None:
        key_obj.monthly_budget_usd = req.monthly_budget_usd
    if req.rate_limit_per_min is not None:
        key_obj.rate_limit_per_min = req.rate_limit_per_min
    if req.redaction_enabled is not None:
        key_obj.redaction_enabled = req.redaction_enabled
    if req.active is not None:
        key_obj.active = req.active

    after = {
        "name": key_obj.name,
        "monthly_budget_usd": float(key_obj.monthly_budget_usd),
        "rate_limit_per_min": key_obj.rate_limit_per_min,
        "redaction_enabled": key_obj.redaction_enabled,
        "active": key_obj.active,
    }

    audit = AuditLog(
        actor="admin",
        action="key.updated",
        entity=f"api_key:{key_obj.id}",
        before=before,
        after=after,
    )
    db.add(audit)
    await db.commit()
    await db.refresh(key_obj)

    return KeyResponse(
        id=key_obj.id,
        name=key_obj.name,
        key_prefix=key_obj.key_prefix,
        monthly_budget_usd=key_obj.monthly_budget_usd,
        rate_limit_per_min=key_obj.rate_limit_per_min,
        redaction_enabled=key_obj.redaction_enabled,
        active=key_obj.active,
        created_at=key_obj.created_at,
        key=None,
    )


@router.get("/usage", dependencies=[Depends(verify_admin_token)])
async def get_usage(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(
            RequestRecord.key_id,
            func.date_trunc("day", RequestRecord.created_at).label("day"),
            func.count(RequestRecord.id).label("requests_count"),
            func.coalesce(func.sum(RequestRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(RequestRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(RequestRecord.cost_usd), Decimal("0.0")).label("total_cost_usd"),
        )
        .where(RequestRecord.created_at >= since)
        .group_by(RequestRecord.key_id, "day")
        .order_by("day")
    )
    result = await db.execute(stmt)
    rows = result.all()
    usage_data = [
        {
            "key_id": str(r.key_id),
            "day": r.day.isoformat() if hasattr(r.day, "isoformat") else str(r.day),
            "requests_count": r.requests_count,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "total_cost_usd": float(r.total_cost_usd),
        }
        for r in rows
    ]
    return {"days": days, "usage": usage_data}


@router.get("/requests", dependencies=[Depends(verify_admin_token)])
async def get_recent_requests(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(RequestRecord).order_by(desc(RequestRecord.created_at)).limit(limit)
    result = await db.execute(stmt)
    records = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "key_id": str(r.key_id),
            "model": r.model,
            "provider_used": r.provider_used,
            "fallback_used": r.fallback_used,
            "cache_hit": r.cache_hit,
            "streamed": r.streamed,
            "status_code": r.status_code,
            "error_kind": r.error_kind,
            "latency_ms": r.latency_ms,
            "gateway_overhead_ms": r.gateway_overhead_ms,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None,
            "pii_count": r.pii_count,
            "pii_types": r.pii_types,
            "trace_id": r.trace_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


@router.get("/providers", dependencies=[Depends(verify_admin_token)])
async def get_provider_health(
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(ProviderHealth)
    result = await db.execute(stmt)
    records = result.scalars().all()
    return [
        {
            "provider": r.provider,
            "status": r.status,
            "last_error": r.last_error,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in records
    ]


class ProviderDownRequest(BaseModel):
    provider: str
    error_mode: str = "500"  # 500, 429, timeout, etc.


@router.post("/demo/provider-down", dependencies=[Depends(verify_admin_token)])
async def demo_provider_down(
    req: ProviderDownRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    settings = get_settings()
    if not settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo endpoints are disabled when DEMO_MODE=false",
        )

    registry = get_model_registry()
    provider = registry.get_provider(req.provider)
    if isinstance(provider, MockProvider):
        provider.set_failure_mode(req.error_mode)

    stmt = select(ProviderHealth).where(ProviderHealth.provider == req.provider)
    result = await db.execute(stmt)
    health = result.scalars().first()
    if not health:
        health = ProviderHealth(
            provider=req.provider,
            status="down",
            last_error=f"Simulated failure: {req.error_mode}",
        )
        db.add(health)
    else:
        health.status = "down"
        health.last_error = f"Simulated failure: {req.error_mode}"
    await db.commit()

    return {"message": f"Provider {req.provider} forced to error mode {req.error_mode}"}
