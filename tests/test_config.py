import os
import pytest
from pathlib import Path


def test_config_loads_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "mysecret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "pass123")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")

    from src.config import Config
    cfg = Config()

    assert cfg.secret_key == "mysecret"
    assert cfg.admin_username == "admin"
    assert cfg.admin_password == "pass123"
    assert cfg.data_dir == tmp_path
    assert cfg.database_url == "postgresql://test:test@localhost/test"
    assert cfg.gitlab_url == "https://gitlab.example.com"
    assert cfg.gitlab_token == "glpat-test"


def test_config_loads_agents_yaml(tmp_path):
    agents_file = tmp_path / "agents.yaml"
    agents_file.write_text("""
architect:
  model: claude-sonnet-4-6
  max_turns: 10
  timeout: 600
  system_prompt_file: prompts/architect.md
  allowed_tools:
    - Read
    - Glob
pipeline:
  max_iterations: 3
  max_concurrent_tasks: 2
""")
    from src.config import load_agents_config
    config = load_agents_config(agents_file)

    assert config["architect"]["model"] == "claude-sonnet-4-6"
    assert config["architect"]["max_turns"] == 10
    assert config["pipeline"]["max_iterations"] == 3
