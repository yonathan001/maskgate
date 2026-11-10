from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProviderHealth
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    providers_status: dict[str, Any] = {}
    try:
        stmt = select(ProviderHealth)
        result = await db.execute(stmt)
        records = result.scalars().all()
        for r in records:
            providers_status[r.provider] = {
                "status": r.status,
                "last_error": r.last_error,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
    except Exception:
        # DB might be initializing or unreachable
        providers_status["db"] = {"status": "degraded"}

    return {
        "status": "ok",
        "gateway": "healthy",
        "providers": providers_status,
    }
