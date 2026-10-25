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

from garmin_mcp import mcp_server  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
