import json
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from src.gitlab_client import GitLabClient, GitLabError


def _mock_response(data, status_code=200):
    resp = httpx.Response(
        status_code=status_code,
        json=data,
        request=httpx.Request("GET", "http://test"),
    )
    return resp


@pytest.mark.asyncio
async def test_list_projects():
    mock_data = [
        {
            "id": 1, "name": "repo1", "path_with_namespace": "group/repo1",
            "ssh_url_to_repo": "git@gitlab.com:group/repo1.git",
            "http_url_to_repo": "https://gitlab.com/group/repo1.git",
            "default_branch": "main", "description": "Test repo",
            "web_url": "https://gitlab.com/group/repo1",
        }
    ]

    client = GitLabClient("https://gitlab.com", "test-token")
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _mock_response(mock_data)
        projects = await client.list_projects(search="repo1")

    assert len(projects) == 1
    assert projects[0]["name"] == "repo1"
    assert projects[0]["full_path"] == "group/repo1"
    assert projects[0]["clone_url_ssh"] == "git@gitlab.com:group/repo1.git"


@pytest.mark.asyncio
async def test_get_project():
    mock_data = {
        "id": 42, "name": "myrepo", "path_with_namespace": "org/myrepo",
        "ssh_url_to_repo": "git@gitlab.com:org/myrepo.git",
        "http_url_to_repo": "https://gitlab.com/org/myrepo.git",
        "default_branch": "develop", "description": "",
        "web_url": "https://gitlab.com/org/myrepo",
    }

    client = GitLabClient("https://gitlab.com", "test-token")
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _mock_response(mock_data)
        project = await client.get_project(42)

    assert project["id"] == 42
    assert project["default_branch"] == "develop"


@pytest.mark.asyncio
async def test_list_branches():
    mock_data = [
        {
            "name": "main", "default": True, "merged": False,
            "protected": True, "commit": {"id": "abc123", "message": "init"},
        },
        {
            "name": "feature-x", "default": False, "merged": False,
            "protected": False, "commit": {"id": "def456", "message": "wip"},
        },
    ]

    client = GitLabClient("https://gitlab.com", "test-token")
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _mock_response(mock_data)
        branches = await client.list_branches(42)

    assert len(branches) == 2
    assert branches[0]["name"] == "main"
    assert branches[0]["default"] is True
    assert branches[1]["commit_sha"] == "def456"


@pytest.mark.asyncio
async def test_create_merge_request():
    mock_data = {
        "iid": 7, "web_url": "https://gitlab.com/org/repo/-/merge_requests/7",
        "state": "opened",
    }

    client = GitLabClient("https://gitlab.com", "test-token")
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _mock_response(mock_data, 201)
        mr = await client.create_merge_request(
            42, "feature-x", "main", "Add feature X", "Description"
        )

    assert mr["iid"] == 7
    assert mr["state"] == "opened"


@pytest.mark.asyncio
async def test_test_connection():
    mock_data = {"id": 1, "username": "admin", "name": "Admin User"}

    client = GitLabClient("https://gitlab.com", "test-token")
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _mock_response(mock_data)
        user = await client.test_connection()

    assert user["username"] == "admin"


@pytest.mark.asyncio
async def test_error_handling():
    client = GitLabClient("https://gitlab.com", "bad-token")
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _mock_response(
            {"error": "unauthorized"}, status_code=401
        )
        with pytest.raises(GitLabError) as exc_info:
            await client.test_connection()
        assert exc_info.value.status_code == 401
