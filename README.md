# ai-codegen

[![tests](https://github.com/syntr0x79/ai-codegen/actions/workflows/tests.yml/badge.svg)](https://github.com/syntr0x79/ai-codegen/actions/workflows/tests.yml)

A pipeline that takes a task description and produces a merge request — through nine agents that hand work to each other as **files**, not as conversation.

Each stage declares what it may read, what it must write, which tools it is allowed to call, and how many turns it gets. A stage that does not produce its artifacts fails the run. A stage cannot read an artifact it was not granted.

## Why artifacts instead of a conversation

The usual multi-agent design passes a growing message history between roles. It works in a demo and degrades in practice: context grows without bound, every stage can see everything, and when the output is wrong there is no way to tell which step went wrong.

Here the contract is on disk:

```yaml
spec_builder:
  model: claude-sonnet-4-6
  max_turns: 15
  timeout: 600
  allowed_tools: [Read, Glob, Grep, Write]
  artifacts_read:  [routing.yaml]
  artifacts_write: [spec.md, acceptance.md, scope.yaml, trace.yaml]

architecture_mapper:
  artifacts_read:  [spec.md, scope.yaml]
  artifacts_write: [impact-map.md, adr-delta.md]
```

Three properties follow from that, and they are the reason for the design:

- **Inspectable.** When a run produces the wrong patch, you open `spec.md` and `impact-map.md` and see exactly where the meaning drifted.
- **Bounded.** A stage reads two files, not the entire history of the run. Context stays small, which is also what keeps cost predictable.
- **Resumable.** Artifacts are durable, so a failed run restarts at the stage that failed rather than from the beginning.

Note that `implementation` is the only stage with `Edit` and `Bash`, and the only one with a large turn budget (40 turns, 30 minutes). Everything before it reads and writes documents; everything after it judges. Exactly one stage can change code.

## The pipeline

| # | Agent | Reads | Writes |
|---|-------|-------|--------|
| 1 | `orchestrator` | — | `routing.yaml` |
| 2 | `spec_builder` | `routing.yaml` | `spec.md`, `acceptance.md`, `scope.yaml`, `trace.yaml` |
| 3 | `architecture_mapper` | `spec.md`, `scope.yaml` | `impact-map.md`, `adr-delta.md` |
| 4 | `implementation` | spec + map | the patch, `patch-summary.md` |
| 5 | `test_contract` | `acceptance.md`, patch | `test-plan.md`, `contract-verdict.json` |
| 6 | `verification` | everything above | `verdict.json`, `evidence.md`, `regression-matrix.md` |
| 7 | `security_policy` | the patch | `policy-verdict.json` |
| 8 | `release_gatekeeper` | all verdicts | `pr-summary.md`, `rollout.md`, `rollback.md` |
| 9 | `pipeline` | — | CI interaction |

Verdicts are JSON, not prose, because a gate that returns an essay is a gate no machine can act on.

## What else is in here

- **Web UI** — FastAPI with server-rendered Jinja templates and SSE for live run output. Runs, presets, repositories, settings, checkpoints.
- **Presets** — a task shape saved and re-run, so recurring work does not get re-specified each time.
- **Worker** — RabbitMQ consumer executing runs outside the request cycle.
- **Artifact storage** — MinIO; Postgres with Alembic migrations for run state.
- **A second pipeline** (`src/prompts/devops/`) applying the same idea to infrastructure changes: analyst → planner → safety reviewer → executor → health checker → reporter. The safety reviewer sits between the plan and the execution deliberately.

## Running it

```bash
cp .env.example .env
docker compose up -d
alembic upgrade head
```

Then open the UI, register a repository with a token, and start a run.

```bash
pytest          # 17 test modules
```

## About the code

Around 6 800 lines of Python. FastAPI, asyncpg, Alembic, MinIO, aio-pika, Jinja2, SSE. No agent framework — the orchestration is a few hundred lines that read `agents.yaml`, prepare a working directory, enforce the artifact contract and invoke the model.

The prompt library in `src/prompts/` is written in Russian, which is the working language of the team it was built for. The code, the contracts and the interfaces are English.

Written on my own time, outside any employer's scope. The prompt files describing infrastructure contain an example environment, not a real one.

## Author

Dmitry Buravtsov — platform and infrastructure engineer.
[github.com/syntr0x79](https://github.com/syntr0x79)

## License

MIT — see [LICENSE](LICENSE).
