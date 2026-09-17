import pytest


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_get_settings(auth_client):
    resp = await auth_client.get("/settings")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_update_settings(auth_client):
    resp = await auth_client.put("/settings", json={
        "max_iterations": "5",
    })
    assert resp.status_code == 200
