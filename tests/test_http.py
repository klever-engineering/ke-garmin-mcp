"""The HTTP app speaks the protocol both consumers use (#22).

life-daily-report and lifeos-sessions send `initialize` with protocol
version 2025-03-26, keep the `mcp-session-id` header, and read
`structuredContent` from `tools/call`. This runs the real ASGI app under
uvicorn on a free localhost port.
"""
import json
import os
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

os.environ.setdefault("LIFEOS_OTEL_DISABLE_OTLP", "1")

import uvicorn  # noqa: E402

from garmin_mcp import access, mcp_server  # noqa: E402

TOOLS = {
    "garmin_get_day_overview",
    "garmin_list_activities",
    "garmin_get_sleep_range",
    "garmin_get_health_history",
    "garmin_get_calories",
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class HttpServer:
    def __init__(self, app):
        self.port = free_port()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("test server did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"


def post(url, body, session_id=None, headers=None):
    request_headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session_id:
        request_headers["mcp-session-id"] = session_id
    request_headers.update(headers or {})
    request = urllib.request.Request(url, json.dumps(body).encode(), request_headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode()
        data = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
        payload = json.loads(data[-1]) if data else (json.loads(raw) if raw.strip() else None)
        return response.status, response.headers.get("mcp-session-id"), payload


def open_session(url, headers=None):
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}}}
    _, session_id, payload = post(url, init, headers=headers)
    post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id, headers)
    return session_id, payload


class ConsumerProtocolTests(unittest.TestCase):
    def test_initialize_list_and_call_like_the_consumers(self):
        fake = {"ok": True, "calendar_date": "2026-10-25", "wear_data": True}
        with mock.patch.object(mcp_server, "_with_garmin", return_value=fake), \
                HttpServer(mcp_server.build_http_app()) as server:
            session_id, init = open_session(server.url)
            self.assertTrue(session_id)
            self.assertEqual("2025-03-26", init["result"]["protocolVersion"])
            self.assertEqual("lifeos.garmin-mcp", init["result"]["serverInfo"]["name"])

            _, _, listed = post(server.url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session_id)
            self.assertEqual(TOOLS, {tool["name"] for tool in listed["result"]["tools"]})

            call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "garmin_get_day_overview", "arguments": {}}}
            _, _, called = post(server.url, call, session_id)
            self.assertEqual(fake, called["result"]["structuredContent"])


LDR = "l" * 40
SESSIONS = "s" * 40


def policy(mode="enforce"):
    return access.load_policy({"GARMIN_MCP_CLIENT_TOKENS": f"life-daily-report={LDR},lifeos-sessions={SESSIONS}",
                               "GARMIN_MCP_AUTH": mode})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class ClientTokenTests(unittest.TestCase):
    """ADR 0007: per-client bearer tokens on the HTTP transport (#17)."""

    def serve(self, mode="enforce"):
        fake = {"ok": True, "calendar_date": "2026-10-25"}
        patcher = mock.patch.object(mcp_server, "_with_garmin", return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return HttpServer(mcp_server.build_http_app(policy=policy(mode)))

    def status_without(self, url, headers):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            open_session(url, headers)
        return caught.exception

    def test_enforce_rejects_missing_and_wrong_tokens(self):
        with self.serve() as server:
            missing = self.status_without(server.url, {})
            self.assertEqual(401, missing.code)
            self.assertIn("Bearer", missing.headers.get("WWW-Authenticate"))
            self.assertEqual(401, self.status_without(server.url, bearer("x" * 40)).code)

    def test_valid_token_works_and_is_attributed_without_logging_secrets(self):
        with self.serve() as server, self.assertLogs("garmin_mcp.access", "INFO") as logs:
            session_id, init = open_session(server.url, bearer(LDR))
            call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "garmin_get_day_overview", "arguments": {"target_date": "2026-10-24"}}}
            _, _, called = post(server.url, call, session_id, bearer(LDR))
        self.assertEqual("2026-10-25", called["result"]["structuredContent"]["calendar_date"])
        line = next(entry for entry in logs.output if "tools/call" in entry)
        self.assertIn("client=life-daily-report", line)
        self.assertIn("tool=garmin_get_day_overview", line)
        self.assertIn('"target_date": "2026-10-24"', line)
        self.assertIn("status=200", line)
        self.assertFalse(any(LDR in entry or SESSIONS in entry for entry in logs.output))

    def test_observe_mode_lets_unauthenticated_requests_through_and_logs_them(self):
        with self.serve("observe") as server, self.assertLogs("garmin_mcp.access", "INFO") as logs:
            session_id, init = open_session(server.url)
        self.assertTrue(session_id)
        self.assertTrue(any("client=unauthenticated method=initialize" in entry for entry in logs.output))


class RunHttpStartupTests(unittest.TestCase):
    """run_http is what the systemd service executes; start it without a socket."""

    def start(self, env):
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(mcp_server, "load_runtime_env"), \
                mock.patch("uvicorn.run") as run:
            for key in ("GARMIN_MCP_CLIENT_TOKENS", "GARMIN_MCP_AUTH", "GARMIN_MCP_HOST", "FASTMCP_HOST"):
                if key not in env:
                    os.environ.pop(key, None)
            mcp_server.run_http("streamable-http")
        return run.call_args

    def test_starts_without_tokens(self):
        with self.assertLogs(mcp_server.logger, "WARNING") as logs:
            call = self.start({})
        self.assertEqual(("127.0.0.1", 8000), (call.kwargs["host"], call.kwargs["port"]))
        self.assertIn("not set", logs.output[0])

    def test_starts_with_tokens_and_wraps_the_app(self):
        env = {"GARMIN_MCP_CLIENT_TOKENS": f"life-daily-report={LDR}", "GARMIN_MCP_AUTH": "observe"}
        with self.assertLogs(mcp_server.logger, "WARNING") as logs:
            call = self.start(env)
        self.assertIsInstance(call.args[0], access.ClientAuthMiddleware)
        self.assertIn("observed only for: life-daily-report", logs.output[0])
        self.assertNotIn(LDR, logs.output[0])

    def test_refuses_public_bind_without_enforced_tokens(self):
        with self.assertRaises(access.AccessConfigError):
            self.start({"GARMIN_MCP_HOST": "0.0.0.0"})


class AccessConfigTests(unittest.TestCase):
    def test_no_tokens_means_off(self):
        self.assertEqual("off", access.load_policy({}).mode)

    def test_invalid_entries_are_rejected(self):
        for value in ("nameonly", "a=short", f"a={LDR},a={SESSIONS}", f"a={LDR},b={LDR}"):
            with self.subTest(value=value), self.assertRaises(access.AccessConfigError):
                access.parse_client_tokens(value)
        with self.assertRaises(access.AccessConfigError):
            access.load_policy({"GARMIN_MCP_CLIENT_TOKENS": f"a={LDR}", "GARMIN_MCP_AUTH": "maybe"})

    def test_non_local_bind_needs_enforced_tokens(self):
        access.check_bind("127.0.0.1", access.load_policy({}))
        access.check_bind("0.0.0.0", policy("enforce"))
        for mode_policy in (access.load_policy({}), policy("observe")):
            with self.subTest(mode=mode_policy.mode), self.assertRaises(access.AccessConfigError):
                access.check_bind("0.0.0.0", mode_policy)


if __name__ == "__main__":
    unittest.main()
