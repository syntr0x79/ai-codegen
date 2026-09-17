from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable

from src.pipeline.artifacts import read_artifact

# Registry of running processes for cancellation
_running_processes: dict[int, asyncio.subprocess.Process] = {}


def register_process(task_id: int, process: asyncio.subprocess.Process) -> None:
    _running_processes[task_id] = process


def unregister_process(task_id: int) -> None:
    _running_processes.pop(task_id, None)


def kill_process(task_id: int) -> None:
    proc = _running_processes.pop(task_id, None)
    if proc and proc.returncode is None:
        proc.terminate()


def build_prompt(
    agent_name: str,
    repo_dir: Path,
    task_description: str = "",
    config: dict | None = None,
    run_context: dict | None = None,
    prompts_dir: Path | None = None,
    repo_context: str = "",
    default_prompt: str | None = None,
) -> str:
    """Build prompt for any of the 8 agents.

    Priority for system prompt:
    1. Preset override (config["system_prompt"])
    2. DB default prompt (default_prompt)
    3. File fallback (prompts_dir / agent_name.md)

    repo_context is injected into every agent as project context.
    """
    parts = []

    # 1. Load system prompt: preset override > DB default > file
    if config and config.get("system_prompt"):
        parts.append(config["system_prompt"])
    elif default_prompt:
        parts.append(default_prompt)
    elif prompts_dir:
        prompt_file = prompts_dir / f"{agent_name}.md"
        if prompt_file.exists():
            parts.append(prompt_file.read_text())

    # Language instruction
    parts.append("\n## ВАЖНО: Язык\n\nВесь вывод, артефакты, комментарии и документация должны быть на русском языке.\n")

    # 1b. Inject repo context (tech standards, conventions)
    if repo_context:
        parts.append(f"\n## Контекст проекта\n\n{repo_context}")

    # 2. Inject task description for ALL agents
    if task_description:
        parts.append(f"\n## Задача\n\n{task_description}")

    # 3. Inject artifacts that this agent should read
    if config:
        artifacts_to_read = config.get("artifacts_read", [])
        for artifact_name in artifacts_to_read:
            content = read_artifact(repo_dir, artifact_name)
            if content:
                parts.append(f"\n## Артефакт: {artifact_name}\n\n```\n{content}\n```")

    # 4. Inject run context (rollback info, iteration, etc.)
    if run_context:
        ctx_parts = []
        if run_context.get("rollback_count", 0) > 0:
            ctx_parts.append(
                f"Это повторная попытка #{run_context['rollback_count']}. "
                "Предыдущие попытки провалились. Проверь .factory/evidence.md и "
                ".factory/regression-matrix.md для деталей ошибок."
            )
        if run_context.get("work_type"):
            ctx_parts.append(f"Тип работы: {run_context['work_type']}")
        if run_context.get("risk_level"):
            ctx_parts.append(f"Уровень риска: {run_context['risk_level']}")
        if ctx_parts:
            parts.append("\n## Контекст запуска\n\n" + "\n".join(ctx_parts))

    # 5. Inject contracts directory listing for agents that need it
    if agent_name in ("implementation", "test_contract"):
        contracts_dir = repo_dir / ".factory" / "contracts"
        if contracts_dir.exists():
            contract_files = sorted(contracts_dir.glob("*.md"))
            if contract_files:
                parts.append("\n## Контракты\n")
                for cf in contract_files:
                    parts.append(f"\n### {cf.name}\n\n```\n{cf.read_text()}\n```")

    return "\n".join(parts)


def parse_verdict(agent_name: str, output: str, repo_dir: Path) -> str | None:
    """Parse the agent's verdict from its output or artifact files.

    Returns the verdict string or None if this agent doesn't produce verdicts.
    """
    if agent_name == "orchestrator":
        # Parse work_type from routing.yaml
        content = read_artifact(repo_dir, "routing.yaml")
        if content:
            import yaml
            try:
                data = yaml.safe_load(content)
                return data.get("work_type")
            except Exception:
                pass
        return None

    if agent_name == "architecture_mapper":
        # Parse risk_level from impact-map.md
        content = read_artifact(repo_dir, "impact-map.md")
        if content:
            for line in reversed(content.strip().split("\n")):
                if line.strip().startswith("RISK_LEVEL:"):
                    return line.split(":", 1)[1].strip()
        return None

    if agent_name == "test_contract":
        content = read_artifact(repo_dir, "contract-verdict.json")
        if content:
            try:
                data = json.loads(content)
                return data.get("overall", "FAIL")
            except Exception:
                pass
        return "FAIL"

    if agent_name == "verification":
        content = read_artifact(repo_dir, "verdict.json")
        if content:
            try:
                data = json.loads(content)
                return data.get("verdict", "FAIL_TEST")
            except Exception:
                pass
        return "FAIL_TEST"

    if agent_name == "security_policy":
        content = read_artifact(repo_dir, "policy-verdict.json")
        if content:
            try:
                data = json.loads(content)
                return data.get("verdict", "REQUIRES_HUMAN")
            except Exception:
                pass
        return "REQUIRES_HUMAN"

    return None


