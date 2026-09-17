from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    secret_key: str = field(default_factory=lambda: os.environ["SECRET_KEY"])
    admin_username: str = field(default_factory=lambda: os.environ.get("ADMIN_USERNAME", "admin"))
    admin_password: str = field(default_factory=lambda: os.environ.get("ADMIN_PASSWORD", "admin"))
    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("PORT", "8000")))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "/app/data")))
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "postgresql://factory:factory@localhost:5432/factory"
        )
    )
    gitlab_url: str = field(default_factory=lambda: os.environ.get("GITLAB_URL", "https://gitlab.com"))
    gitlab_token: str = field(default_factory=lambda: os.environ.get("GITLAB_TOKEN", ""))
    minio_endpoint: str = field(default_factory=lambda: os.environ.get("MINIO_ENDPOINT", "minio:9000"))
    minio_access_key: str = field(default_factory=lambda: os.environ.get("MINIO_ACCESS_KEY", "factory"))
    minio_secret_key: str = field(default_factory=lambda: os.environ.get("MINIO_SECRET_KEY", "factoryminio"))

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"


def load_agents_config(path: Path | None = None) -> dict:
    if path is None:
        path = Path("agents.yaml")
    with open(path) as f:
        return yaml.safe_load(f)
