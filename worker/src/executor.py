"""Worker job executor: clone → run agent → commit → upload artifacts."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path

from src.db import Database


def _extract_text_from_stream(raw_output: str) -> str:
    """Extract human-readable text from NDJSON stream-json output."""
    texts = []
    for line in raw_output.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if obj.get("type") == "assistant":
            for block in obj.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block["text"])
    return "\n\n".join(texts) if texts else ""


from src.pipeline.agent import run_agent
from src.pipeline.artifacts import ensure_artifact_dir, list_artifacts, commit_all_changes
from src.pipeline.git import get_diff
from src.shared.minio_client import MinIOClient
from src.shared.models import JobMessage, ResultMessage

logger = logging.getLogger(__name__)


class JobExecutor:
    def __init__(self, db: Database, minio: MinIOClient | None, work_dir: Path):
        self.db = db
        self.minio = minio
        self.work_dir = work_dir
        self._current_run_id: int | None = None

    @property
    def current_run_id(self) -> int | None:
        return self._current_run_id

    def cancel_current(self):
        """Cancel current agent if running."""
        from src.pipeline.agent import kill_process
        if self._current_run_id:
            kill_process(self._current_run_id)
            logger.info(f"Terminated agent for run {self._current_run_id}")

    async def execute(self, job: JobMessage) -> ResultMessage:
        """Execute a single agent step.

        Repo is stored at work_dir/runs/{run_id}/ (shared volume).
        Clone only on first step. Push only on final step.
        Artifacts always go to MinIO.
        """
        self._current_run_id = job.run_id
        repo_dir = self.work_dir / "runs" / str(job.run_id)
        source_dir = self.work_dir / "runs" / f"{job.run_id}_source"
        started_at = time.time()

        try:
            await self.db.update_step(job.step_id, status="running")

            # ── Clone repo (only if not yet cloned) ──
            if not repo_dir.exists():
                repo_dir.parent.mkdir(parents=True, exist_ok=True)
                await self._run_cmd(["git", "clone", job.repo_url, str(repo_dir)])

                if job.work_branch == job.base_branch:
                    # Working directly in existing branch (not main/develop)
                    await self._run_cmd(["git", "checkout", job.work_branch], cwd=repo_dir)
                else:
                    # Create new branch from base (main/develop)
                    try:
                        await self._run_cmd(["git", "checkout", job.work_branch], cwd=repo_dir)
                    except RuntimeError:
                        await self._run_cmd(["git", "checkout", job.base_branch], cwd=repo_dir)
                        await self._run_cmd(["git", "checkout", "-b", job.work_branch], cwd=repo_dir)

                logger.info(f"Cloned repo for run {job.run_id}, branch: {job.work_branch}")

            ensure_artifact_dir(repo_dir)

            # Snapshot existing .factory/ files BEFORE agent runs (inputs from previous steps)
            factory_dir = repo_dir / ".factory"
            pre_existing = set(
                str(f.relative_to(factory_dir))
                for f in factory_dir.rglob("*") if f.is_file()
            ) if factory_dir.exists() else set()

            # ── Download input artifacts from MinIO ──
            if self.minio and job.artifact_inputs:
                factory_dir = repo_dir / ".factory"
                for artifact_name in job.artifact_inputs:
                    try:
                        content = self.minio.download_text(job.run_id, artifact_name)
                        if content:
                            artifact_path = factory_dir / artifact_name
                            artifact_path.parent.mkdir(parents=True, exist_ok=True)
                            artifact_path.write_text(content)
                    except Exception as e:
                        logger.warning(f"Failed to download artifact {artifact_name}: {e}")

            # Update pre_existing after downloads
            pre_existing = set(
                str(f.relative_to(factory_dir))
                for f in factory_dir.rglob("*") if f.is_file()
            ) if factory_dir.exists() else set()

            # ── Clone source repo for transformation (only once) ──
            if job.source_repo_url and not source_dir.exists():
                try:
                    await self._run_cmd(["git", "clone", job.source_repo_url, str(source_dir)])
                    # Remove remote to prevent accidental push to source
                    await self._run_cmd(["git", "remote", "remove", "origin"], cwd=source_dir)

                    # If target repo is empty, copy source code into it
                    target_files = [f for f in repo_dir.iterdir() if f.name not in ('.git', '.factory')]
                    if len(target_files) <= 1:  # Only README or nothing
                        await self.db.append_step_log(
                            job.step_id, "Target repo is empty, copying source code...\n"
                        )
                        await self._run_cmd([
                            "bash", "-c",
                            f"cp -a {source_dir}/. {repo_dir}/ 2>/dev/null; "
                            f"rm -rf {repo_dir}/.git/; "
                            f"cd {repo_dir} && git init && git add -A && "
                            f"git commit -m 'chore: import source code for transformation'"
                        ], cwd=repo_dir)
                        # Re-setup git remote and branch
                        await self._run_cmd(["git", "remote", "add", "origin", job.repo_url], cwd=repo_dir)
                        await self._run_cmd(["git", "checkout", "-b", job.work_branch], cwd=repo_dir)
                        logger.info("Copied source code into target repo")
                except Exception as e:
                    await self.db.append_step_log(
                        job.step_id, f"[WARNING] Source repo clone failed: {e}\n"
                    )

            # ── Build agent config ──
            config = dict(job.agent_config)
            if job.artifact_inputs and not config.get("artifacts_read"):
                config["artifacts_read"] = job.artifact_inputs
            if source_dir.exists():
                ctx = config.get("_repo_context", "")
                config["_repo_context"] = (
                    ctx +
                    f"\n\nИсходный репозиторий для анализа: {source_dir}\n"
                    f"Используй Read/Glob/Grep для чтения файлов оттуда.\n"
                    f"ВАЖНО: Все изменения пиши ТОЛЬКО в текущую рабочую директорию ({repo_dir})!"
                )

            # ── Log phase marker ──
            await self.db.append_step_log(
                job.step_id, f"--- {job.agent_name} (step {job.step_order}) ---\n"
            )

            async def on_output(line: str):
                await self.db.append_step_log(job.step_id, line + "\n")

            # ── Run agent ──
            result = await run_agent(
                agent_name=job.agent_name,
                repo_dir=repo_dir,
                run_id=job.run_id,
                config=config,
                task_description=job.task_description,
                run_context=job.run_context,
                prompts_dir=Path(__file__).parent.parent.parent / "src" / "prompts",
                on_output=on_output,
            )

            duration = time.time() - started_at
            output_text = result.get("output", "")
            verdict = result.get("verdict")
            metrics = result.get("metrics", {})

            # ── Fallback: save agent text as artifact if no .factory/ files created ──
            factory_dir = repo_dir / ".factory"
            factory_files = [f for f in factory_dir.rglob("*") if f.is_file()] if factory_dir.exists() else []
            if not factory_files and output_text:
                ensure_artifact_dir(repo_dir)
                readable = _extract_text_from_stream(output_text)
                if readable:
                    fallback_name = f"{job.agent_name}-output.md"
                    (factory_dir / fallback_name).write_text(readable[:50000])

            # ── Git commit (local only, no push) ──
            commit_sha = await commit_all_changes(repo_dir, job.agent_name)

            # ── Push only on final step ──
            if job.is_final_step:
                try:
                    await self._run_cmd(
                        ["git", "push", "origin", job.work_branch], cwd=repo_dir
                    )
                    logger.info(f"Pushed branch {job.work_branch} for run {job.run_id}")
                except Exception as e:
                    logger.warning(f"Git push failed: {e}")
                    await self.db.append_step_log(
                        job.step_id, f"[WARNING] Git push failed: {e}\n"
                    )

            # ── Determine NEW artifacts (created by this agent, not downloaded) ──
            all_produced = set(list_artifacts(repo_dir))
            new_artifacts = all_produced - pre_existing

            # ── Upload only new artifacts to MinIO ──
            uploaded = []
            if self.minio and new_artifacts:
                for fn in new_artifacts:
                    fpath = factory_dir / fn
                    if fpath.exists():
                        try:
                            self.minio.upload_file(job.run_id, fn, fpath)
                            uploaded.append(fn)
                        except Exception as e:
                            logger.warning(f"MinIO upload {fn} failed: {e}")

                # Upload diff on final step
                if job.is_final_step:
                    try:
                        diff_text = await get_diff(repo_dir, job.base_branch)
                        if diff_text:
                            self.minio.upload_diff(job.run_id, diff_text)
                    except Exception:
                        pass

            # ── Record only NEW artifacts in DB ──
            for fn in new_artifacts:
                storage_url = None
                if self.minio and fn in uploaded:
                    storage_url = f"minio://{self.minio.bucket}/runs/{job.run_id}/artifacts/{fn}"
                await self.db.create_artifact(
                    job.run_id, job.step_id, job.agent_name, fn,
                    f".factory/{fn}", commit_sha, storage_url,
                )

            # ── Cleanup repo on final step ──
            if job.is_final_step:
                if repo_dir.exists():
                    await asyncio.to_thread(shutil.rmtree, repo_dir, ignore_errors=True)
                if source_dir.exists():
                    await asyncio.to_thread(shutil.rmtree, source_dir, ignore_errors=True)

            # ── Update step ──
            await self.db.update_step(
                job.step_id,
                status="completed",
                output_summary=output_text[:5000],
                verdict=verdict,
                duration_seconds=duration,
                metrics_json=json.dumps(metrics) if metrics else None,
            )

            return ResultMessage(
                job_id=job.job_id,
                run_id=job.run_id,
                step_id=job.step_id,
                agent_name=job.agent_name,
                status="completed",
                verdict=verdict,
                output_summary=output_text[:5000],
                metrics=metrics,
                duration_seconds=duration,
                commit_sha=commit_sha,
                artifacts_uploaded=uploaded,
            )

        except Exception as e:
            duration = time.time() - started_at
            logger.exception(f"Job {job.job_id} failed: {e}")
            await self.db.update_step(
                job.step_id, status="failed",
                output_summary=str(e)[:5000],
                duration_seconds=duration,
            )
            return ResultMessage(
                job_id=job.job_id,
                run_id=job.run_id,
                step_id=job.step_id,
                agent_name=job.agent_name,
                status="failed",
                error=str(e)[:500],
                duration_seconds=duration,
            )

        finally:
            self._current_run_id = None

    async def _run_cmd(self, cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Command {cmd[:3]} timed out after {timeout}s")
        if proc.returncode != 0:
            raise RuntimeError(f"Command {cmd[:3]} failed: {stderr.decode()[:500]}")
        return stdout.decode()
