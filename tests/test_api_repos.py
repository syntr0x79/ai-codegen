import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_repos_page(auth_client):
    resp = await auth_client.get("/repos")
    assert resp.status_code == 200
    assert "Repositories" in resp.text


@pytest.mark.asyncio
async def test_connect_repo(auth_client, app):
    """Test connecting a GitLab repo."""
    mock_project = {
        "id": 123, "name": "test-repo", "full_path": "group/test-repo",
        "clone_url_ssh": "git@gitlab.com:group/test-repo.git",
        "clone_url_http": "https://gitlab.com/group/test-repo.git",
        "default_branch": "main", "description": "", "web_url": "",
    }

    mock_gitlab = AsyncMock()
    mock_gitlab.get_project = AsyncMock(return_value=mock_project)
    app.state.gitlab = mock_gitlab

    resp = await auth_client.post("/repos/connect", data={
        "gitlab_project_id": "123",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "/repos/" in resp.headers["location"]

    # Verify repo appears in list
    resp = await auth_client.get("/repos")
    assert "test-repo" in resp.text


@pytest.mark.asyncio
async def test_connect_duplicate_repo(auth_client, app):
    """Connecting same repo twice should redirect to existing."""
    mock_project = {
        "id": 456, "name": "dup-repo", "full_path": "group/dup-repo",
        "clone_url_ssh": "git@gitlab.com:group/dup-repo.git",
        "clone_url_http": "https://gitlab.com/group/dup-repo.git",
        "default_branch": "main", "description": "", "web_url": "",
    }

    mock_gitlab = AsyncMock()
    mock_gitlab.get_project = AsyncMock(return_value=mock_project)
    app.state.gitlab = mock_gitlab

    # Connect first time
    await auth_client.post("/repos/connect", data={
        "gitlab_project_id": "456",
    }, follow_redirects=False)

    # Connect same project again
    resp = await auth_client.post("/repos/connect", data={
        "gitlab_project_id": "456",
    }, follow_redirects=False)
    assert resp.status_code == 303


@pytest.mark.asyncio
async def test_repo_detail(auth_client, app):
    mock_project = {
        "id": 789, "name": "detail-repo", "full_path": "g/detail-repo",
        "clone_url_ssh": "ssh://url", "clone_url_http": "https://url",
        "default_branch": "main", "description": "", "web_url": "",
    }
    mock_branches = [
        {"name": "main", "default": True, "merged": False, "protected": True,
         "commit_sha": "abc", "commit_message": "init"},
    ]

    mock_gitlab = AsyncMock()
    mock_gitlab.get_project = AsyncMock(return_value=mock_project)
    mock_gitlab.list_branches = AsyncMock(return_value=mock_branches)
    app.state.gitlab = mock_gitlab

    # Connect repo first
    await auth_client.post("/repos/connect", data={
        "gitlab_project_id": "789",
    }, follow_redirects=False)

    # View detail
    resp = await auth_client.get("/repos/1")
    assert resp.status_code == 200
    assert "detail-repo" in resp.text


@pytest.mark.asyncio
async def test_disconnect_repo(auth_client, app):
    mock_project = {
        "id": 101, "name": "del-repo", "full_path": "g/del-repo",
        "clone_url_ssh": "ssh://url", "clone_url_http": "https://url",
        "default_branch": "main", "description": "", "web_url": "",
    }

    mock_gitlab = AsyncMock()
    mock_gitlab.get_project = AsyncMock(return_value=mock_project)
    app.state.gitlab = mock_gitlab

    await auth_client.post("/repos/connect", data={
        "gitlab_project_id": "101",
    }, follow_redirects=False)

    resp = await auth_client.request("DELETE", "/repos/1", follow_redirects=False)
    assert resp.status_code == 303


@pytest.mark.asyncio
async def test_no_gitlab_configured(auth_client, app):
    """Without GitLab client, connect should fail gracefully."""
    app.state.gitlab = None
    resp = await auth_client.post("/repos/connect", data={
        "gitlab_project_id": "1",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]
