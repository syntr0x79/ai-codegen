from __future__ import annotations

import asyncio
from pathlib import Path

ARTIFACT_DIR = ".factory"


def artifact_path(repo_dir: Path, filename: str) -> Path:
    """Get the full path to an artifact file in the repo."""
    return repo_dir / ARTIFACT_DIR / filename


def read_artifact(repo_dir: Path, filename: str) -> str | None:
    """Read an artifact file from the repo. Returns None if not found."""
    path = artifact_path(repo_dir, filename)
    if path.exists():
        return path.read_text()
    return None


def list_artifacts(repo_dir: Path) -> list[str]:
    """List all artifact filenames in the .factory/ directory."""
    factory_dir = repo_dir / ARTIFACT_DIR
    if not factory_dir.exists():
        return []
    results = []
    for p in sorted(factory_dir.rglob("*")):
        if p.is_file():
            results.append(str(p.relative_to(factory_dir)))
    return results


def ensure_artifact_dir(repo_dir: Path) -> Path:
    """Create the .factory/ directory if it doesn't exist."""
    factory_dir = repo_dir / ARTIFACT_DIR
    factory_dir.mkdir(parents=True, exist_ok=True)
    return factory_dir


async def commit_artifacts(
    repo_dir: Path, agent_name: str, filenames: list[str],
) -> str | None:
    """
    Git add and commit artifact files produced by an agent.
    Returns the commit SHA, or None if nothing to commit.
    """
    if not filenames:
        return None

    # Stage artifact files
    paths_to_add = []
    for fn in filenames:
        path = artifact_path(repo_dir, fn)
        if path.exists():
            paths_to_add.append(str(path.relative_to(repo_dir)))

    if not paths_to_add:
        return None

    # Also stage any code changes (for implementation agent)
    # We do git add -A for code, but explicitly add .factory/ files
    proc = await asyncio.create_subprocess_exec(
        "git", "add", *paths_to_add,
        cwd=repo_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    # Check if there's anything to commit
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--cached", "--quiet",
        cwd=repo_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode == 0:
        return None  # Nothing staged

    # Commit
    files_desc = ", ".join(filenames)
    msg = f"[factory] {agent_name}: {files_desc}"
    proc = await asyncio.create_subprocess_exec(
        "git", "commit", "-m", msg,
        cwd=repo_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode != 0:
        return None

    # Get commit SHA
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD",
        cwd=repo_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip() if proc.returncode == 0 else None


async def commit_all_changes(repo_dir: Path, agent_name: str) -> str | None:
    """
    Git add -A and commit all changes (code + artifacts).
    Used after the implementation agent which modifies code files.
    """
    proc = await asyncio.create_subprocess_exec(
        "git", "add", "-A",
        cwd=repo_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    # Check if there's anything to commit
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--cached", "--quiet",
        cwd=repo_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode == 0:
        return None

    proc = await asyncio.create_subprocess_exec(
        "git", "commit", "-m", f"[factory] {agent_name}: implementation changes",
        cwd=repo_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode != 0:
        return None

    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD",
        cwd=repo_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip() if proc.returncode == 0 else None
