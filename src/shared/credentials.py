"""Shared credential management -- write/restore credentials from DB to filesystem."""
from __future__ import annotations

import json
import os


def _write_file(filename: str, content: str, subdir: str, mode: int = 0o600) -> None:
    """Write a file to ~/subdir/filename with given permissions."""
    home = os.path.expanduser("~")
    target_dir = os.path.join(home, subdir)
    os.makedirs(target_dir, exist_ok=True)
    filepath = os.path.join(target_dir, filename)
    with open(filepath, "w") as f:
        f.write(content)
    os.chmod(filepath, mode)


def write_claude_credentials(creds_json_str: str) -> None:
    """Write credentials JSON to ~/.claude/.credentials.json."""
    _write_file(".credentials.json", creds_json_str, ".claude")
    # Ensure .claude.json exists
    home = os.path.expanduser("~")
    claude_json_path = os.path.join(home, ".claude.json")
    if not os.path.exists(claude_json_path):
        with open(claude_json_path, "w") as f:
            json.dump({"numStartups": 1}, f)


def write_ssh_key(key: str) -> None:
    """Write SSH private key to ~/.ssh/id_agent."""
    _write_file("id_agent", key, ".ssh")


def write_kubeconfig(config: str) -> None:
    """Write kubeconfig to ~/.kube/config."""
    _write_file("config", config, ".kube")


async def restore_all_credentials(db_get_setting) -> None:
    """Restore all credentials from DB settings to filesystem."""
    claude_creds = await db_get_setting("claude_credentials")
    if claude_creds:
        write_claude_credentials(claude_creds)

    ssh_key = await db_get_setting("ssh_private_key")
    if ssh_key:
        write_ssh_key(ssh_key)

    kubeconfig = await db_get_setting("kubeconfig")
    if kubeconfig:
        write_kubeconfig(kubeconfig)
