from __future__ import annotations

OVERRIDABLE_FIELDS = {"model", "max_turns", "timeout", "allowed_tools", "system_prompt"}


def resolve_agent_config(base_config: dict, preset_overrides: dict) -> dict:
    """Merge preset overrides on top of agents.yaml defaults.

    Only OVERRIDABLE_FIELDS are applied from overrides.
    artifacts_read/artifacts_write are never overridden.
    The 'pipeline' key is passed through unchanged.
    """
    result = {}
    for agent_name, defaults in base_config.items():
        if agent_name == "pipeline":
            result[agent_name] = defaults
            continue
        merged = dict(defaults)
        agent_overrides = preset_overrides.get(agent_name, {})
        for key in OVERRIDABLE_FIELDS:
            if key in agent_overrides:
                merged[key] = agent_overrides[key]
        result[agent_name] = merged
    return result


def build_preset_snapshot(base_config: dict, preset: dict | None) -> dict | None:
    """Build a snapshot of the resolved config to store with the run.

    Returns the preset's agent_configs dict (overrides only), or None if no preset.
    The snapshot is stored in pipeline_runs.preset_snapshot for audit trail.
    """
    if not preset:
        return None
    agent_configs = preset.get("agent_configs", {})
    if not agent_configs:
        return None
    # Only include overridable fields in the snapshot
    snapshot = {}
    for agent_name, overrides in agent_configs.items():
        filtered = {k: v for k, v in overrides.items() if k in OVERRIDABLE_FIELDS}
        if filtered:
            snapshot[agent_name] = filtered
    return snapshot if snapshot else None
