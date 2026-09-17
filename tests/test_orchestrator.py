"""Tests for the orchestrator service logic."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.pipeline.routes import get_route, route_to_string, AGENT_ARTIFACTS


async def _setup_run(db, work_type="bugfix"):
    user_id = await db.create_user("admin", "hash")
    repo_id = await db.create_repo(
        gitlab_project_id=1, name="repo", full_path="g/repo",
        clone_url_ssh="git@gitlab.com:g/repo.git",
        clone_url_http="https://gitlab.com/g/repo.git",
    )
    route = get_route(work_type)
    run_id = await db.create_run(
        title="Test", description="Test run",
        repo_id=repo_id, base_branch="main",
        work_type=work_type, route=route_to_string(route),
        created_by=user_id,
    )
    return run_id, repo_id


@pytest.mark.asyncio
async def test_orchestrator_action_start(db):
    """Web creates run with orchestrator_action='start'."""
    run_id, _ = await _setup_run(db)
    await db.update_run(run_id, orchestrator_action="start")

    runs = await db.get_runs_with_action()
    assert len(runs) == 1
    assert runs[0]["orchestrator_action"] == "start"

    await db.clear_orchestrator_action(run_id)
    runs = await db.get_runs_with_action()
    assert len(runs) == 0


@pytest.mark.asyncio
async def test_orchestrator_action_resume(db):
    """Checkpoint approval sets orchestrator_action='resume'."""
    run_id, _ = await _setup_run(db)

    # Create a step and checkpoint
    step_id = await db.create_step(run_id, "orchestrator", agent_number=1, step_order=0)
    cp_id = await db.create_checkpoint(run_id, step_id, "orchestrator", "Test checkpoint")

    # Simulate approval
    user_id = (await db.get_user_by_username("admin"))["id"]
    await db.approve_checkpoint(cp_id, reviewed_by=user_id)
    await db.update_run(run_id, orchestrator_action="resume")

    runs = await db.get_runs_with_action()
    assert len(runs) == 1
    assert runs[0]["orchestrator_action"] == "resume"


@pytest.mark.asyncio
async def test_orchestrator_action_cancel(db):
    """Cancel sets status and orchestrator_action."""
    run_id, _ = await _setup_run(db)
    await db.update_run(run_id, status="cancelled", orchestrator_action="cancel")

    run = await db.get_run(run_id)
    assert run["status"] == "cancelled"


@pytest.mark.asyncio
async def test_checkpoint_summary_fallback(db):
    """Checkpoint summary falls back when artifact not in MinIO."""
    from orchestrator.src.main import _build_checkpoint_summary

    mock_minio = MagicMock()
    mock_minio.download_text.return_value = None

    summary = _build_checkpoint_summary(mock_minio, 999, "spec_builder")
    assert "завершён" in summary


@pytest.mark.asyncio
async def test_checkpoint_summary_from_minio(db):
    """Checkpoint summary extracts headers from MinIO artifact."""
    from orchestrator.src.main import _build_checkpoint_summary

    mock_minio = MagicMock()
    mock_minio.download_text.return_value = "# Spec\n\n## Overview\n\n- Item 1\n- Item 2\n\nSome text"

    summary = _build_checkpoint_summary(mock_minio, 1, "spec_builder")
    assert "# Spec" in summary
    assert "- Item 1" in summary


@pytest.mark.asyncio
async def test_run_lifecycle_in_db(db):
    """Test full run state transitions in DB."""
    run_id, _ = await _setup_run(db, "feature")

    # Start
    await db.update_run(run_id, status="running", current_step_idx=0)
    run = await db.get_run(run_id)
    assert run["status"] == "running"

    # Step completion
    step_id = await db.create_step(run_id, "orchestrator", agent_number=1, step_order=0)
    await db.update_step(step_id, status="completed", verdict="feature")
    step = await db.get_step(step_id)
    assert step["status"] == "completed"

    # Advance
    await db.update_run(run_id, current_step_idx=1)

    # Checkpoint
    cp_id = await db.create_checkpoint(run_id, step_id, "orchestrator", "Review needed")
    await db.update_run(run_id, status="awaiting_checkpoint")
    run = await db.get_run(run_id)
    assert run["status"] == "awaiting_checkpoint"

    # Approve
    user_id = (await db.get_user_by_username("admin"))["id"]
    await db.approve_checkpoint(cp_id, reviewed_by=user_id)
    await db.update_run(run_id, status="running")

    # Complete
    await db.update_run(run_id, status="completed", final_verdict="PASS")
    run = await db.get_run(run_id)
    assert run["status"] == "completed"
    assert run["final_verdict"] == "PASS"


@pytest.mark.asyncio
async def test_rollback_state(db):
    """Test rollback increments counter and resets step index."""
    run_id, _ = await _setup_run(db, "bugfix")
    await db.update_run(run_id, status="running", current_step_idx=3)

    # Rollback
    await db.update_run(run_id, current_step_idx=2, rollback_count=1)
    run = await db.get_run(run_id)
    assert run["current_step_idx"] == 2
    assert run["rollback_count"] == 1


@pytest.mark.asyncio
async def test_heartbeat_write_and_read(db):
    """Test worker heartbeat DB operations."""
    run_id, _ = await _setup_run(db)
    step_id = await db.create_step(run_id, "orchestrator", agent_number=1, step_order=0)

    # Write heartbeat
    await db._pool.execute(
        "INSERT INTO worker_heartbeats (step_id, worker_id) VALUES ($1, $2)",
        step_id, "worker-test-1",
    )

    # Read
    row = await db._pool.fetchrow(
        "SELECT * FROM worker_heartbeats WHERE step_id = $1", step_id
    )
    assert row["worker_id"] == "worker-test-1"
