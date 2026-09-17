"""Factory of Code -- Orchestrator Service.

Polls PostgreSQL for new/resumed runs, publishes jobs to RabbitMQ,
consumes results, handles checkpoints and rollbacks.
"""
import asyncio
import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import Config, load_agents_config
from src.db import Database
from src.gitlab_client import GitLabClient
from src.pipeline.routes import (
    get_agents_registry, route_from_string,
    should_checkpoint, get_rollback_target, find_step_index,
    FAIL_VERDICTS, MAX_ROLLBACKS, AGENT_INPUTS,
)
from src.presets import OVERRIDABLE_FIELDS
from src.shared.minio_client import MinIOClient
from src.shared.rabbitmq import (
    get_connection, declare_topology, publish_job, publish_cancel,
    RESULT_QUEUE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("orchestrator")

# Pending result futures
_pending_results: dict[str, asyncio.Future] = {}


def _build_checkpoint_summary(minio, run_id: int, agent: str) -> str:
    from src.pipeline.routes import AGENT_ARTIFACTS
    fn = AGENT_ARTIFACTS.get(agent)
    if fn and minio:
        try:
            content = minio.download_text(run_id, fn)
            if content:
                lines = [l.strip() for l in content.strip().split("\n")
                         if l.strip().startswith("#") or l.strip().startswith("- ") or l.strip().startswith("**")][:15]
                if lines:
                    return "\n".join(lines)
        except Exception:
            pass
    return f"Этап {agent} завершён."


async def process_run(db, run_id, channel, gitlab, minio, agents_config):
    """Walk through a run's route, one job at a time via RabbitMQ."""
    run = await db.get_run(run_id)
    if not run:
        return

    route = route_from_string(run["route"])
    agents_reg = get_agents_registry(run["work_type"])
    await db.update_run(run_id, status="running")

    repo = await db.get_repo(run["repo_id"])
    if not repo:
        await db.update_run(run_id, status="failed", final_verdict="repo not found")
        return

    # Always read fresh token from DB (may be updated via Settings at any time)
    gitlab_token = await db.get_setting("gitlab_token") or (gitlab.token if gitlab else None)
    repo_url = repo["clone_url_http"]
    if gitlab_token:
        repo_url = re.sub(r'^https://', f'https://oauth2:{gitlab_token}@', repo_url)

    source_repo_url = None
    if run.get("source_repo_id"):
        sr = await db.get_repo(run["source_repo_id"])
        if sr:
            source_repo_url = sr["clone_url_http"]
            if gitlab_token:
                source_repo_url = re.sub(r'^https://', f'https://oauth2:{gitlab_token}@', source_repo_url)

    preset_snapshot = run.get("preset_snapshot") or {}
    repo_context = repo.get("context", "")
    if source_repo_url:
        repo_context += f"\n\nИсходный репозиторий: git clone {source_repo_url} в отдельную директорию для изучения."

    step_idx = run["current_step_idx"]

    while step_idx < len(route):
        run = await db.get_run(run_id)
        if run["status"] == "cancelled":
            return

        agent_num = route[step_idx]
        agent = agents_reg[agent_num]

        # Build config
        config = dict(agents_config.get(agent, {
            "model": "claude-sonnet-4-6", "max_turns": 30, "timeout": 1800,
            "allowed_tools": ["Read", "Glob", "Grep", "Write", "Edit", "Bash"],
        }))
        if agent in preset_snapshot:
            for k, v in preset_snapshot[agent].items():
                if k in OVERRIDABLE_FIELDS:
                    config[k] = v

        default_prompt = await db.get_agent_prompt(agent)
        if default_prompt:
            config["_default_prompt"] = default_prompt
        config["_repo_context"] = repo_context

        existing = await db.get_latest_step_for_agent(run_id, agent)
        attempt = (existing["attempt"] + 1) if existing else 1
        step_id = await db.create_step(run_id, agent, agent_number=agent_num,
                                        step_order=step_idx, attempt=attempt)

        # Publish job
        job_id = uuid.uuid4().hex
        artifact_inputs = AGENT_INPUTS.get(agent, [])
        is_final_step = (step_idx == len(route) - 1)
        await publish_job(channel, {
            "job_id": job_id, "run_id": run_id, "step_id": step_id,
            "agent_name": agent, "agent_number": agent_num,
            "step_order": step_idx, "attempt": attempt,
            "work_type": run["work_type"],
            "repo_url": repo_url, "base_branch": run["base_branch"],
            "work_branch": run["work_branch"],
            "task_description": run["description"],
            "run_context": {"work_type": run["work_type"],
                            "risk_level": run.get("risk_level", "low"),
                            "rollback_count": run["rollback_count"]},
            "agent_config": config,
            "source_repo_url": source_repo_url,
            "artifact_inputs": artifact_inputs,
            "is_final_step": is_final_step,
        })
        log.info(f"Job {job_id}: run={run_id} agent={agent}")

        # Wait for result
        future = asyncio.get_event_loop().create_future()
        _pending_results[job_id] = future
        try:
            result = await asyncio.wait_for(future, timeout=3600)
        except asyncio.TimeoutError:
            await db.update_run(run_id, status="failed", final_verdict="Worker timeout")
            return
        finally:
            _pending_results.pop(job_id, None)

        verdict = result.get("verdict")

        if agent == "architecture_mapper" and verdict:
            await db.update_run(run_id, risk_level=verdict)
            run = await db.get_run(run_id)

        if verdict and verdict.upper() in FAIL_VERDICTS:
            target = get_rollback_target(agent_num, run["work_type"])
            if target and run["rollback_count"] < MAX_ROLLBACKS:
                idx = find_step_index(route, target)
                await db.update_run(run_id, current_step_idx=idx,
                                     rollback_count=run["rollback_count"] + 1)
                step_idx = idx
                run = await db.get_run(run_id)
                continue
            else:
                await db.update_run(run_id, status="failed",
                                     final_verdict=f"max rollbacks ({verdict})")
                return

        if should_checkpoint(agent_num, run):
            summary = _build_checkpoint_summary(minio, run_id, agent)
            await db.create_checkpoint(run_id, step_id, agent, reason=summary)
            await db.update_run(run_id, status="awaiting_checkpoint",
                                 current_step_idx=step_idx + 1)
            log.info(f"Run {run_id} checkpoint after {agent}")
            return

        step_idx += 1
        await db.update_run(run_id, current_step_idx=step_idx)

    # Done -- create MR only if working in a separate branch
    mr_iid = mr_url = None
    needs_mr = run["work_branch"] != run["base_branch"]

    # Re-read token for MR creation (may have been set after orchestrator start)
    fresh_token = await db.get_setting("gitlab_token") or (gitlab.token if gitlab else "")
    fresh_url = await db.get_setting("gitlab_url") or (gitlab.base_url if gitlab else "https://gitlab.com")
    mr_gitlab = GitLabClient(fresh_url, fresh_token) if fresh_token else gitlab

    if needs_mr:
        has_changes = False
        if minio:
            try:
                diff = minio.download_diff(run_id)
                has_changes = bool(diff and diff.strip())
            except Exception:
                has_changes = True

        if mr_gitlab and repo and has_changes:
            try:
                desc = ""
                if minio:
                    try:
                        desc = minio.download_text(run_id, "pr-summary.md") or ""
                    except Exception:
                        pass
                mr = await mr_gitlab.create_merge_request(
                    repo["gitlab_project_id"], run["work_branch"],
                    run["base_branch"], run["title"], desc)
                mr_iid, mr_url = mr.get("iid"), mr.get("url")
            except Exception as e:
                log.warning(f"MR failed: {e}")
        elif not has_changes:
            log.warning(f"Run {run_id}: no code changes detected, skipping MR")
    else:
        log.info(f"Run {run_id}: committed directly to {run['work_branch']}, no MR needed")

    verdict = "PASS"
    await db.update_run(run_id, status="completed", final_verdict=verdict,
                         mr_iid=mr_iid, mr_url=mr_url)
    log.info(f"Run {run_id} completed")


async def result_consumer(channel):
    queue = await channel.get_queue(RESULT_QUEUE)

    async def on_msg(message):
        async with message.process():
            data = json.loads(message.body)
            f = _pending_results.get(data.get("job_id"))
            if f and not f.done():
                f.set_result(data)

    await queue.consume(on_msg)


async def main():
    config = Config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    rmq_url = os.environ.get("RABBITMQ_URL", "amqp://factory:factory@rabbitmq:5672/")

    db = Database(config.database_url)
    for i in range(30):
        try:
            await db.init()
            break
        except Exception:
            if i < 29: await asyncio.sleep(2)
            else: raise
    log.info("Connected to PostgreSQL")

    minio = MinIOClient(config.minio_endpoint, config.minio_access_key, config.minio_secret_key)
    try:
        minio.ensure_bucket()
    except Exception:
        minio = None

    gitlab_token = config.gitlab_token or await db.get_setting("gitlab_token") or ""
    gitlab_url = await db.get_setting("gitlab_url") or config.gitlab_url
    gitlab = GitLabClient(gitlab_url, gitlab_token) if gitlab_token else None

    try:
        agents_config = load_agents_config()
    except FileNotFoundError:
        agents_config = {"pipeline": {"max_concurrent_runs": 5}}

    rmq = await get_connection(rmq_url)
    channel = await rmq.channel()
    await declare_topology(channel)
    log.info("Connected to RabbitMQ")

    asyncio.create_task(result_consumer(channel))

    # Recovery
    for run in await db.list_runs_by_status("running"):
        log.info(f"Recovering run {run['id']}")
        await db.update_run(run["id"], orchestrator_action="start",
                             status="pending", current_step_idx=0)

    log.info("Orchestrator ready")

    active: dict[int, asyncio.Task] = {}
    while True:
        try:
            for run in await db.get_runs_with_action():
                action, rid = run["orchestrator_action"], run["id"]
                await db.clear_orchestrator_action(rid)

                if action == "start" and rid not in active:
                    t = asyncio.create_task(process_run(db, rid, channel, gitlab, minio, agents_config))
                    active[rid] = t
                    t.add_done_callback(lambda _, r=rid: active.pop(r, None))
                elif action == "resume" and rid not in active:
                    await db.update_run(rid, status="running")
                    t = asyncio.create_task(process_run(db, rid, channel, gitlab, minio, agents_config))
                    active[rid] = t
                    t.add_done_callback(lambda _, r=rid: active.pop(r, None))
                elif action == "cancel":
                    await publish_cancel(channel, rid)
                    t = active.pop(rid, None)
                    if t: t.cancel()
        except Exception as e:
            log.exception(f"Loop error: {e}")
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
