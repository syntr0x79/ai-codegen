import pytest


@pytest.mark.asyncio
async def test_create_user(db):
    user_id = await db.create_user("testuser", "hashedpass")
    assert user_id is not None
    user = await db.get_user_by_username("testuser")
    assert user["username"] == "testuser"
    assert user["password_hash"] == "hashedpass"


@pytest.mark.asyncio
async def test_create_repo(db):
    repo_id = await db.create_repo(
        gitlab_project_id=123, name="my-repo", full_path="group/my-repo",
        clone_url_ssh="git@gitlab.com:group/my-repo.git",
        clone_url_http="https://gitlab.com/group/my-repo.git",
        default_branch="main",
    )
    assert repo_id is not None
    repo = await db.get_repo(repo_id)
    assert repo["name"] == "my-repo"
    assert repo["gitlab_project_id"] == 123


@pytest.mark.asyncio
async def test_create_run(db):
    user_id = await db.create_user("admin", "hash")
    repo_id = await db.create_repo(
        gitlab_project_id=1, name="repo", full_path="g/repo",
        clone_url_ssh="ssh://url", clone_url_http="https://url",
    )
    run_id = await db.create_run(
        title="Test run", description="Do something",
        repo_id=repo_id, base_branch="main",
        work_type="feature", route="1,2,3,4,5,6,7,8",
        created_by=user_id,
    )
    assert run_id is not None
    run = await db.get_run(run_id)
    assert run["title"] == "Test run"
    assert run["status"] == "pending"
    assert run["work_branch"] == f"foc/run-{run_id}"
    assert run["work_type"] == "feature"


@pytest.mark.asyncio
async def test_update_run(db):
    user_id = await db.create_user("admin", "hash")
    repo_id = await db.create_repo(
        gitlab_project_id=1, name="repo", full_path="g/repo",
        clone_url_ssh="ssh://url", clone_url_http="https://url",
    )
    run_id = await db.create_run(
        title="T", description="D", repo_id=repo_id,
        base_branch="main", work_type="bugfix", route="1,2,4,5,6,8",
        created_by=user_id,
    )
    await db.update_run(run_id, status="running", current_step_idx=1)
    run = await db.get_run(run_id)
    assert run["status"] == "running"
    assert run["current_step_idx"] == 1


@pytest.mark.asyncio
async def test_list_runs(db):
    user_id = await db.create_user("admin", "hash")
    repo_id = await db.create_repo(
        gitlab_project_id=1, name="repo", full_path="g/repo",
        clone_url_ssh="ssh://url", clone_url_http="https://url",
    )
    await db.create_run(title="R1", description="D", repo_id=repo_id,
                        base_branch="main", work_type="feature", route="1,2,3,4,5,6,7,8",
                        created_by=user_id)
    await db.create_run(title="R2", description="D", repo_id=repo_id,
                        base_branch="main", work_type="bugfix", route="1,2,4,5,6,8",
                        created_by=user_id)
    runs = await db.list_runs()
    assert len(runs) == 2


@pytest.mark.asyncio
async def test_pipeline_steps(db):
    user_id = await db.create_user("admin", "hash")
    repo_id = await db.create_repo(
        gitlab_project_id=1, name="repo", full_path="g/repo",
        clone_url_ssh="ssh://url", clone_url_http="https://url",
    )
    run_id = await db.create_run(
        title="T", description="D", repo_id=repo_id,
        base_branch="main", work_type="feature", route="1,2,3,4,5,6,7,8",
        created_by=user_id,
    )
    step_id = await db.create_step(run_id, "orchestrator", agent_number=1, step_order=0)
    await db.update_step(step_id, status="completed", output_summary="Route selected",
                         verdict="feature")
    steps = await db.get_steps(run_id)
    assert len(steps) == 1
    assert steps[0]["agent_name"] == "orchestrator"
    assert steps[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_checkpoints(db):
    user_id = await db.create_user("admin", "hash")
    repo_id = await db.create_repo(
        gitlab_project_id=1, name="repo", full_path="g/repo",
        clone_url_ssh="ssh://url", clone_url_http="https://url",
    )
    run_id = await db.create_run(
        title="T", description="D", repo_id=repo_id,
        base_branch="main", work_type="feature", route="1,2,3,4,5,6,7,8",
        created_by=user_id,
    )
    step_id = await db.create_step(run_id, "spec_builder", agent_number=2, step_order=1)
    cp_id = await db.create_checkpoint(run_id, step_id, "spec_builder", "Large feature")

    cp = await db.get_checkpoint(cp_id)
    assert cp["status"] == "pending"

    await db.approve_checkpoint(cp_id, reviewed_by=user_id, comment="Looks good")
    cp = await db.get_checkpoint(cp_id)
    assert cp["status"] == "approved"
    assert cp["reviewer_comment"] == "Looks good"


@pytest.mark.asyncio
async def test_artifacts(db):
    user_id = await db.create_user("admin", "hash")
    repo_id = await db.create_repo(
        gitlab_project_id=1, name="repo", full_path="g/repo",
        clone_url_ssh="ssh://url", clone_url_http="https://url",
    )
    run_id = await db.create_run(
        title="T", description="D", repo_id=repo_id,
        base_branch="main", work_type="feature", route="1,2,3,4,5,6,7,8",
        created_by=user_id,
    )
    step_id = await db.create_step(run_id, "spec_builder", agent_number=2, step_order=1)
    art_id = await db.create_artifact(
        run_id, step_id, "spec_builder", "spec.md", ".factory/spec.md",
        git_commit_sha="abc123",
    )
    arts = await db.get_artifacts(run_id)
    assert len(arts) == 1
    assert arts[0]["filename"] == "spec.md"
    assert arts[0]["git_commit_sha"] == "abc123"


@pytest.mark.asyncio
async def test_step_logs(db):
    user_id = await db.create_user("admin", "hash")
    repo_id = await db.create_repo(
        gitlab_project_id=1, name="repo", full_path="g/repo",
        clone_url_ssh="ssh://url", clone_url_http="https://url",
    )
    run_id = await db.create_run(
        title="T", description="D", repo_id=repo_id,
        base_branch="main", work_type="feature", route="1,2,3,4,5,6,7,8",
        created_by=user_id,
    )
    step_id = await db.create_step(run_id, "orchestrator", agent_number=1, step_order=0)
    await db.append_step_log(step_id, "line 1\n")
    await db.append_step_log(step_id, "line 2\n")
    full = await db.get_run_logs(run_id)
    assert full == "line 1\nline 2\n"


@pytest.mark.asyncio
async def test_settings(db):
    await db.set_setting("max_iterations", "5")
    val = await db.get_setting("max_iterations")
    assert val == "5"

    await db.set_setting("max_iterations", "3")
    val = await db.get_setting("max_iterations")
    assert val == "3"

    all_settings = await db.get_all_settings()
    assert all_settings["max_iterations"] == "3"
