"""Message models for RabbitMQ job/result protocol."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class JobMessage:
    job_id: str
    run_id: int
    step_id: int
    agent_name: str
    agent_number: int
    step_order: int
    attempt: int
    work_type: str
    repo_url: str
    base_branch: str
    work_branch: str
    task_description: str
    run_context: dict
    agent_config: dict
    minio_bucket: str = "factory-artifacts"
    minio_prefix: str = ""
    source_repo_url: str | None = None
    artifact_inputs: list[str] = field(default_factory=list)
    is_final_step: bool = False


@dataclass
class ResultMessage:
    job_id: str
    run_id: int
    step_id: int
    agent_name: str
    status: str  # "completed" | "failed"
    verdict: str | None = None
    output_summary: str = ""
    metrics: dict = field(default_factory=dict)
    duration_seconds: float = 0.0
    commit_sha: str | None = None
    artifacts_uploaded: list[str] = field(default_factory=list)
    error: str | None = None
