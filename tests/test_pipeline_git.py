import pytest
import subprocess
from pathlib import Path


@pytest.fixture
def bare_repo(tmp_path) -> Path:
    """Create a bare git repo to act as remote."""
    repo_dir = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(repo_dir)], check=True, capture_output=True)

    # Create a working copy, add a commit, push
    work_dir = tmp_path / "work"
    subprocess.run(["git", "clone", str(repo_dir), str(work_dir)], check=True, capture_output=True)
    (work_dir / "README.md").write_text("# Test repo")
    subprocess.run(["git", "add", "."], cwd=work_dir, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@test.com",
                     "commit", "-m", "init"], cwd=work_dir, check=True, capture_output=True)
    subprocess.run(["git", "push"], cwd=work_dir, check=True, capture_output=True)
    return repo_dir


@pytest.mark.asyncio
async def test_clone_and_branch(bare_repo, tmp_path):
    from src.pipeline.git import clone_and_branch
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    # Detect the default branch name (main or master)
    result = subprocess.run(
        ["git", "ls-remote", "--symref", str(bare_repo), "HEAD"],
        capture_output=True, text=True,
    )
    base_branch = "main"
    for line in result.stdout.splitlines():
        if line.startswith("ref:"):
            # format: "ref: refs/heads/main\tHEAD"
            ref_part = line.split()[1]  # "refs/heads/main"
            base_branch = ref_part.replace("refs/heads/", "")
            break

    repo_dir = await clone_and_branch(
        repo_url=str(bare_repo),
        base_branch=base_branch,
        branch="ai/task-1",
        repos_dir=repos_dir,
        task_id=1,
    )

    assert repo_dir.exists()
    assert (repo_dir / "README.md").exists()

    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    assert result.stdout.strip() == "ai/task-1"


@pytest.mark.asyncio
async def test_get_diff(bare_repo, tmp_path):
    from src.pipeline.git import clone_and_branch, get_diff
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    # Detect the default branch name (main or master)
    result = subprocess.run(
        ["git", "ls-remote", "--symref", str(bare_repo), "HEAD"],
        capture_output=True, text=True,
    )
    base_branch = "main"
    for line in result.stdout.splitlines():
        if line.startswith("ref:"):
            ref_part = line.split()[1]  # "refs/heads/main"
            base_branch = ref_part.replace("refs/heads/", "")
            break

    repo_dir = await clone_and_branch(
        repo_url=str(bare_repo), base_branch=base_branch,
        branch="ai/task-1", repos_dir=repos_dir, task_id=1,
    )

    (repo_dir / "new_file.py").write_text("print('hello')")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@test.com",
                     "commit", "-m", "add file"], cwd=repo_dir, check=True, capture_output=True)

    diff = await get_diff(repo_dir, base_branch)
    assert "new_file.py" in diff
    assert "print('hello')" in diff


@pytest.mark.asyncio
async def test_cleanup_repo(bare_repo, tmp_path):
    from src.pipeline.git import clone_and_branch, cleanup_repo
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    # Detect the default branch name (main or master)
    result = subprocess.run(
        ["git", "ls-remote", "--symref", str(bare_repo), "HEAD"],
        capture_output=True, text=True,
    )
    base_branch = "main"
    for line in result.stdout.splitlines():
        if line.startswith("ref:"):
            ref_part = line.split()[1]  # "refs/heads/main"
            base_branch = ref_part.replace("refs/heads/", "")
            break

    repo_dir = await clone_and_branch(
        repo_url=str(bare_repo), base_branch=base_branch,
        branch="ai/task-1", repos_dir=repos_dir, task_id=1,
    )
    assert repo_dir.exists()

    await cleanup_repo(repo_dir)
    assert not repo_dir.exists()


@pytest.mark.asyncio
async def test_create_merge_request(tmp_path):
    """Test MR creation with mocked GitLab client."""
    from unittest.mock import AsyncMock
    from src.pipeline.git import create_merge_request
    from src.pipeline.artifacts import ARTIFACT_DIR

    # Create a repo dir with pr-summary.md
    repo_dir = tmp_path / "repo"
    factory = repo_dir / ARTIFACT_DIR
    factory.mkdir(parents=True)
    (factory / "pr-summary.md").write_text("## Summary\n\nFixed the bug.\n")

    mock_gitlab = AsyncMock()
    mock_gitlab.create_merge_request = AsyncMock(return_value={
        "iid": 42,
        "web_url": "https://gitlab.com/g/repo/-/merge_requests/42",
        "state": "opened",
    })

    mr = await create_merge_request(
        gitlab=mock_gitlab,
        gitlab_project_id=123,
        source_branch="foc/run-1",
        target_branch="main",
        title="Fix the bug",
        repo_dir=repo_dir,
    )

    assert mr["iid"] == 42
    # Verify pr-summary.md was used as description
    call_args = mock_gitlab.create_merge_request.call_args
    assert "Fixed the bug" in call_args.kwargs.get("description", call_args[1].get("description", ""))


@pytest.mark.asyncio
async def test_create_merge_request_no_summary(tmp_path):
    """MR creation works even without pr-summary.md."""
    from unittest.mock import AsyncMock
    from src.pipeline.git import create_merge_request

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    mock_gitlab = AsyncMock()
    mock_gitlab.create_merge_request = AsyncMock(return_value={
        "iid": 7, "web_url": "https://gitlab.com/mr/7", "state": "opened",
    })

    mr = await create_merge_request(
        gitlab=mock_gitlab,
        gitlab_project_id=1,
        source_branch="foc/run-2",
        target_branch="main",
        title="Some change",
        repo_dir=repo_dir,
    )

    assert mr["iid"] == 7
