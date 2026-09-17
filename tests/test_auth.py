import pytest


@pytest.mark.asyncio
async def test_login_success(client):
    resp = await client.post("/auth/login", data={
        "username": "admin",
        "password": "testpass",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "session" in resp.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post("/auth/login", data={
        "username": "admin",
        "password": "wrong",
    })
    assert resp.status_code == 200  # re-renders login page
    assert "session" not in resp.cookies


@pytest.mark.asyncio
async def test_protected_route_redirects(client):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


@pytest.mark.asyncio
async def test_logout(auth_client):
    resp = await auth_client.post("/auth/logout", follow_redirects=False)
    assert resp.status_code == 303
