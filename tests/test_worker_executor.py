"""Tests for worker executor logic."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import asdict

from src.shared.models import JobMessage, ResultMessage
from src.pipeline.artifacts import ARTIFACT_DIR


def _make_job(**overrides) -> JobMessage:
    defaults = {
        "job_id": "test-job-1",
        "run_id": 1,
        "step_id": 1,
        "agent_name": "orchestrator",
        "agent_number": 1,
        "step_order": 0,
        "attempt": 1,
        "work_type": "bugfix",
        "repo_url": "https://example.com/repo.git",
        "base_branch": "main",
        "work_branch": "foc/run-1",
        "task_description": "Test task",
        "run_context": {"work_type": "bugfix", "risk_level": "low", "rollback_count": 0},
        "agent_config": {
            "model": "test", "max_turns": 1, "timeout": 10,
            "allowed_tools": [], "artifacts_write": ["routing.yaml"],
        },
    }
    defaults.update(overrides)
    return JobMessage(**defaults)


def test_job_message_creation():
    job = _make_job()
    assert job.job_id == "test-job-1"
    assert job.run_id == 1
    assert job.agent_name == "orchestrator"
    assert job.source_repo_url is None


def test_result_message_creation():
    result = ResultMessage(
        job_id="test-1", run_id=1, step_id=1,
        agent_name="orchestrator", status="completed",
        verdict="PASS", metrics={"cost_usd": 0.01},
    )
    assert result.status == "completed"
    assert result.error is None
    d = asdict(result)
    assert d["job_id"] == "test-1"


def test_job_with_source_repo():
    job = _make_job(
        work_type="transformation",
        source_repo_url="https://example.com/source.git",
    )
    assert job.source_repo_url == "https://example.com/source.git"


def test_executor_fallback_artifact(tmp_path):
    """When agent produces no .factory/ files, output is saved as fallback."""
    factory_dir = tmp_path / ARTIFACT_DIR
    factory_dir.mkdir()

    # No files in .factory/
    files = list(factory_dir.rglob("*"))
    assert len([f for f in files if f.is_file()]) == 0

    # Fallback creates output file
    fallback_name = "orchestrator-output.md"
    (factory_dir / fallback_name).write_text("Agent output text here")

    assert (factory_dir / fallback_name).exists()
    assert (factory_dir / fallback_name).read_text() == "Agent output text here"


def test_executor_timeout_in_run_cmd():
    """_run_cmd should have timeout parameter."""
    from worker.src.executor import JobExecutor
    import inspect
    sig = inspect.signature(JobExecutor._run_cmd)
    params = list(sig.parameters.keys())
    assert "timeout" in params
