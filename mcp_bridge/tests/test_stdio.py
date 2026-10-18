"""Real MCP stdio integration against a simulated HTTP backend, not backend E2E."""

from __future__ import annotations

import copy
import json
import os
import socket
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from contracts.requests import ContextUpdate, Empty, QueryModule


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "mcp_bridge" / "server.py"
TOKEN = "test-only-relay-token-35b6061a"


@dataclass
class StubReply:
    status: int
    body: Any
    delay: float = 0
    raw: bool = False


class StubState:
    """Test-only backend semantics; never imported by the production adapter."""

    def __init__(self):
        self.bootstrap = json.loads(
            (ROOT / "contracts" / "examples" / "bootstrap.json").read_text(encoding="utf-8")
        )
        self.requests: list[dict[str, Any]] = []
        self.replies: deque[StubReply] = deque()
        self.lock = threading.Lock()

    def reply(self, path: str, authorization: str | None, body: Any) -> StubReply:
        with self.lock:
            self.requests.append({"path": path, "authorization": authorization, "body": body})
            if authorization != f"Bearer {TOKEN}":
                return StubReply(401, {"error": {"code": "unauthorized", "message": "Invalid test token"}})
            routes = {
                "/api/tools/get_my_context",
                "/api/tools/update_my_context",
                "/api/tools/query_module",
            }
            if path not in routes:
                return StubReply(404, {"error": {"code": "unknown_tool", "message": "Invalid test route"}})
            if self.replies:
                return self.replies.popleft()
            if path.endswith("/get_my_context"):
                return StubReply(200, copy.deepcopy(self.bootstrap))
            if path.endswith("/query_module"):
                return StubReply(200, {
                    "contract": copy.deepcopy(self.bootstrap["dependency_contracts"][0]),
                    "query_id": "query_mock_1",
                    "mode": "published_contract",
                    "notice": "Simulated HTTP backend: published contract only.",
                })
            context = self.bootstrap["context"]
            if body["expected_version"] != context["version"]:
                return StubReply(409, {"error": {
                    "code": "version_conflict",
                    "message": "Re-read context before updating",
                    "details": [{"current_version": context["version"]}],
                }})
            updates = {k: v for k, v in body.items() if k != "expected_version" and v is not None}
            if not updates:
                return StubReply(422, {"error": {"code": "invalid_input", "message": "No non-null updates"}})
            context["data"].update(updates)
            context["version"] += 1
            return StubReply(200, copy.deepcopy(context))


