import asyncio
from collections.abc import AsyncGenerator
from decimal import Decimal
import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.auth import generate_api_key
from app.db.models import APIKey, Base
from app.db.session import get_db
from app.main import create_app
from app.providers.registry import get_model_registry

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def app_instance(test_engine):
    app = create_app()

    maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app_instance) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app_instance),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def created_api_key(db_session: AsyncSession) -> tuple[str, APIKey]:
    raw_key, prefix, key_hash = generate_api_key()
    api_key = APIKey(
        name="test-key",
        key_prefix=prefix,
        key_hash=key_hash,
        monthly_budget_usd=Decimal("50.0000"),
        rate_limit_per_min=100,
        redaction_enabled=True,
        active=True,
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return raw_key, api_key
