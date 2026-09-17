from __future__ import annotations

# ── Standard Pipeline: 8 agents ──

AGENTS = {
    1: "orchestrator",
    2: "spec_builder",
    3: "architecture_mapper",
    4: "implementation",
    5: "test_contract",
    6: "verification",
    7: "security_policy",
    8: "release_gatekeeper",
}

AGENT_NUMBERS = {v: k for k, v in AGENTS.items()}

ROUTES: dict[str, list[int]] = {
    "bugfix":    [1, 2, 4, 5, 6, 8],
    "refactor":  [1, 3, 4, 5, 6, 8],
    "migration": [1, 2, 3, 4, 5, 6, 7, 8],
    "feature":   [1, 2, 3, 4, 5, 6, 7, 8],
    "hotfix":    [1, 2, 4, 5, 6, 8],
}

CHECKPOINT_RULES: dict[int, callable] = {
    2: lambda run: run["work_type"] in ("feature", "migration", "hotfix"),
    3: lambda run: True,
    7: lambda run: run.get("risk_level", "low") in ("medium", "high"),
    8: lambda run: True,
}

ROLLBACK_TARGETS: dict[int, int] = {
    5: 4,
    6: 4,
}

MAX_ROLLBACKS = 3
FAIL_VERDICTS = {"FAIL", "FAIL_TEST", "FAIL_SPEC"}

# ── Transformation Pipeline: 6 agents ──

TRANSFORM_AGENTS = {
    1: "code_archeologist",
    2: "transformation_architect",
    3: "feature_mapper",
    4: "transform_implementer",
    5: "compatibility_checker",
    6: "transform_release",
}

TRANSFORM_AGENT_NUMBERS = {v: k for k, v in TRANSFORM_AGENTS.items()}

TRANSFORM_ROUTE = [1, 2, 3, 4, 5, 6]

# Checkpoints for transformation: after analysis (1), after architecture (2), after mapping (3), before release (6)
TRANSFORM_CHECKPOINT_RULES: dict[int, callable] = {
    1: lambda run: True,   # After code archeologist -- review the analysis
    2: lambda run: True,   # After transformation architect -- approve the plan
    3: lambda run: True,   # After feature mapper -- confirm the mapping
    6: lambda run: True,   # Before release -- final review
}

# Rollback: if compatibility check fails, go back to implementer
TRANSFORM_ROLLBACK_TARGETS: dict[int, int] = {
    5: 4,
}

# ── DevOps Pipeline: 6 agents ──

DEVOPS_AGENTS = {
    1: "infra_analyst",
    2: "change_planner",
    3: "safety_reviewer",
    4: "infra_executor",
    5: "health_checker",
    6: "ops_reporter",
}

DEVOPS_AGENT_NUMBERS = {v: k for k, v in DEVOPS_AGENTS.items()}

DEVOPS_ROUTE = [1, 2, 3, 4, 5, 6]

# Checkpoints: after analysis (1), after safety review (3), after execution (4)
DEVOPS_CHECKPOINT_RULES: dict[int, callable] = {
    1: lambda run: True,   # Review analysis before planning
    3: lambda run: True,   # Approve safety review before execution
    6: lambda run: True,   # Final review
}

DEVOPS_ROLLBACK_TARGETS: dict[int, int] = {
    5: 4,  # Health check fails -> re-execute (with fixes)
}


def get_route(work_type: str) -> list[int]:
    if work_type == "transformation":
        return list(TRANSFORM_ROUTE)
    if work_type == "devops":
        return list(DEVOPS_ROUTE)
    route = ROUTES.get(work_type)
    if not route:
        raise ValueError(f"Unknown work type: {work_type}")
    return list(route)


def get_agents_registry(work_type: str) -> dict[int, str]:
    if work_type == "transformation":
        return TRANSFORM_AGENTS
    if work_type == "devops":
        return DEVOPS_AGENTS
    return AGENTS


def route_to_string(route: list[int]) -> str:
    return ",".join(str(n) for n in route)