@contextmanager
def simulated_backend():
    """Only a test HTTP stub; this does not validate the real backend."""
    state = StubState()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError):
                self.send_error(400)
                return
            # The stub checks the exact route and environment-derived bearer header.
            reply = state.reply(self.path, self.headers.get("Authorization"), body)
            if reply.delay:
                time.sleep(reply.delay)
            payload = (reply.body if reply.raw else json.dumps(reply.body, ensure_ascii=False)).encode("utf-8")
            try:
                self.send_response(reply.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # Expected when the timeout test closes a delayed request.

        def log_message(self, *_args):
            pass  # Never log the Authorization header or request content.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@asynccontextmanager
async def mcp_session(tmp_path: Path, api_url: str, timeout: str = "2"):
    """Launch the real SDK stdio transport from an unrelated working directory."""
    env = dict(os.environ)
    env.update({
        "RELAY_API_URL": api_url,
        "RELAY_TASK_TOKEN": TOKEN,
        "RELAY_HTTP_TIMEOUT_SECONDS": timeout,
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_PROXY": "127.0.0.1,localhost",
    })
    parameters = StdioServerParameters(
        command=sys.executable, args=["-B", str(SERVER)], env=env, cwd=tmp_path
    )
    with (tmp_path / "mcp-stderr.log").open("w", encoding="utf-8") as stderr:
        with anyio.fail_after(30):
            async with stdio_client(parameters, errlog=stderr) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
    assert TOKEN not in (tmp_path / "mcp-stderr.log").read_text(encoding="utf-8")


def payload(result, *, error: str | None = None):
    assert result.isError is (error is not None)
    assert isinstance(result.structuredContent, dict)
    value = result.structuredContent
    texts = [item.text for item in result.content if item.type == "text"]
    assert len(texts) == 1
    assert json.loads(texts[0]) == value
    assert TOKEN not in json.dumps(value, ensure_ascii=False)
    if error is not None:
        assert value["error"]["code"] == error
    return value


def test_stdio_discovery_forwarding_and_context_update_semantics(tmp_path):
    with simulated_backend() as (state, origin):
        async def scenario():
            async with mcp_session(tmp_path, origin + "/") as session:
                discovered = await session.list_tools()
                schemas = {tool.name: tool.inputSchema for tool in discovered.tools}
                assert schemas == {
                    "get_my_context": Empty.model_json_schema(),
                    "update_my_context": ContextUpdate.model_json_schema(),
                    "query_module": QueryModule.model_json_schema(),
                }
                bootstrap = payload(await session.call_tool("get_my_context", {}))
                assert bootstrap == state.bootstrap
                old_summary = bootstrap["context"]["data"]["summary"]
                request = {"expected_version": 1, "summary": None, "next_steps": ""}
                updated = payload(await session.call_tool("update_my_context", request))
                assert updated["version"] == 2
                assert updated["data"]["summary"] == old_summary
                assert updated["data"]["next_steps"] == ""
                assert state.requests[-1]["body"] == request
                assert "todos" not in state.requests[-1]["body"]
                for empty in ({"expected_version": 2}, {"expected_version": 2, "summary": None}):
                    before = len(state.requests)
                    payload(await session.call_tool("update_my_context", empty), error="invalid_input")
                    assert len(state.requests) == before + 1  # Let the backend decide no-op semantics.
                    assert state.requests[-1]["body"] == empty
                    assert state.bootstrap["context"]["version"] == 2
                same_value = {"expected_version": 2, "next_steps": ""}
                assert payload(await session.call_tool("update_my_context", same_value))["version"] == 3
                before = len(state.requests)
                conflict = payload(await session.call_tool("update_my_context", {"expected_version": 2, "summary": "stale"}), error="version_conflict")
                assert conflict["error"]["details"] == [{"current_version": 3}]
                assert len(state.requests) == before + 1  # Never retry a conflicting write.
                assert state.bootstrap["context"]["version"] == 3
                assert state.bootstrap["context"]["data"]["summary"] == old_summary
                queried = payload(await session.call_tool("query_module", {"task_id": "task_api"}))
                assert queried["mode"] == "published_contract"
                assert state.requests[-1]["body"] == {"task_id": "task_api"}
                payload(await session.call_tool("query_module", {"task_id": " task_api ", "question": "   "}))
                assert state.requests[-1]["body"] == {"task_id": "task_api", "question": ""}
                before = len(state.requests)
                payload(await session.call_tool("unknown_tool", {}), error="unknown_tool")
                for tool, arguments in (
                    ("get_my_context", {"task_id": "another_task"}),
                    ("update_my_context", {"expected_version": 3, "role": "admin"}),
                    ("query_module", {"task_id": "task_api", "token": "model-supplied"}),
                    ("update_my_context", {"expected_version": 0, "summary": "invalid version"}),
                ):
                    payload(await session.call_tool(tool, arguments), error="invalid_input")
                assert len(state.requests) == before
                assert all(request["authorization"] == f"Bearer {TOKEN}" for request in state.requests)
                assert all(request["path"].startswith("/api/tools/") for request in state.requests)
        anyio.run(scenario)


def test_stdio_backend_errors_are_visible_redacted_and_recoverable(tmp_path):
    with simulated_backend() as (state, origin):
        async def scenario():
            async with mcp_session(tmp_path, origin) as session:
                for status, code in ((401, "unauthorized"), (403, "forbidden"), (500, "internal_error")):
                    state.replies.append(StubReply(status, {"error": {
                        "code": code, "message": f"Mock failure {TOKEN}",
                        "details": [{"hint": f"Never echo {TOKEN}"}],
                    }}))
                    before = len(state.requests)
                    failure = payload(await session.call_tool("get_my_context", {}), error=code)
                    assert failure["error"]["message"].startswith("Mock failure")
                    assert failure["error"]["details"][0]["hint"].startswith("Never echo")
                    assert len(state.requests) == before + 1
                    assert payload(await session.call_tool("get_my_context", {}))["task"]["task_id"] == "task_form"
                for reply in (StubReply(200, ["unexpected array"]), StubReply(200, "not-json", raw=True)):
                    state.replies.append(reply)
                    payload(await session.call_tool("get_my_context", {}), error="invalid_backend_response")
                    payload(await session.call_tool("get_my_context", {}))
        anyio.run(scenario)


def test_stdio_real_connection_failure_is_recoverable(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        listener.settimeout(0.2)
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        stopped = threading.Event()

        def disconnect_requests():
            while not stopped.is_set():
                try:
                    connection, _address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                with connection:
                    connection.settimeout(1)
                    try:
                        connection.recv(65536)
                    except (OSError, socket.timeout):
                        pass
                # Deliberately disconnect after accepting HTTP, without a response.
                # This exercises a real RequestError consistently on Windows.

        thread = threading.Thread(target=disconnect_requests, daemon=True)
        thread.start()
        async def scenario():
            async with mcp_session(tmp_path, origin) as session:
                payload(await session.call_tool("get_my_context", {}), error="backend_unreachable")
                payload(await session.call_tool("get_my_context", {}), error="backend_unreachable")
                assert len((await session.list_tools()).tools) == 3
        try:
            anyio.run(scenario)
        finally:
            stopped.set()
            thread.join(timeout=2)


def test_stdio_real_http_timeout_does_not_retry_or_kill_session(tmp_path):
    with simulated_backend() as (state, origin):
        state.replies.append(StubReply(200, {"late": True}, delay=0.6))
        async def scenario():
            async with mcp_session(tmp_path, origin, timeout="0.15") as session:
                payload(await session.call_tool("get_my_context", {}), error="backend_timeout")
                assert len(state.requests) == 1
                payload(await session.call_tool("get_my_context", {}))
                assert len(state.requests) == 2
        anyio.run(scenario)
