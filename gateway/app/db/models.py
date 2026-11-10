import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator


class Base(DeclarativeBase):
    pass


class CompatibleJSON(TypeDecorator[Any]):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class CompatibleArray(TypeDecorator[list[str]]):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Text))
        return dialect.type_descriptor(JSON())


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    monthly_budget_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), default=Decimal("10.0000"), nullable=False
    )
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    redaction_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    requests: Mapped[list["RequestRecord"]] = relationship(
        "RequestRecord", back_populates="api_key", cascade="all, delete-orphan"
    )


class RequestRecord(Base):
    __tablename__ = "requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    provider_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    streamed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    error_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    gateway_overhead_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    pii_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pii_types: Mapped[list[str]] = mapped_column(CompatibleArray, default=list, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    api_key: Mapped["APIKey"] = relationship("APIKey", back_populates="requests")

    __table_args__ = (Index("requests_key_created", "key_id", created_at.desc()),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger, "postgresql"),
        primary_key=True,
        autoincrement=True,
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(CompatibleJSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(CompatibleJSON, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderHealth(Base):
    __tablename__ = "provider_health"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # ok | degraded | down
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
