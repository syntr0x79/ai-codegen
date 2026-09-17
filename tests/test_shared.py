"""Tests for shared modules: credentials, models, minio_client."""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import asdict

from src.shared.models import JobMessage, ResultMessage
from src.shared.credentials import (
    write_claude_credentials, write_ssh_key, write_kubeconfig,
)


def test_job_message_fields():
    job = JobMessage(
        job_id="abc", run_id=1, step_id=2, agent_name="test",
        agent_number=1, step_order=0, attempt=1, work_type="bugfix",
        repo_url="https://url", base_branch="main", work_branch="foc/run-1",
        task_description="desc", run_context={}, agent_config={},
    )
    assert job.minio_bucket == "factory-artifacts"
    assert job.source_repo_url is None
    d = asdict(job)
    assert d["job_id"] == "abc"


def test_result_message_defaults():
    result = ResultMessage(
        job_id="x", run_id=1, step_id=2,
        agent_name="test", status="completed",
    )
    assert result.verdict is None
    assert result.metrics == {}
    assert result.artifacts_uploaded == []
    assert result.error is None


def test_write_claude_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    creds = json.dumps({"claudeAiOauth": {"accessToken": "test-token"}})
    write_claude_credentials(creds)

    creds_file = tmp_path / ".claude" / ".credentials.json"
    assert creds_file.exists()
    assert oct(creds_file.stat().st_mode)[-3:] == "600"

    loaded = json.loads(creds_file.read_text())
    assert loaded["claudeAiOauth"]["accessToken"] == "test-token"

    # .claude.json should also exist
    assert (tmp_path / ".claude.json").exists()


def test_write_ssh_key(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write_ssh_key("private-key-content")

    key_file = tmp_path / ".ssh" / "id_agent"
    assert key_file.exists()
    assert key_file.read_text() == "private-key-content"
    assert oct(key_file.stat().st_mode)[-3:] == "600"


def test_write_kubeconfig(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write_kubeconfig("apiVersion: v1\nkind: Config")

    kube_file = tmp_path / ".kube" / "config"
    assert kube_file.exists()
    assert "apiVersion" in kube_file.read_text()


@pytest.mark.asyncio
async def test_restore_all_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from src.shared.credentials import restore_all_credentials

    settings = {
        "claude_credentials": json.dumps({"claudeAiOauth": {"accessToken": "t"}}),
        "ssh_private_key": "ssh-key-data",
        "kubeconfig": "kube-data",
    }

    async def mock_get(key):
        return settings.get(key)

    await restore_all_credentials(mock_get)

    assert (tmp_path / ".claude" / ".credentials.json").exists()
    assert (tmp_path / ".ssh" / "id_agent").exists()
    assert (tmp_path / ".kube" / "config").exists()


@pytest.mark.asyncio
async def test_restore_credentials_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from src.shared.credentials import restore_all_credentials

    async def mock_get(key):
        return None

    await restore_all_credentials(mock_get)

    # Nothing should be created
    assert not (tmp_path / ".claude" / ".credentials.json").exists()
    assert not (tmp_path / ".ssh" / "id_agent").exists()
    assert not (tmp_path / ".kube" / "config").exists()


def test_minio_client_artifact_key():
    from src.shared.minio_client import MinIOClient
    client = MinIOClient.__new__(MinIOClient)
    client.bucket = "factory-artifacts"
    assert client.artifact_key(123, "spec.md") == "runs/123/artifacts/spec.md"
    assert client.artifact_key(1, "nested/file.md") == "runs/1/artifacts/nested/file.md"
