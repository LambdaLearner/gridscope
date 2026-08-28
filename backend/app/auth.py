"""Opt-in bearer-token authentication for the whole API surface.

When GRIDSCOPE_API_TOKEN is set, every HTTP request — including /docs,
/openapi.json, and the SSE stream from /api/execute/run — must carry a
matching ``Authorization: Bearer <token>`` header; anything else gets 401.
When the variable is unset the API is open, and the loopback-only default
bind (see run.py) is the security boundary.

Pure ASGI middleware rather than BaseHTTPMiddleware so streaming responses
pass through untouched. The token is read per request, so tests can toggle
it and import order relative to load_dotenv() doesn't matter. CORS
preflight (OPTIONS) never reaches this middleware: CORSMiddleware is
mounted outermost (see main.py) and answers preflights itself, which is
required because browsers send preflights without Authorization headers.
"""

import json
import os
import secrets

TOKEN_ENV_VAR = "GRIDSCOPE_API_TOKEN"
UNAUTHORIZED_DETAIL = (
    "Missing or invalid API token. Send 'Authorization: Bearer <token>' "
    f"matching the server's {TOKEN_ENV_VAR}."
)


class BearerTokenAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        expected = os.getenv(TOKEN_ENV_VAR)
        if expected and not _authorized(scope, expected):
            await _send_401(send)
            return

        await self.app(scope, receive, send)


def _authorized(scope, expected: str) -> bool:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            if scheme.lower() != "bearer":
                return False
            # compare_digest on bytes: constant-time, and safe even if a
            # client sends non-ASCII garbage in the header.
            return secrets.compare_digest(
                token.strip().encode("utf-8"), expected.encode("utf-8")
            )
    return False


async def _send_401(send):
    body = json.dumps({"detail": UNAUTHORIZED_DETAIL}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
