import pytest
from src.pipeline.routes import (
    AGENTS, TRANSFORM_AGENTS, DEVOPS_AGENTS, AGENT_ARTIFACTS,
    get_route, route_to_string, route_from_string,
    agent_name, agent_number, should_checkpoint,
    get_rollback_target, get_agents_registry, find_step_index,
)


def test_agent_registry():
    assert AGENTS[1] == "orchestrator"
    assert AGENTS[4] == "implementation"
    assert AGENTS[8] == "release_gatekeeper"
    assert len(AGENTS) == 8


def test_get_route_bugfix():
    route = get_route("bugfix")
    assert route == [1, 2, 4, 5, 6, 8]
    assert 3 not in route  # no architecture_mapper
    assert 7 not in route  # no security_policy


def test_get_route_refactor():
    route = get_route("refactor")
    assert route == [1, 3, 4, 5, 6, 8]
    assert 2 not in route  # no spec_builder
    assert 7 not in route  # no security_policy


def test_get_route_feature():
    route = get_route("feature")
    assert route == [1, 2, 3, 4, 5, 6, 7, 8]
    assert len(route) == 8


def test_get_route_migration():
    route = get_route("migration")
    assert route == [1, 2, 3, 4, 5, 6, 7, 8]


def test_get_route_invalid():
    with pytest.raises(ValueError):
        get_route("invalid_type")


def test_route_serialization():
    route = [1, 2, 4, 5, 6, 8]
    s = route_to_string(route)
    assert s == "1,2,4,5,6,8"
    assert route_from_string(s) == route


def test_agent_name_and_number():
    assert agent_name(1) == "orchestrator"
    assert agent_number("orchestrator") == 1
    assert agent_name(4) == "implementation"
    assert agent_number("implementation") == 4


def test_checkpoint_rules_feature():
    run = {"work_type": "feature", "risk_level": "low"}
    assert should_checkpoint(2, run) is True   # spec_builder for feature
    assert should_checkpoint(3, run) is True   # arch_mapper always
    assert should_checkpoint(7, run) is False  # security only for medium/high risk
    assert should_checkpoint(8, run) is True   # release_gatekeeper always
    assert should_checkpoint(4, run) is False  # implementation never


def test_checkpoint_rules_bugfix():
    run = {"work_type": "bugfix", "risk_level": "low"}
    assert should_checkpoint(2, run) is False  # spec_builder not for bugfix
    assert should_checkpoint(8, run) is True   # release_gatekeeper always


def test_checkpoint_rules_migration():
    run = {"work_type": "migration", "risk_level": "high"}
    assert should_checkpoint(2, run) is True   # spec_builder for migration
    assert should_checkpoint(3, run) is True
    assert should_checkpoint(7, run) is True   # security for high risk
    assert should_checkpoint(8, run) is True


def test_rollback_targets():
    assert get_rollback_target(5) == 4  # test_contract -> implementation
    assert get_rollback_target(6) == 4  # verification -> implementation
    assert get_rollback_target(4) is None  # no rollback for implementation
    assert get_rollback_target(1) is None


def test_find_step_index():
    route = [1, 2, 4, 5, 6, 8]
    assert find_step_index(route, 1) == 0
    assert find_step_index(route, 4) == 2
    assert find_step_index(route, 8) == 5


def test_transformation_route():
    route = get_route("transformation")
    assert route == [1, 2, 3, 4, 5, 6]
    assert len(TRANSFORM_AGENTS) == 6


def test_devops_route():
    route = get_route("devops")
    assert route == [1, 2, 3, 4, 5, 6]
    assert len(DEVOPS_AGENTS) == 6


def test_get_agents_registry():
    assert get_agents_registry("feature") is AGENTS
    assert get_agents_registry("transformation") is TRANSFORM_AGENTS
    assert get_agents_registry("devops") is DEVOPS_AGENTS


def test_agent_artifacts_mapping():
    """Every agent in every pipeline has an artifact mapping."""
    for agent in AGENTS.values():
        assert agent in AGENT_ARTIFACTS, f"Missing artifact for {agent}"
    for agent in TRANSFORM_AGENTS.values():
        assert agent in AGENT_ARTIFACTS, f"Missing artifact for {agent}"
    for agent in DEVOPS_AGENTS.values():
        assert agent in AGENT_ARTIFACTS, f"Missing artifact for {agent}"


def test_devops_checkpoint_rules():
    run = {"work_type": "devops", "risk_level": "low"}
    assert should_checkpoint(1, run) is True   # infra_analyst always
    assert should_checkpoint(3, run) is True   # safety_reviewer always
    assert should_checkpoint(6, run) is True   # ops_reporter always
    assert should_checkpoint(4, run) is False  # infra_executor never


def test_transform_checkpoint_rules():
    run = {"work_type": "transformation"}
    assert should_checkpoint(1, run) is True
    assert should_checkpoint(2, run) is True
    assert should_checkpoint(3, run) is True
    assert should_checkpoint(6, run) is True
    assert should_checkpoint(4, run) is False


def test_rollback_targets_devops():
    assert get_rollback_target(5, "devops") == 4
    assert get_rollback_target(4, "devops") is None


def test_rollback_targets_transform():
    assert get_rollback_target(5, "transformation") == 4
    assert get_rollback_target(3, "transformation") is None
