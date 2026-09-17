from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from src.gitlab_client import GitLabClient
from src.pipeline.artifacts import read_artifact


async def _run(cmd: list[str], cwd: Path | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Command {cmd} failed: {stderr.decode()}")
    return stdout.decode()


def _inject_token_into_url(http_url: str, token: str) -> str:
    """Convert https://gitlab.com/group/repo.git to https://oauth2:TOKEN@gitlab.com/group/repo.git"""
    return re.sub(r'^https://', f'https://oauth2:{token}@', http_url)


async def clone_and_branch(
    repo_url: str,
    base_branch: str,
    branch: str,
    repos_dir: Path,
    task_id: int,
    gitlab_token: str | None = None,
) -> Path:
    """Clone a repo and create a work branch.

    If gitlab_token is provided and repo_url is HTTPS, injects the token
    for authentication. Otherwise uses SSH (requires mounted keys).
    """
    clone_url = repo_url
    if gitlab_token and repo_url.startswith("https://"):
        clone_url = _inject_token_into_url(repo_url, gitlab_token)

    repo_dir = repos_dir / str(task_id)
    await _run(["git", "clone", clone_url, str(repo_dir)])
    await _run(["git", "checkout", base_branch], cwd=repo_dir)
    await _run(["git", "checkout", "-b", branch], cwd=repo_dir)
    return repo_dir


async def git_push(repo_dir: Path, branch: str) -> None:
    await _run(["git", "push", "origin", branch], cwd=repo_dir)


async def get_diff(repo_dir: Path, base_branch: str) -> str:
    return await _run(["git", "diff", base_branch, "HEAD"], cwd=repo_dir)


async def cleanup_repo(repo_dir: Path) -> None:
    if repo_dir.exists():
        await asyncio.to_thread(shutil.rmtree, repo_dir)


# ── GitLab MR operations ──


async def create_merge_request(
    gitlab: GitLabClient,
    gitlab_project_id: int,
    source_branch: str,
    target_branch: str,
    title: str,
    repo_dir: Path | None = None,
) -> dict:
    """Create a GitLab MR. Uses pr-summary.md as description if available."""
    description = ""
    if repo_dir:
        summary = read_artifact(repo_dir, "pr-summary.md")
        if summary:
            description = summary

    mr = await gitlab.create_merge_request(
        project_id=gitlab_project_id,
        source_branch=source_branch,
        target_branch=target_branch,
        title=title,
        description=description,
    )
    return mr


async def auto_merge_mr(
    gitlab: GitLabClient, gitlab_project_id: int, mr_iid: int,
) -> dict:
    """Merge an MR immediately."""
    return await gitlab.merge_merge_request(gitlab_project_id, mr_iid)


async def close_mr(
    gitlab: GitLabClient, gitlab_project_id: int, mr_iid: int,
) -> dict:
    """Close an MR without merging (on rejection)."""
    return await gitlab.close_merge_request(gitlab_project_id, mr_iid)
