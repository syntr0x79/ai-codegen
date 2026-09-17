import pytest
from pathlib import Path

from src.pipeline.artifacts import (
    artifact_path, read_artifact, list_artifacts,
    ensure_artifact_dir, ARTIFACT_DIR,
)


def test_artifact_path(tmp_path):
    p = artifact_path(tmp_path, "spec.md")
    assert p == tmp_path / ".factory" / "spec.md"


def test_read_artifact_exists(tmp_path):
    factory = tmp_path / ARTIFACT_DIR
    factory.mkdir()
    (factory / "spec.md").write_text("# Spec\nTest content")

    content = read_artifact(tmp_path, "spec.md")
    assert content == "# Spec\nTest content"


def test_read_artifact_missing(tmp_path):
    content = read_artifact(tmp_path, "nonexistent.md")
    assert content is None


def test_list_artifacts_empty(tmp_path):
    assert list_artifacts(tmp_path) == []


def test_list_artifacts(tmp_path):
    factory = tmp_path / ARTIFACT_DIR
    factory.mkdir()
    (factory / "spec.md").write_text("spec")
    (factory / "routing.yaml").write_text("routing")
    contracts = factory / "contracts"
    contracts.mkdir()
    (contracts / "api.md").write_text("contract")

    result = list_artifacts(tmp_path)
    assert "spec.md" in result
    assert "routing.yaml" in result
    assert "contracts/api.md" in result


def test_ensure_artifact_dir(tmp_path):
    factory = ensure_artifact_dir(tmp_path)
    assert factory.exists()
    assert factory == tmp_path / ARTIFACT_DIR
    # Idempotent
    ensure_artifact_dir(tmp_path)
    assert factory.exists()
