import pytest
from src.presets import resolve_agent_config, build_preset_snapshot


def test_resolve_no_overrides():
    base = {
        "orchestrator": {"model": "claude-sonnet-4-6", "max_turns": 5, "timeout": 300,
                         "artifacts_read": [], "artifacts_write": ["routing.yaml"]},
        "pipeline": {"max_concurrent_runs": 2},
    }
    result = resolve_agent_config(base, {})
    assert result["orchestrator"]["model"] == "claude-sonnet-4-6"
    assert result["pipeline"]["max_concurrent_runs"] == 2


def test_resolve_partial_override():
    base = {
        "implementation": {"model": "claude-sonnet-4-6", "max_turns": 40, "timeout": 1800,
                           "artifacts_read": ["spec.md"], "artifacts_write": ["patch-summary.md"]},
    }
    overrides = {
        "implementation": {"model": "claude-opus-4-6", "max_turns": 60},
    }
    result = resolve_agent_config(base, overrides)
    assert result["implementation"]["model"] == "claude-opus-4-6"
    assert result["implementation"]["max_turns"] == 60
    assert result["implementation"]["timeout"] == 1800  # unchanged
    assert result["implementation"]["artifacts_read"] == ["spec.md"]  # never overridden


def test_resolve_system_prompt_override():
    base = {
        "spec_builder": {"model": "claude-sonnet-4-6", "max_turns": 15},
    }
    overrides = {
        "spec_builder": {"system_prompt": "Custom prompt for Python"},
    }
    result = resolve_agent_config(base, overrides)
    assert result["spec_builder"]["system_prompt"] == "Custom prompt for Python"
    assert result["spec_builder"]["model"] == "claude-sonnet-4-6"


def test_resolve_artifacts_not_overridable():
    base = {
        "orchestrator": {"model": "claude-sonnet-4-6",
                         "artifacts_read": [], "artifacts_write": ["routing.yaml"]},
    }
    overrides = {
        "orchestrator": {"artifacts_read": ["hacked.md"], "artifacts_write": ["evil.yaml"]},
    }
    result = resolve_agent_config(base, overrides)
    assert result["orchestrator"]["artifacts_read"] == []
    assert result["orchestrator"]["artifacts_write"] == ["routing.yaml"]


def test_resolve_pipeline_passthrough():
    base = {
        "orchestrator": {"model": "claude-sonnet-4-6"},
        "pipeline": {"max_concurrent_runs": 2, "max_rollbacks": 3},
    }
    overrides = {"pipeline": {"max_concurrent_runs": 99}}
    result = resolve_agent_config(base, overrides)
    assert result["pipeline"]["max_concurrent_runs"] == 2  # pipeline is not overridable


def test_resolve_multiple_agents():
    base = {
        "orchestrator": {"model": "claude-sonnet-4-6", "max_turns": 5},
        "implementation": {"model": "claude-sonnet-4-6", "max_turns": 40},
        "verification": {"model": "claude-sonnet-4-6", "max_turns": 10},
    }
    overrides = {
        "orchestrator": {"model": "claude-opus-4-6"},
        "implementation": {"max_turns": 80, "timeout": 3600},
    }
    result = resolve_agent_config(base, overrides)
    assert result["orchestrator"]["model"] == "claude-opus-4-6"
    assert result["implementation"]["max_turns"] == 80
    assert result["verification"]["model"] == "claude-sonnet-4-6"  # unaffected


def test_build_preset_snapshot_none():
    assert build_preset_snapshot({}, None) is None


def test_build_preset_snapshot_empty():
    preset = {"agent_configs": {}}
    assert build_preset_snapshot({}, preset) is None


def test_build_preset_snapshot_filters():
    preset = {
        "agent_configs": {
            "implementation": {
                "model": "claude-opus-4-6",
                "system_prompt": "Custom",
                "artifacts_read": ["should_be_filtered"],
            },
        },
    }
    snapshot = build_preset_snapshot({}, preset)
    assert "implementation" in snapshot
    assert snapshot["implementation"]["model"] == "claude-opus-4-6"
    assert snapshot["implementation"]["system_prompt"] == "Custom"
    assert "artifacts_read" not in snapshot["implementation"]


@pytest.mark.asyncio
async def test_db_preset_crud(db):
    preset_id = await db.create_preset("Test Preset", "For testing", {
        "implementation": {"model": "claude-opus-4-6", "max_turns": 60},
    })
    assert preset_id is not None

    preset = await db.get_preset(preset_id)
    assert preset["name"] == "Test Preset"
    assert preset["agent_configs"]["implementation"]["model"] == "claude-opus-4-6"

    await db.update_preset(preset_id, "Updated", "New desc", {
        "implementation": {"model": "claude-sonnet-4-6"},
    })
    preset = await db.get_preset(preset_id)
    assert preset["name"] == "Updated"

    presets = await db.list_presets()
    assert len(presets) == 1

    await db.delete_preset(preset_id)
    presets = await db.list_presets()
    assert len(presets) == 0


@pytest.mark.asyncio
async def test_repo_preset_assignment(db):
    preset_id = await db.create_preset("Python", "Python preset", {})
    repo_id = await db.create_repo(
        gitlab_project_id=1, name="repo", full_path="g/repo",
        clone_url_ssh="ssh://url", clone_url_http="https://url",
    )

    await db.set_repo_preset(repo_id, preset_id)
    repo = await db.get_repo(repo_id)
    assert repo["preset_id"] == preset_id

    # Unset preset
    await db.set_repo_preset(repo_id, None)
    repo = await db.get_repo(repo_id)
    assert repo["preset_id"] is None


@pytest.mark.asyncio
async def test_delete_preset_nullifies_repo(db):
    preset_id = await db.create_preset("Temp", "Will be deleted", {})
    repo_id = await db.create_repo(
        gitlab_project_id=2, name="repo2", full_path="g/repo2",
        clone_url_ssh="ssh://url", clone_url_http="https://url",
    )
    await db.set_repo_preset(repo_id, preset_id)

    await db.delete_preset(preset_id)
    repo = await db.get_repo(repo_id)
    assert repo["preset_id"] is None  # ON DELETE SET NULL
