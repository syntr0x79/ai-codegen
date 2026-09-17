import pytest


@pytest.mark.asyncio
async def test_presets_page(auth_client):
    resp = await auth_client.get("/presets")
    assert resp.status_code == 200
    assert "Agent Presets" in resp.text


@pytest.mark.asyncio
async def test_new_preset_page(auth_client):
    resp = await auth_client.get("/presets/new")
    assert resp.status_code == 200
    assert "New Preset" in resp.text


@pytest.mark.asyncio
async def test_create_preset(auth_client, app):
    resp = await auth_client.post("/presets", json={
        "name": "Python Backend",
        "description": "For Python projects",
        "agent_configs": {
            "implementation": {"model": "claude-opus-4-6", "max_turns": 60},
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] is not None

    # Verify it appears in list
    resp = await auth_client.get("/presets")
    assert "Python Backend" in resp.text


@pytest.mark.asyncio
async def test_edit_preset_page(auth_client, app):
    await auth_client.post("/presets", json={
        "name": "Edit Test",
        "description": "",
        "agent_configs": {},
    })

    resp = await auth_client.get("/presets/1")
    assert resp.status_code == 200
    assert "Edit Test" in resp.text


@pytest.mark.asyncio
async def test_update_preset(auth_client, app):
    await auth_client.post("/presets", json={
        "name": "Update Test",
        "description": "",
        "agent_configs": {},
    })

    resp = await auth_client.put("/presets/1", json={
        "name": "Updated Name",
        "description": "Updated desc",
        "agent_configs": {"orchestrator": {"model": "claude-opus-4-6"}},
    })
    assert resp.status_code == 200

    resp = await auth_client.get("/presets/1")
    assert "Updated Name" in resp.text


@pytest.mark.asyncio
async def test_delete_preset(auth_client, app):
    await auth_client.post("/presets", json={
        "name": "Delete Me",
        "description": "",
        "agent_configs": {},
    })

    resp = await auth_client.request("DELETE", "/presets/1", follow_redirects=False)
    assert resp.status_code == 303


@pytest.mark.asyncio
async def test_clone_preset(auth_client, app):
    await auth_client.post("/presets", json={
        "name": "Original",
        "description": "To be cloned",
        "agent_configs": {"implementation": {"max_turns": 99}},
    })

    resp = await auth_client.post("/presets/1/clone", follow_redirects=False)
    assert resp.status_code == 303

    resp = await auth_client.get("/presets")
    assert "Original (copy)" in resp.text
