from __future__ import annotations

import json
from datetime import datetime, timezone

import asyncpg


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def init(self):
        self._pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)

    async def close(self):
        if self._pool:
            await self._pool.close()

    def _record_to_dict(self, record: asyncpg.Record | None) -> dict | None:
        return dict(record) if record else None

    def _records_to_list(self, records: list[asyncpg.Record]) -> list[dict]:
        return [dict(r) for r in records]

    # ── Users ──

    async def create_user(self, username: str, password_hash: str) -> int:
        row = await self._pool.fetchrow(
            "INSERT INTO users (username, password_hash, created_at) VALUES ($1, $2, $3) RETURNING id",
            username, password_hash, _now(),
        )
        return row["id"]

    async def get_user_by_username(self, username: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM users WHERE username = $1", username
        )
        return self._record_to_dict(row)

    # ── Settings ──

    async def get_setting(self, key: str) -> str | None:
        row = await self._pool.fetchrow(
            "SELECT value FROM settings WHERE key = $1", key
        )
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self._pool.execute(
            "INSERT INTO settings (key, value) VALUES ($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value = $2",
            key, value,
        )

    async def get_all_settings(self) -> dict:
        rows = await self._pool.fetch("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in rows}

    # ── Agent Prompts ──

    async def get_agent_prompt(self, agent_name: str) -> str | None:
        row = await self._pool.fetchrow(
            "SELECT system_prompt FROM agent_prompts WHERE agent_name = $1", agent_name
        )
        return row["system_prompt"] if row else None

    async def get_all_agent_prompts(self) -> dict[str, str]:
        rows = await self._pool.fetch("SELECT agent_name, system_prompt FROM agent_prompts ORDER BY agent_name")
        return {r["agent_name"]: r["system_prompt"] for r in rows}

    async def set_agent_prompt(self, agent_name: str, system_prompt: str) -> None:
        await self._pool.execute(
            "INSERT INTO agent_prompts (agent_name, system_prompt, updated_at) "
            "VALUES ($1, $2, $3) ON CONFLICT (agent_name) DO UPDATE SET system_prompt = $2, updated_at = $3",
            agent_name, system_prompt, _now(),
        )

    # ── Repos ──

    async def create_repo(
        self, gitlab_project_id: int, name: str, full_path: str,
        clone_url_ssh: str, clone_url_http: str, default_branch: str = "main",
    ) -> int:
        row = await self._pool.fetchrow(
            """INSERT INTO repos (gitlab_project_id, name, full_path,
               clone_url_ssh, clone_url_http, default_branch, last_synced_at, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $7) RETURNING id""",
            gitlab_project_id, name, full_path,
            clone_url_ssh, clone_url_http, default_branch, _now(),
        )
        return row["id"]

    async def get_repo(self, repo_id: int) -> dict | None:
        row = await self._pool.fetchrow("SELECT * FROM repos WHERE id = $1", repo_id)
        return self._record_to_dict(row)

    async def get_repo_by_gitlab_id(self, gitlab_project_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM repos WHERE gitlab_project_id = $1", gitlab_project_id
        )
        return self._record_to_dict(row)

    async def list_repos(self) -> list[dict]:
        rows = await self._pool.fetch("SELECT * FROM repos ORDER BY name")
        return self._records_to_list(rows)

    async def delete_repo(self, repo_id: int) -> None:
        await self._pool.execute("DELETE FROM repos WHERE id = $1", repo_id)

    async def update_repo_sync(self, repo_id: int, **kwargs) -> None:
        kwargs["last_synced_at"] = _now()
        sets = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(kwargs))
        vals = list(kwargs.values()) + [repo_id]
        await self._pool.execute(
            f"UPDATE repos SET {sets} WHERE id = ${len(vals)}", *vals
        )

    async def set_repo_preset(self, repo_id: int, preset_id: int | None) -> None:
        await self._pool.execute(
            "UPDATE repos SET preset_id = $1 WHERE id = $2", preset_id, repo_id
        )

    # ── Agent Presets ──

    async def create_preset(self, name: str, description: str, agent_configs: dict) -> int:
        row = await self._pool.fetchrow(
            """INSERT INTO agent_presets (name, description, agent_configs, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $4) RETURNING id""",
            name, description, json.dumps(agent_configs), _now(),
        )
        return row["id"]

    async def get_preset(self, preset_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM agent_presets WHERE id = $1", preset_id
        )
        if not row:
            return None
        d = dict(row)
        if isinstance(d.get("agent_configs"), str):
            d["agent_configs"] = json.loads(d["agent_configs"])
        return d

    async def list_presets(self) -> list[dict]:
        rows = await self._pool.fetch("SELECT * FROM agent_presets ORDER BY name")
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("agent_configs"), str):
                d["agent_configs"] = json.loads(d["agent_configs"])
            result.append(d)
        return result

    async def update_preset(self, preset_id: int, name: str, description: str, agent_configs: dict) -> None:
        await self._pool.execute(
            """UPDATE agent_presets SET name = $1, description = $2,
               agent_configs = $3, updated_at = $4 WHERE id = $5""",
            name, description, json.dumps(agent_configs), _now(), preset_id,
        )

    async def delete_preset(self, preset_id: int) -> None:
        await self._pool.execute("DELETE FROM agent_presets WHERE id = $1", preset_id)

    # ── Pipeline Runs ──

    async def create_run(
        self, title: str, description: str, repo_id: int,
        base_branch: str, work_type: str, route: str, created_by: int,
        preset_snapshot: dict | None = None,
        source_repo_id: int | None = None,
    ) -> int:
        now = _now()
        snapshot_json = json.dumps(preset_snapshot) if preset_snapshot else None
        row = await self._pool.fetchrow(
            """INSERT INTO pipeline_runs
               (title, description, repo_id, base_branch, work_branch,
                work_type, route, status, current_step_idx, rollback_count,
                created_by, preset_snapshot, source_repo_id, created_at, updated_at)
               VALUES ($1, $2, $3, $4, '', $5, $6, 'pending', 0, 0, $7, $8, $9, $10, $10)
               RETURNING id""",
            title, description, repo_id, base_branch,
            work_type, route, created_by, snapshot_json, source_repo_id, now,
        )
        run_id = row["id"]
        # If base branch is main/develop, create new work branch.
        # Otherwise work directly in the specified branch.
        protected_branches = {"main", "master", "develop", "development"}
        if base_branch.lower() in protected_branches:
            work_branch = f"foc/run-{run_id}"
        else:
            work_branch = base_branch
        await self._pool.execute(
            "UPDATE pipeline_runs SET work_branch = $1 WHERE id = $2",
            work_branch, run_id,
        )
        return run_id

    async def get_run(self, run_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM pipeline_runs WHERE id = $1", run_id
        )
        if not row:
            return None
        d = dict(row)
        if isinstance(d.get("preset_snapshot"), str):
            d["preset_snapshot"] = json.loads(d["preset_snapshot"])
        return d

    async def list_runs(self, status: str | None = None, repo_id: int | None = None) -> list[dict]:
        conditions = []
        params = []
        idx = 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if repo_id:
            conditions.append(f"repo_id = ${idx}")
            params.append(repo_id)
            idx += 1
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await self._pool.fetch(
            f"SELECT * FROM pipeline_runs{where} ORDER BY id DESC", *params
        )
        return self._records_to_list(rows)

    async def update_run(self, run_id: int, **kwargs) -> None:
        kwargs["updated_at"] = _now()
        sets = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(kwargs))
        vals = list(kwargs.values()) + [run_id]
        await self._pool.execute(
            f"UPDATE pipeline_runs SET {sets} WHERE id = ${len(vals)}", *vals
        )

    async def delete_run(self, run_id: int) -> None:
        await self._pool.execute("DELETE FROM pipeline_runs WHERE id = $1", run_id)

    async def get_runs_with_action(self) -> list[dict]:
        """Get runs that need orchestrator attention."""
        rows = await self._pool.fetch(
            "SELECT * FROM pipeline_runs WHERE orchestrator_action IS NOT NULL ORDER BY id"
        )
        return self._records_to_list(rows)

    async def clear_orchestrator_action(self, run_id: int) -> None:
        await self._pool.execute(
            "UPDATE pipeline_runs SET orchestrator_action = NULL WHERE id = $1", run_id
        )

    async def list_runs_by_status(self, status: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM pipeline_runs WHERE status = $1 ORDER BY id", status
        )
        return self._records_to_list(rows)

    # ── Pipeline Steps ──

    async def create_step(
        self, run_id: int, agent_name: str, agent_number: int,
        step_order: int, attempt: int = 1,
    ) -> int:
        row = await self._pool.fetchrow(
            """INSERT INTO pipeline_steps
               (run_id, agent_name, agent_number, step_order, status, attempt, started_at)
               VALUES ($1, $2, $3, $4, 'running', $5, $6) RETURNING id""",
            run_id, agent_name, agent_number, step_order, attempt, _now(),
        )
        return row["id"]

    async def update_step(self, step_id: int, **kwargs) -> None:
        if "status" in kwargs and kwargs["status"] in ("completed", "failed"):
            kwargs["finished_at"] = _now()
        sets = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(kwargs))
        vals = list(kwargs.values()) + [step_id]
        await self._pool.execute(
            f"UPDATE pipeline_steps SET {sets} WHERE id = ${len(vals)}", *vals
        )

    async def get_steps(self, run_id: int) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM pipeline_steps WHERE run_id = $1 ORDER BY step_order, attempt",
            run_id,
        )
        return self._records_to_list(rows)

    async def get_step(self, step_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM pipeline_steps WHERE id = $1", step_id
        )
        return self._record_to_dict(row)

    async def get_latest_step_for_agent(self, run_id: int, agent_name: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM pipeline_steps WHERE run_id = $1 AND agent_name = $2 "
            "ORDER BY attempt DESC LIMIT 1",
            run_id, agent_name,
        )
        return self._record_to_dict(row)

    # ── Checkpoints ──

    async def create_checkpoint(
        self, run_id: int, step_id: int, agent_name: str, reason: str,
    ) -> int:
        row = await self._pool.fetchrow(
            """INSERT INTO checkpoints (run_id, step_id, agent_name, reason, status, created_at)
               VALUES ($1, $2, $3, $4, 'pending', $5) RETURNING id""",
            run_id, step_id, agent_name, reason, _now(),
        )
        return row["id"]

    async def get_checkpoint(self, checkpoint_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM checkpoints WHERE id = $1", checkpoint_id
        )
        return self._record_to_dict(row)

    async def list_checkpoints(self, run_id: int) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM checkpoints WHERE run_id = $1 ORDER BY id", run_id
        )
        return self._records_to_list(rows)

    async def approve_checkpoint(
        self, checkpoint_id: int, reviewed_by: int, comment: str = "",
    ) -> None:
        await self._pool.execute(
            """UPDATE checkpoints SET status = 'approved', reviewer_comment = $1,
               reviewed_by = $2, reviewed_at = $3 WHERE id = $4""",
            comment, reviewed_by, _now(), checkpoint_id,
        )

    async def reject_checkpoint(
        self, checkpoint_id: int, reviewed_by: int, comment: str = "",
    ) -> None:
        await self._pool.execute(
            """UPDATE checkpoints SET status = 'rejected', reviewer_comment = $1,
               reviewed_by = $2, reviewed_at = $3 WHERE id = $4""",
            comment, reviewed_by, _now(), checkpoint_id,
        )

    async def get_pending_checkpoints(self) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT c.*, r.title as run_title FROM checkpoints c "
            "JOIN pipeline_runs r ON r.id = c.run_id "
            "WHERE c.status = 'pending' ORDER BY c.created_at"
        )
        return self._records_to_list(rows)

    # ── Artifacts ──

    async def create_artifact(
        self, run_id: int, step_id: int, agent_name: str,
        filename: str, file_path: str, git_commit_sha: str | None = None,
        storage_url: str | None = None,
    ) -> int:
        row = await self._pool.fetchrow(
            """INSERT INTO artifacts (run_id, step_id, agent_name, filename, file_path,
               git_commit_sha, storage_url, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
            run_id, step_id, agent_name, filename, file_path, git_commit_sha, storage_url, _now(),
        )
        return row["id"]

    async def get_artifacts(self, run_id: int) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM artifacts WHERE run_id = $1 ORDER BY id", run_id
        )
        return self._records_to_list(rows)

    async def get_artifacts_by_step(self, step_id: int) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM artifacts WHERE step_id = $1 ORDER BY id", step_id
        )
        return self._records_to_list(rows)

    # ── Step Logs ──

    async def append_step_log(self, step_id: int, chunk: str) -> None:
        await self._pool.execute(
            "INSERT INTO step_logs (step_id, chunk, created_at) VALUES ($1, $2, $3)",
            step_id, chunk, _now(),
        )
        # Notify SSE listeners
        await self._pool.execute(
            "SELECT pg_notify('step_log', $1)",
            json.dumps({"step_id": step_id}),
        )

    async def get_step_logs(self, step_id: int) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM step_logs WHERE step_id = $1 ORDER BY id", step_id
        )
        return self._records_to_list(rows)

    async def get_run_log_chunks_since(self, run_id: int, since_id: int = 0) -> list[dict]:
        """Get new step_log entries for a run since a given log ID."""
        rows = await self._pool.fetch(
            """SELECT sl.id, sl.chunk FROM step_logs sl
               JOIN pipeline_steps ps ON ps.id = sl.step_id
               WHERE ps.run_id = $1 AND sl.id > $2 ORDER BY sl.id""",
            run_id, since_id,
        )
        return self._records_to_list(rows)

    async def get_run_logs(self, run_id: int) -> str:
        rows = await self._pool.fetch(
            """SELECT sl.chunk FROM step_logs sl
               JOIN pipeline_steps ps ON ps.id = sl.step_id
               WHERE ps.run_id = $1 ORDER BY sl.id""",
            run_id,
        )
        return "".join(r["chunk"] for r in rows)

    # ── Dashboard Stats ──

    async def get_dashboard_stats(self) -> dict:
        """Aggregate stats for the dashboard."""
        # Run counts by status
        rows = await self._pool.fetch(
            "SELECT status::text, COUNT(*) as cnt FROM pipeline_runs GROUP BY status"
        )
        run_counts = {r["status"]: r["cnt"] for r in rows}
        total_runs = sum(run_counts.values())

        # Work type distribution
        rows = await self._pool.fetch(
            "SELECT work_type::text, COUNT(*) as cnt FROM pipeline_runs GROUP BY work_type"
        )
        work_types = {r["work_type"]: r["cnt"] for r in rows}

        # Per-agent metrics
        rows = await self._pool.fetch("""
            SELECT
                agent_name,
                COUNT(*) as step_count,
                COALESCE(AVG(duration_seconds), 0) as avg_duration,
                COALESCE(SUM(NULLIF(metrics_json->>'cost_usd', '')::float), 0) as total_cost,
                COALESCE(SUM(
                    COALESCE(NULLIF(metrics_json->>'input_tokens', '')::int, 0) +
                    COALESCE(NULLIF(metrics_json->>'output_tokens', '')::int, 0)
                ), 0) as total_tokens,
                COALESCE(SUM(COALESCE(NULLIF(metrics_json->>'tool_calls', '')::int, 0)), 0) as total_tool_calls
            FROM pipeline_steps
            WHERE metrics_json IS NOT NULL AND metrics_json::text != 'null' AND status = 'completed'
            GROUP BY agent_name
            ORDER BY agent_name
        """)
        agents = [
            {
                "name": r["agent_name"],
                "steps": r["step_count"],
                "avg_duration": round(float(r["avg_duration"]), 1),
                "total_cost": round(float(r["total_cost"]), 4),
                "total_tokens": int(r["total_tokens"]),
                "total_tool_calls": int(r["total_tool_calls"]),
            }
            for r in rows
        ]

        # Totals
        total_cost = sum(a["total_cost"] for a in agents)
        total_tokens = sum(a["total_tokens"] for a in agents)
        total_tool_calls = sum(a["total_tool_calls"] for a in agents)

        # Avg run duration (completed runs only)
        row = await self._pool.fetchrow("""
            SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (updated_at - created_at))), 0) as avg_dur
            FROM pipeline_runs WHERE status = 'completed'
        """)
        avg_run_duration = round(float(row["avg_dur"]), 1) if row else 0

        # Total rollbacks
        row = await self._pool.fetchrow(
            "SELECT COALESCE(SUM(rollback_count), 0) as total FROM pipeline_runs"
        )
        total_rollbacks = int(row["total"]) if row else 0

        # Success rate
        completed = run_counts.get("completed", 0)
        success_rate = round((completed / total_runs * 100), 1) if total_runs > 0 else 0

        # Pending checkpoints
        row = await self._pool.fetchrow(
            "SELECT COUNT(*) as cnt FROM checkpoints WHERE status = 'pending'"
        )
        pending_checkpoints = int(row["cnt"]) if row else 0

        # DB size
        row = await self._pool.fetchrow(
            "SELECT pg_database_size(current_database()) as size_bytes"
        )
        db_size_mb = round(int(row["size_bytes"]) / (1024 * 1024), 1) if row else 0

        return {
            "runs": run_counts,
            "total_runs": total_runs,
            "work_types": work_types,
            "agents": agents,
            "totals": {
                "cost_usd": round(total_cost, 4),
                "tokens": total_tokens,
                "tool_calls": total_tool_calls,
            },
            "avg_run_duration": avg_run_duration,
            "total_rollbacks": total_rollbacks,
            "success_rate": success_rate,
            "pending_checkpoints": pending_checkpoints,
            "db_size_mb": db_size_mb,
        }
