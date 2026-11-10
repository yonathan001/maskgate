import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_admin_unauthorized(client: AsyncClient) -> None:
    resp = await client.post("/admin/keys", json={"name": "test"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_create_and_list_keys(client: AsyncClient) -> None:
    headers = {"X-Admin-Token": "change-me"}

    # Create key
    create_resp = await client.post(
        "/admin/keys",
        headers=headers,
        json={"name": "test-client", "monthly_budget_usd": 25.0, "rate_limit_per_min": 120},
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["name"] == "test-client"
    assert created["key"] is not None
    assert created["key_prefix"] == created["key"][:8]
    assert float(created["monthly_budget_usd"]) == 25.0
    key_id = created["id"]

    # List keys
    list_resp = await client.get("/admin/keys", headers=headers)
    assert list_resp.status_code == 200
    keys = list_resp.json()
    matching = [k for k in keys if k["id"] == key_id]
    assert len(matching) == 1
    assert matching[0]["key"] is None  # Never return raw key in list

    # Update key
    patch_resp = await client.patch(
        f"/admin/keys/{key_id}",
        headers=headers,
        json={"monthly_budget_usd": 30.0, "active": False},
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert float(updated["monthly_budget_usd"]) == 30.0
    assert updated["active"] is False


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["gateway"] == "healthy"
