import json
import pytest
from pathlib import Path

from src.pipeline.agent import build_prompt, parse_verdict, _parse_stream_metrics
from src.pipeline.artifacts import ARTIFACT_DIR


@pytest.fixture
def repo_with_artifacts(tmp_path):
    """Create a fake repo with .factory/ artifacts."""
    factory = tmp_path / ARTIFACT_DIR
    factory.mkdir()
    (factory / "routing.yaml").write_text(
        "work_type: feature\nrisk_level: medium\njustification: test\n"
    )
    (factory / "spec.md").write_text("# Spec\n\nFR-1: Do something\n")
    (factory / "impact-map.md").write_text("# Impact\n\nRISK_LEVEL: high\n")
    (factory / "contract-verdict.json").write_text(
        json.dumps({"overall": "PASS", "tests_passed": 5, "tests_failed": 0, "tests_total": 5})
    )
    (factory / "verdict.json").write_text(
        json.dumps({"verdict": "PASS", "summary": "All good"})
    )
    (factory / "policy-verdict.json").write_text(
        json.dumps({"verdict": "APPROVED", "findings": []})
    )
    contracts = factory / "contracts"
    contracts.mkdir()
    (contracts / "api.md").write_text("# API Contract\n\nGET /users -> 200\n")
    return tmp_path


# The prompt library is written in Russian — that is the working language of
# the team this was built for, and the headings below are what the builder
# actually emits. These two assertions were left behind by the translation and
# asserted the old English wording.
def test_build_prompt_orchestrator(repo_with_artifacts):
    prompt = build_prompt("orchestrator", repo_with_artifacts, task_description="Add login")
    assert "Add login" in prompt
    assert "## Задача" in prompt


def test_build_prompt_spec_builder(repo_with_artifacts):
    config = {"artifacts_read": ["routing.yaml"]}
    prompt = build_prompt("spec_builder", repo_with_artifacts,
                          task_description="Add login", config=config)
    assert "Add login" in prompt
    assert "routing.yaml" in prompt
    assert "work_type: feature" in prompt


def test_build_prompt_implementation_with_contracts(repo_with_artifacts):
    config = {"artifacts_read": ["spec.md", "impact-map.md"]}
    prompt = build_prompt("implementation", repo_with_artifacts, config=config)
    assert "spec.md" in prompt
    assert "FR-1" in prompt
    assert "API Contract" in prompt  # contracts injected


def test_build_prompt_with_rollback_context(repo_with_artifacts):
    config = {"artifacts_read": ["spec.md"]}
    run_context = {"rollback_count": 2, "work_type": "feature", "risk_level": "high"}
    prompt = build_prompt("implementation", repo_with_artifacts,
                          config=config, run_context=run_context)
    assert "повторная попытка #2" in prompt
    assert "Тип работы: feature" in prompt
    assert "Уровень риска: high" in prompt


def test_parse_verdict_orchestrator(repo_with_artifacts):
    verdict = parse_verdict("orchestrator", "", repo_with_artifacts)
    assert verdict == "feature"


def test_parse_verdict_architecture_mapper(repo_with_artifacts):
    verdict = parse_verdict("architecture_mapper", "", repo_with_artifacts)
    assert verdict == "high"


def test_parse_verdict_test_contract(repo_with_artifacts):
    verdict = parse_verdict("test_contract", "", repo_with_artifacts)
    assert verdict == "PASS"


def test_parse_verdict_verification(repo_with_artifacts):
    verdict = parse_verdict("verification", "", repo_with_artifacts)
    assert verdict == "PASS"


def test_parse_verdict_security(repo_with_artifacts):
    verdict = parse_verdict("security_policy", "", repo_with_artifacts)
    assert verdict == "APPROVED"


def test_parse_verdict_no_verdict_for_implementation(repo_with_artifacts):
    verdict = parse_verdict("implementation", "", repo_with_artifacts)
    assert verdict is None


def test_parse_stream_metrics():
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/a.py"}},
                {"type": "text", "text": "Done"},
            ]},
        }),
        json.dumps({
            "type": "result",
            "total_cost_usd": 0.05,
            "usage": {"input_tokens": 1000, "output_tokens": 500,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        }),
    ]
    metrics = _parse_stream_metrics(lines)
    assert metrics["input_tokens"] == 1000
    assert metrics["output_tokens"] == 500
    assert metrics["cost_usd"] == 0.05
    assert metrics["tool_calls"] == 1
    assert "/tmp/a.py" in metrics["files_changed"]


def test_parse_stream_metrics_empty():
    metrics = _parse_stream_metrics([])
    assert metrics["input_tokens"] == 0
    assert metrics["cost_usd"] == 0.0


def test_parse_stream_metrics_invalid_json():
    lines = ["not json", "", "also not json"]
    metrics = _parse_stream_metrics(lines)
    assert metrics["input_tokens"] == 0
    assert metrics["cost_usd"] == 0.0
