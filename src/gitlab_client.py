from __future__ import annotations

import httpx


class GitLabError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"GitLab API error {status_code}: {detail}")


class GitLabClient:
    """Async wrapper around GitLab REST API v4."""

    def __init__(self, url: str, token: str, timeout: float = 30.0):
        self.base_url = url.rstrip("/")
        self.api_url = f"{self.base_url}/api/v4"
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict:
        return {"PRIVATE-TOKEN": self.token}

    async def _request(
        self, method: str, path: str, **kwargs
    ) -> dict | list:
        url = f"{self.api_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(
                method, url, headers=self._headers(), **kwargs
            )
        if resp.status_code >= 400:
            raise GitLabError(resp.status_code, resp.text)
        if resp.status_code == 204:
            return {}
        return resp.json()

    # ── Projects ──

    async def list_projects(
        self, search: str = "", page: int = 1, per_page: int = 20,
        membership: bool = True,
    ) -> list[dict]:
        params = {
            "page": page,
            "per_page": per_page,
            "membership": str(membership).lower(),
            "order_by": "name",
            "sort": "asc",
        }
        if search:
            params["search"] = search
        projects = await self._request("GET", "/projects", params=params)
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "full_path": p["path_with_namespace"],
                "clone_url_ssh": p["ssh_url_to_repo"],
                "clone_url_http": p["http_url_to_repo"],
                "default_branch": p.get("default_branch", "main"),
                "description": p.get("description", ""),
                "web_url": p.get("web_url", ""),
            }
            for p in projects
        ]

    async def get_project(self, project_id: int) -> dict:
        p = await self._request("GET", f"/projects/{project_id}")
        return {
            "id": p["id"],
            "name": p["name"],
            "full_path": p["path_with_namespace"],
            "clone_url_ssh": p["ssh_url_to_repo"],
            "clone_url_http": p["http_url_to_repo"],
            "default_branch": p.get("default_branch", "main"),
            "description": p.get("description", ""),
            "web_url": p.get("web_url", ""),
        }

    # ── Branches ──

    async def list_branches(
        self, project_id: int, search: str = "", per_page: int = 100,
    ) -> list[dict]:
        params = {"per_page": per_page}
        if search:
            params["search"] = search
        branches = await self._request(
            "GET", f"/projects/{project_id}/repository/branches", params=params
        )
        return [
            {
                "name": b["name"],
                "default": b.get("default", False),
                "merged": b.get("merged", False),
                "protected": b.get("protected", False),
                "commit_sha": b.get("commit", {}).get("id", ""),
                "commit_message": b.get("commit", {}).get("message", ""),
            }
            for b in branches
        ]

    # ── Merge Requests ──

    async def create_merge_request(
        self, project_id: int, source_branch: str, target_branch: str,
        title: str, description: str = "",
    ) -> dict:
        data = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "remove_source_branch": True,
        }
        mr = await self._request(
            "POST", f"/projects/{project_id}/merge_requests", json=data
        )
        return {
            "iid": mr["iid"],
            "url": mr["web_url"],
            "state": mr["state"],
        }

    async def get_merge_request(self, project_id: int, mr_iid: int) -> dict:
        mr = await self._request(
            "GET", f"/projects/{project_id}/merge_requests/{mr_iid}"
        )
        return {
            "iid": mr["iid"],
            "url": mr["web_url"],
            "state": mr["state"],
            "merged_by": mr.get("merged_by"),
            "merge_status": mr.get("merge_status"),
        }

    async def merge_merge_request(self, project_id: int, mr_iid: int) -> dict:
        mr = await self._request(
            "PUT", f"/projects/{project_id}/merge_requests/{mr_iid}/merge"
        )
        return {
            "iid": mr["iid"],
            "state": mr["state"],
        }

    async def close_merge_request(self, project_id: int, mr_iid: int) -> dict:
        mr = await self._request(
            "PUT", f"/projects/{project_id}/merge_requests/{mr_iid}",
            json={"state_event": "close"},
        )
        return {
            "iid": mr["iid"],
            "state": mr["state"],
        }

    # ── Connection Test ──

    async def test_connection(self) -> dict:
        """Test the connection by fetching the current user."""
        user = await self._request("GET", "/user")
        return {
            "username": user["username"],
            "name": user.get("name", ""),
            "id": user["id"],
        }
