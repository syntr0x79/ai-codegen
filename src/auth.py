from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from base64 import b64decode, b64encode

import bcrypt
from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

PUBLIC_PATHS = {"/login", "/auth/login", "/health"}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_session_cookie(user_id: int, username: str, secret: str) -> str:
    payload = json.dumps({"user_id": user_id, "username": username, "ts": int(time.time())})
    encoded = b64encode(payload.encode()).decode()
    sig = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{sig}"


def decode_session_cookie(cookie: str, secret: str) -> dict | None:
    try:
        encoded, sig = cookie.rsplit(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return json.loads(b64decode(encoded))
    except Exception:
        return None


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret: str):
        super().__init__(app)
        self.secret = secret

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        cookie = request.cookies.get("session")
        session = decode_session_cookie(cookie, self.secret) if cookie else None

        if not session:
            return RedirectResponse("/login", status_code=303)

        request.state.user = session
        return await call_next(request)
