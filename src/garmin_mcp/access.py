"""Per-client bearer tokens for the HTTP transport (ADR 0007, #17).

`GARMIN_MCP_CLIENT_TOKENS` holds `name=token` pairs separated by commas, for
example `life-daily-report=<token>,lifeos-sessions=<token>`. When it is set,
each HTTP request must send `Authorization: Bearer <token>`, and the request
is attributed to that client name. `GARMIN_MCP_AUTH=observe` lets requests
without a valid token through and logs them, for rolling the tokens out one
consumer at a time. stdio is not affected.

Logs carry the client name, JSON-RPC method, tool name, the date arguments and
the HTTP status. They never contain tokens or Garmin values.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("garmin_mcp.access")
# Access lines are INFO; the server logs other modules at WARNING.
logger.setLevel(logging.INFO)

MIN_TOKEN_LENGTH = 32
DATE_ARGUMENTS = ("target_date", "start_date", "end_date", "days")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class AccessConfigError(ValueError):
    """The client token configuration is unusable; the server must not start."""


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    tokens: dict[str, str]  # client name -> token
    mode: str  # "off" (no tokens), "observe" or "enforce"

    def client_for(self, token: str | None) -> str | None:
        if not token:
            return None
        match = None
        for name, expected in self.tokens.items():
            # Compare against every token so timing does not reveal which matched.
            if hmac.compare_digest(token.encode(), expected.encode()):
                match = name
        return match


def parse_client_tokens(value: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for item in filter(None, (part.strip() for part in value.split(","))):
        name, sep, token = item.partition("=")
        name, token = name.strip(), token.strip()
        if not sep or not name or not token:
            raise AccessConfigError("GARMIN_MCP_CLIENT_TOKENS entries must look like name=token")
        if len(token) < MIN_TOKEN_LENGTH:
            raise AccessConfigError(f"token for client '{name}' is shorter than {MIN_TOKEN_LENGTH} characters")
        if name in tokens:
            raise AccessConfigError(f"client '{name}' is listed twice")
        if token in tokens.values():
            raise AccessConfigError(f"client '{name}' reuses another client's token")
        tokens[name] = token
    return tokens


def load_policy(environ: dict[str, str] | None = None) -> AccessPolicy:
    env = os.environ if environ is None else environ
    tokens = parse_client_tokens(env.get("GARMIN_MCP_CLIENT_TOKENS", ""))
    requested = (env.get("GARMIN_MCP_AUTH") or "").strip().lower()
    if requested not in ("", "enforce", "observe"):
        raise AccessConfigError("GARMIN_MCP_AUTH must be 'enforce' or 'observe'")
    if not tokens:
        return AccessPolicy({}, "off")
    return AccessPolicy(tokens, requested or "enforce")


def check_bind(host: str, policy: AccessPolicy) -> None:
    """Refuse to listen beyond localhost unless every request needs a token."""
    if host not in LOCAL_HOSTS and policy.mode != "enforce":
        raise AccessConfigError(
            f"refusing to bind {host}: set GARMIN_MCP_CLIENT_TOKENS (enforced) before listening beyond localhost"
        )


def _bearer(scope: dict[str, Any]) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == b"authorization":
            scheme, _, credential = value.decode("latin-1").partition(" ")
            if scheme.lower() == "bearer":
                return credential.strip() or None
    return None


def _describe(body: bytes) -> dict[str, Any]:
    """Method, tool and date arguments of a JSON-RPC request, for the access log."""
    try:
        message = json.loads(body) if body else None
    except (ValueError, UnicodeDecodeError):
        return {"method": "unparsed"}
    if not isinstance(message, dict):
        return {"method": "batch" if isinstance(message, list) else "unknown"}
    info: dict[str, Any] = {"method": message.get("method")}
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if info["method"] == "tools/call":
        info["tool"] = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        dates = {key: arguments[key] for key in DATE_ARGUMENTS if key in arguments}
        if dates:
            info["dates"] = dates
    return info


class ClientAuthMiddleware:
    """ASGI middleware: bearer-token check and one access-log line per request."""

    def __init__(self, app, policy: AccessPolicy):
        self.app = app
        self.policy = policy

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.policy.mode == "off":
            await self.app(scope, receive, send)
            return

        client = self.policy.client_for(_bearer(scope))
        is_post = scope.get("method") == "POST"
        body, receive = await _buffer_body(receive) if is_post else (b"", receive)

        async def send_logged(message):
            # Log when the response starts, before the client can read it.
            if message["type"] == "http.response.start" and (is_post or message["status"] == 401):
                info = _describe(body)
                logger.info(
                    "access client=%s method=%s tool=%s dates=%s status=%s",
                    client or "unauthenticated", info.get("method"), info.get("tool", "-"),
                    json.dumps(info["dates"], sort_keys=True) if "dates" in info else "-", message["status"],
                )
            await send(message)

        if client is None and self.policy.mode == "enforce":
            await _unauthorized(send_logged)
        else:
            await self.app(scope, receive, send_logged)


async def _buffer_body(receive):
    """Read the request body once and replay it to the wrapped app."""
    chunks, more = [], True
    while more:
        message = await receive()
        if message["type"] != "http.request":
            # Client went away before sending the body; pass the event through.
            async def replay_disconnect(message=message):
                return message
            return b"", replay_disconnect
        chunks.append(message.get("body", b""))
        more = message.get("more_body", False)
    body = b"".join(chunks)
    sent = False

    async def replay():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return body, replay


async def _unauthorized(send) -> None:
    payload = json.dumps({"error": "unauthorized", "message": "missing or invalid bearer token"}).encode()
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"www-authenticate", b'Bearer realm="garmin-mcp"'),
            (b"content-length", str(len(payload)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": payload})
