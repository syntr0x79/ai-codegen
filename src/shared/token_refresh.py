"""OAuth token refresh for Claude Code CLI credentials."""
from __future__ import annotations

import json
import logging
import time
import httpx

logger = logging.getLogger(__name__)

TOKEN_REFRESH_URL = "https://console.anthropic.com/v1/oauth/token"
TOKEN_REFRESH_BUFFER = 300  # Refresh 5 minutes before expiry


async def refresh_token_if_needed(db) -> bool:
    """Check if Claude OAuth token needs refresh, and refresh it.

    Returns True if token is valid (either already valid or refreshed).
    Returns False if refresh failed.
    """
    creds_str = await db.get_setting("claude_credentials")
    if not creds_str:
        return False

    try:
        creds = json.loads(creds_str)
    except json.JSONDecodeError:
        return False

    oauth = creds.get("claudeAiOauth", {})
    access_token = oauth.get("accessToken")
    refresh_token = oauth.get("refreshToken")
    expires_at = oauth.get("expiresAt", 0)

    if not access_token:
        return False

    # Check if token still valid
    now_ms = int(time.time() * 1000)
    if expires_at > now_ms + (TOKEN_REFRESH_BUFFER * 1000):
        return True  # Still valid

    # Need refresh
    if not refresh_token:
        logger.warning("Token expired and no refresh token available")
        return False

    logger.info("Refreshing Claude OAuth token...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                TOKEN_REFRESH_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
                },
            )
            if resp.status_code != 200:
                logger.error(f"Token refresh failed: {resp.status_code} {resp.text[:200]}")
                return False

            data = resp.json()
            new_access = data.get("access_token")
            new_refresh = data.get("refresh_token", refresh_token)
            new_expires = int(time.time() * 1000) + data.get("expires_in", 86400) * 1000

            if not new_access:
                logger.error("Token refresh returned no access_token")
                return False

            # Update credentials
            oauth["accessToken"] = new_access
            oauth["refreshToken"] = new_refresh
            oauth["expiresAt"] = new_expires
            creds["claudeAiOauth"] = oauth

            new_creds_str = json.dumps(creds, indent=2)
            await db.set_setting("claude_credentials", new_creds_str)

            # Write to filesystem
            from src.shared.credentials import write_claude_credentials
            write_claude_credentials(new_creds_str)

            logger.info("Token refreshed successfully")
            return True

    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        return False
