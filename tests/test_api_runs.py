import pytest


async def _create_test_repo(app):
    """Helper: create a repo in DB for testing."""
    db = app.state.db
    return await db.create_repo(
        gitlab_project_id=999, name="test-repo", full_path="g/test-repo",
        clone_url_ssh="git@gitlab.com:g/test-repo.git",
        clone_url_http="https://gitlab.com/g/test-repo.git",
    )


@pytest.mark.asyncio
async def test_dashboard(auth_client):
    resp = await auth_client.get("/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_new_run_page(auth_client):
    resp = await auth_client.get("/runs/new")
    assert resp.status_code == 200
    assert "New Pipeline Run" in resp.text


@pytest.mark.asyncio
async def test_create_run(auth_client, app):
    repo_id = await _create_test_repo(app)

    resp = await auth_client.post("/runs", data={
        "title": "Test Run",
        "description": "Build something",
        "repo_id": str(repo_id),
        "base_branch": "main",
        "work_type": "bugfix",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "/runs/" in resp.headers["location"]

    # Verify orchestrator_action was set
    db = app.state.db
    runs = await db.list_runs()
    assert len(runs) == 1
    assert runs[0]["work_type"] == "bugfix"


@pytest.mark.asyncio
async def test_create_run_invalid_work_type(auth_client, app):
    repo_id = await _create_test_repo(app)

    resp = await auth_client.post("/runs", data={
        "title": "Bad", "description": "D",
        "repo_id": str(repo_id), "base_branch": "main",
        "work_type": "invalid_type",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]


@pytest.mark.asyncio
async def test_run_detail(auth_client, app):
    repo_id = await _create_test_repo(app)

    await auth_client.post("/runs", data={
        "title": "Detail Run", "description": "Desc",
        "repo_id": str(repo_id), "base_branch": "main",
        "work_type": "feature",
    }, follow_redirects=False)

    resp = await auth_client.get("/runs/1")
    assert resp.status_code == 200
    assert "Detail Run" in resp.text


@pytest.mark.asyncio
async def test_run_detail_not_found(auth_client):
    resp = await auth_client.get("/runs/9999", follow_redirects=False)
    assert resp.status_code == 303


@pytest.mark.asyncio
async def test_run_status_check(auth_client, app):
    repo_id = await _create_test_repo(app)
    await auth_client.post("/runs", data={
        "title": "T", "description": "D",
        "repo_id": str(repo_id), "base_branch": "main",
        "work_type": "bugfix",
    }, follow_redirects=False)

    resp = await auth_client.get("/runs/1/status-check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert "steps" in data


@pytest.mark.asyncio
async def test_delete_run(auth_client, app):
    repo_id = await _create_test_repo(app)

    await auth_client.post("/runs", data={
        "title": "T", "description": "D",
        "repo_id": str(repo_id), "base_branch": "main",
        "work_type": "bugfix",
    }, follow_redirects=False)

    resp = await auth_client.request("DELETE", "/runs/1", follow_redirects=False)
    assert resp.status_code == 303