def route_from_string(route_str: str) -> list[int]:
    return [int(n) for n in route_str.split(",")]


def agent_name(number: int, work_type: str = "") -> str:
    return get_agents_registry(work_type)[number]


def agent_number(name: str) -> int:
    for reg in (AGENT_NUMBERS, TRANSFORM_AGENT_NUMBERS, DEVOPS_AGENT_NUMBERS):
        if name in reg:
            return reg[name]
    raise ValueError(f"Unknown agent: {name}")


def should_checkpoint(agent_num: int, run: dict) -> bool:
    wt = run.get("work_type", "")
    if wt == "transformation":
        rules = TRANSFORM_CHECKPOINT_RULES
    elif wt == "devops":
        rules = DEVOPS_CHECKPOINT_RULES
    else:
        rules = CHECKPOINT_RULES
    rule = rules.get(agent_num)
    return rule(run) if rule else False


def get_rollback_target(agent_num: int, work_type: str = "") -> int | None:
    if work_type == "transformation":
        return TRANSFORM_ROLLBACK_TARGETS.get(agent_num)
    if work_type == "devops":
        return DEVOPS_ROLLBACK_TARGETS.get(agent_num)
    return ROLLBACK_TARGETS.get(agent_num)


def find_step_index(route: list[int], agent_num: int) -> int:
    return route.index(agent_num)


# ── Agent → Primary Artifact mapping (single source of truth) ──

AGENT_ARTIFACTS = {
    # Standard pipeline
    "orchestrator": "routing.yaml",
    "spec_builder": "spec.md",
    "architecture_mapper": "impact-map.md",
    "implementation": "patch-summary.md",
    "test_contract": "test-plan.md",
    "verification": "evidence.md",
    "security_policy": "policy-verdict.json",
    "release_gatekeeper": "pr-summary.md",
    # Transformation pipeline
    "code_archeologist": "codebase-map.md",
    "transformation_architect": "transformation-plan.md",
    "feature_mapper": "feature-map.md",
    "transform_implementer": "implementation-report.md",
    "compatibility_checker": "compatibility-report.md",
    "transform_release": "transform-summary.md",
    # DevOps pipeline
    "infra_analyst": "infra-analysis.md",
    "change_planner": "change-plan.md",
    "safety_reviewer": "safety-review.md",
    "infra_executor": "execution-log.md",
    "health_checker": "health-report.md",
    "ops_reporter": "ops-report.md",
}

# What artifacts each agent needs from previous steps (downloaded from MinIO)
AGENT_INPUTS: dict[str, list[str]] = {
    # Standard pipeline
    "orchestrator": [],
    "spec_builder": ["routing.yaml"],
    "architecture_mapper": ["spec.md", "scope.yaml"],
    "implementation": ["spec.md", "impact-map.md"],
    "test_contract": ["spec.md", "patch-summary.md"],
    "verification": ["test-plan.md", "regression-matrix.md", "contract-verdict.json", "spec.md"],
    "security_policy": [],
    "release_gatekeeper": ["verdict.json", "evidence.md", "policy-verdict.json", "spec.md"],
    # Transformation pipeline
    "code_archeologist": [],
    "transformation_architect": ["codebase-map.md", "feature-inventory.md", "tech-debt.md"],
    "feature_mapper": ["feature-inventory.md", "transformation-plan.md"],
    "transform_implementer": ["transformation-plan.md", "feature-map.md", "migration-order.md"],
    "compatibility_checker": ["feature-map.md", "implementation-report.md"],
    "transform_release": ["transformation-plan.md", "feature-map.md", "compatibility-report.md"],
    # DevOps pipeline
    "infra_analyst": [],
    "change_planner": ["infra-analysis.md", "infra-inventory.md"],
    "safety_reviewer": ["change-plan.md"],
    "infra_executor": ["change-plan.md", "safety-review.md"],
    "health_checker": ["execution-log.md", "change-plan.md"],
    "ops_reporter": ["infra-analysis.md", "change-plan.md", "execution-log.md", "health-report.md"],
}