def _parse_stream_metrics(output_lines: list[str]) -> dict:
    """Parse NDJSON stream-json output for metrics (usage, tool calls, files)."""
    input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0
    tool_calls = 0
    files_changed: list[str] = []

    for line in output_lines:
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue

        obj_type = obj.get("type", "")

        if obj_type == "assistant":
            msg = obj.get("message", {})
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls += 1
                    tool_name = block.get("name", "")
                    tool_input = block.get("input", {})
                    if isinstance(tool_input, dict) and tool_name in ("Write", "Edit"):
                        fp = tool_input.get("file_path", "")
                        if fp and fp not in files_changed:
                            files_changed.append(fp)

        if obj_type == "result":
            cost_usd = obj.get("total_cost_usd", 0.0)
            usage = obj.get("usage", {})
            input_tokens = (
                usage.get("input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
            )
            output_tokens = usage.get("output_tokens", 0)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "tool_calls": tool_calls,
        "files_changed": files_changed,
    }


def _format_stream_line(line: str) -> str | None:
    """Parse a stream-json line and return human-readable text, or None to skip."""
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None

    obj_type = obj.get("type", "")

    if obj_type == "assistant":
        msg = obj.get("message", {})
        content = msg.get("content", [])
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block["text"])
        if texts:
            return "\n".join(texts)

    elif obj_type == "tool_use":
        tool = obj.get("tool_name", "unknown")
        inp = obj.get("input", {})
        if isinstance(inp, dict):
            if tool in ("Read", "Glob", "Grep"):
                target = inp.get("file_path") or inp.get("pattern") or inp.get("path", "")
                return f"  -> {tool}: {target}"
            elif tool in ("Write", "Edit"):
                return f"  -> {tool}: {inp.get('file_path', '')}"
            elif tool == "Bash":
                cmd = inp.get("command", "")
                if len(cmd) > 80:
                    cmd = cmd[:80] + "..."
                return f"  -> Bash: {cmd}"
            else:
                return f"  -> {tool}"
        return f"  -> {tool}"

    elif obj_type == "result":
        cost = obj.get("total_cost_usd", 0)
        duration = obj.get("duration_ms", 0)
        if duration:
            return f"  Done ({duration/1000:.0f}s, ${cost:.4f})"

    return None


async def run_agent(
    agent_name: str,
    repo_dir: Path,
    run_id: int,
    config: dict,
    task_description: str = "",
    run_context: dict | None = None,
    prompts_dir: Path | None = None,
    on_output: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    """Run a Claude Code agent and return its output, verdict, and metrics."""
    prompt = build_prompt(
        agent_name, repo_dir, task_description,
        config, run_context, prompts_dir,
        repo_context=config.get("_repo_context", ""),
        default_prompt=config.get("_default_prompt"),
    )

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--model", config.get("model", "claude-sonnet-4-6"),
        "--max-turns", str(config.get("max_turns", 10)),
    ]

    for tool in config.get("allowed_tools", []):
        cmd.extend(["--allowedTools", tool])

    timeout = config.get("timeout", 600)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=repo_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024,
    )
    register_process(run_id, process)

    output_lines = []
    stderr_lines = []
    try:
        async def read_stdout():
            async for line in process.stdout:
                decoded = line.decode().strip()
                if decoded:
                    output_lines.append(decoded)
                    if on_output:
                        formatted = _format_stream_line(decoded)
                        if formatted:
                            await on_output(formatted)

        async def read_stderr():
            async for line in process.stderr:
                stderr_lines.append(line.decode().strip())

        await asyncio.wait_for(
            asyncio.gather(read_stdout(), read_stderr()),
            timeout=timeout,
        )
        await process.wait()
    except asyncio.TimeoutError:
        process.terminate()
        await process.wait()
        raise RuntimeError(f"Agent {agent_name} timed out after {timeout}s")
    finally:
        unregister_process(run_id)

    full_output = "\n".join(output_lines)

    if process.returncode != 0:
        stderr = "\n".join(stderr_lines)
        raise RuntimeError(f"Agent {agent_name} failed (exit {process.returncode}): {stderr}")

    metrics = _parse_stream_metrics(output_lines)
    verdict = parse_verdict(agent_name, full_output, repo_dir)

    return {
        "output": full_output,
        "verdict": verdict,
        "metrics": metrics,
    }
