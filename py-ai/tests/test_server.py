"""Tests for ulysses_ai.server — JSON-RPC 2.0 server over stdio.

Follows TDD: each test is written BEFORE the corresponding implementation.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from ulysses_ai.protocol import (
    AUTH_ERROR,
    API_TIMEOUT,
    JSONRPCErrorResponse,
    JSONRPCException,
    JSONRPCResponse,
    INVALID_REQUEST,
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    RATE_LIMIT_EXCEEDED,
)
from ulysses_ai.server import RPCServer


# =============================================================================
# Helpers
# =============================================================================


def make_request(id_: int, method: str, params: dict | None = None) -> str:
    """Build a JSON-RPC 2.0 request string."""
    req = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        req["params"] = params
    return json.dumps(req)


def make_notification(method: str, params: dict | None = None) -> str:
    """Build a JSON-RPC 2.0 notification string (no id)."""
    notif = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        notif["params"] = params
    return json.dumps(notif)


async def ping_handler(params: dict | None = None) -> str:
    """Health check handler — returns 'pong'."""
    return "pong"


def create_server_with_ping() -> RPCServer:
    """Create a server with the ping handler registered."""
    server = RPCServer()
    server.register("ping", ping_handler)
    return server


# =============================================================================
# Round 1: Ping request-response round trip
# =============================================================================


class TestPingRoundTrip:
    """Tests for the basic ping → pong request-response cycle."""

    def test_ping_returns_pong(self, capsys):
        """Sending a ping request returns a pong response."""
        server = create_server_with_ping()
        line = make_request(1, "ping", {})

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["result"] == "pong"

    def test_ping_response_has_no_error_field(self, capsys):
        """A successful ping response must NOT contain an error field."""
        server = create_server_with_ping()
        line = make_request(1, "ping")

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert "error" not in response
        assert "result" in response


# =============================================================================
# Round 2: Parse Error for invalid JSON
# =============================================================================


class TestParseError:
    """Tests for parse error handling when input is not valid JSON."""

    def test_invalid_json_returns_parse_error(self, capsys):
        """Sending non-JSON input returns a Parse Error (-32700) with null id."""
        server = create_server_with_ping()
        line = "this is not json"

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert response["jsonrpc"] == "2.0"
        assert response["id"] is None
        assert response["error"]["code"] == PARSE_ERROR
        assert "error" in response
        assert "result" not in response


# =============================================================================
# Round 3: Method Not Found error
# =============================================================================


class TestMethodNotFound:
    """Tests for method-not-found error when no handler is registered."""

    def test_unknown_method_returns_method_not_found(self, capsys):
        """Request with unregistered method returns Method Not Found (-32601)."""
        server = create_server_with_ping()
        line = make_request(2, "unknown_method", {})

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 2
        assert response["error"]["code"] == METHOD_NOT_FOUND
        assert "result" not in response


# =============================================================================
# Round 4: Handler exception → Internal Error
# =============================================================================


class TestInternalError:
    """Tests for internal error when a handler raises an exception."""

    def test_handler_exception_returns_internal_error(self, capsys):
        """Handler that raises an exception returns Internal Error (-32603)."""
        async def faulty_handler(params: dict | None = None) -> str:
            raise ValueError("something went wrong")

        server = RPCServer()
        server.register("faulty", faulty_handler)
        line = make_request(3, "faulty")

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 3
        assert response["error"]["code"] == INTERNAL_ERROR


# =============================================================================
# Round 5: Notification handling (no id messages)
# =============================================================================


class TestNotificationHandling:
    """Tests that notifications (no id) dispatch to handlers without response."""

    def test_notification_dispatches_to_handler(self, capsys):
        """A valid notification calls the handler but writes nothing to stdout."""
        received_params = []

        async def notif_handler(params: dict | None = None) -> None:
            received_params.append(params)

        server = RPCServer()
        server.register("stream/message_stop", notif_handler)
        line = make_notification("stream/message_stop", {"request_id": 3})

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        # Notification → no response written to stdout
        assert captured.out.strip() == ""
        # Handler must have been called
        assert len(received_params) == 1
        assert received_params[0] == {"request_id": 3}

    def test_notification_does_not_write_to_stdout(self, capsys):
        """Multiple notifications produce no stdout output."""
        call_count = 0

        async def counting_handler(params: dict | None = None) -> None:
            nonlocal call_count
            call_count += 1

        server = RPCServer()
        server.register("stream/ping", counting_handler)

        for i in range(3):
            line = make_notification("stream/ping", {"seq": i})
            asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        assert captured.out.strip() == ""
        assert call_count == 3

    def test_notification_with_invalid_json_returns_parse_error(self, capsys):
        """A malformed notification (invalid JSON) returns a Parse Error."""
        server = RPCServer()
        line = "not json {"

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert response["jsonrpc"] == "2.0"
        assert response["id"] is None
        assert response["error"]["code"] == PARSE_ERROR

    def test_notification_missing_method_returns_invalid_request(self, capsys):
        """A message without method or id should return Invalid Request."""
        server = RPCServer()
        line = json.dumps({"jsonrpc": "2.0", "params": {"x": 1}})

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert response["error"]["code"] == INVALID_REQUEST


# =============================================================================
# Round 5.5: JSONRPCException — typed error propagation from handlers
# =============================================================================


class TestJSONRPCExceptionHandling:
    """Tests that JSONRPCException from handlers produces correct error codes."""

    def test_jsonrpc_exception_returns_correct_error_code(self, capsys):
        """Handler raising JSONRPCException returns the specified error code."""
        async def auth_handler(params: dict | None = None):
            raise JSONRPCException(AUTH_ERROR, "Invalid API key")

        server = RPCServer()
        server.register("test_auth", auth_handler)
        line = make_request(1, "test_auth")

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert response["error"]["code"] == AUTH_ERROR
        assert "Invalid API key" in response["error"]["message"]
        assert "result" not in response

    def test_jsonrpc_exception_with_data_includes_data(self, capsys):
        """JSONRPCException with data includes data in error response."""
        async def rate_limit_handler(params: dict | None = None):
            raise JSONRPCException(
                RATE_LIMIT_EXCEEDED,
                "Rate limited",
                data={"type": "RateLimitError", "retry_after": 30},
            )

        server = RPCServer()
        server.register("test_rate", rate_limit_handler)
        line = make_request(1, "test_rate")

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert response["error"]["code"] == RATE_LIMIT_EXCEEDED
        assert response["error"]["data"]["retry_after"] == 30
        assert response["error"]["data"]["type"] == "RateLimitError"

    def test_jsonrpc_exception_data_excluded_when_none(self, capsys):
        """JSONRPCException without data omits data field (exclude_none)."""
        async def handler(params: dict | None = None):
            raise JSONRPCException(API_TIMEOUT, "Timeout")

        server = RPCServer()
        server.register("test_timeout", handler)
        line = make_request(1, "test_timeout")

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert response["error"]["code"] == API_TIMEOUT
        assert "data" not in response["error"]

    def test_non_jsonrpc_exception_still_returns_internal_error(self, capsys):
        """Non-JSONRPCException exceptions still map to INTERNAL_ERROR."""
        async def broken_handler(params: dict | None = None):
            raise ValueError("something broke")

        server = RPCServer()
        server.register("broken", broken_handler)
        line = make_request(1, "broken")

        asyncio.run(server._handle_line(line))

        captured = capsys.readouterr()
        response = json.loads(captured.out.strip())
        assert response["error"]["code"] == INTERNAL_ERROR


# =============================================================================
# Round 6: Concurrent request processing
# =============================================================================


class TestConcurrentProcessing:
    """Tests that the server handles multiple requests concurrently."""

    def test_concurrent_requests_all_get_responses(self):
        """5 concurrent ping requests all receive correct responses."""
        import io

        server = create_server_with_ping()

        # Capture stdout via a StringIO replacement
        output = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = output

        try:
            async def run_concurrently():
                tasks = []
                for i in range(5):
                    line = make_request(i, "ping", {"seq": i})
                    tasks.append(server._handle_line(line))
                await asyncio.gather(*tasks)

            asyncio.run(run_concurrently())
        finally:
            sys.stdout = original_stdout

        lines = [l for l in output.getvalue().strip().split("\n") if l]
        assert len(lines) == 5, f"expected 5 responses, got {len(lines)}"

        responses_by_id = {}
        for line in lines:
            resp = json.loads(line)
            responses_by_id[resp["id"]] = resp

        for i in range(5):
            assert i in responses_by_id, f"missing response for id {i}"
            assert responses_by_id[i]["result"] == "pong"
            assert responses_by_id[i]["jsonrpc"] == "2.0"

    def test_concurrent_requests_preserve_id_matching(self):
        """Responses match by id regardless of processing order."""
        import io

        server = RPCServer()

        async def echo(params: dict | None = None) -> dict:
            # Simulate variable processing time to encourage interleaving
            if params and params.get("delay"):
                await asyncio.sleep(params["delay"])
            return {"echo": params.get("value") if params else None}

        server.register("echo", echo)

        output = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = output

        try:
            async def run_concurrently():
                tasks = [
                    server._handle_line(
                        make_request(1, "echo", {"value": "fast", "delay": 0})
                    ),
                    server._handle_line(
                        make_request(2, "echo", {"value": "slow", "delay": 0.05})
                    ),
                    server._handle_line(
                        make_request(3, "echo", {"value": "fast2", "delay": 0})
                    ),
                ]
                await asyncio.gather(*tasks)

            asyncio.run(run_concurrently())
        finally:
            sys.stdout = original_stdout

        lines = [l for l in output.getvalue().strip().split("\n") if l]
        assert len(lines) == 3

        responses = {}
        for line in lines:
            resp = json.loads(line)
            responses[resp["id"]] = resp["result"]

        assert responses[1] == {"echo": "fast"}
        assert responses[2] == {"echo": "slow"}
        assert responses[3] == {"echo": "fast2"}

    def test_concurrent_writes_are_not_interleaved(self):
        """Each JSON line written to stdout is a complete, valid JSON object."""
        import io

        server = create_server_with_ping()

        output = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = output

        try:
            async def run_concurrently():
                tasks = [
                    server._handle_line(make_request(i, "ping"))
                    for i in range(20)
                ]
                await asyncio.gather(*tasks)

            asyncio.run(run_concurrently())
        finally:
            sys.stdout = original_stdout

        lines = [l for l in output.getvalue().strip().split("\n") if l]
        assert len(lines) == 20

        # Every line must be valid JSON
        for line in lines:
            obj = json.loads(line)
            assert "jsonrpc" in obj
            assert "id" in obj


# =============================================================================
# Round 7: __main__.py integration (subprocess smoke test)
# =============================================================================


class TestMainIntegration:
    """End-to-end tests via subprocess — verifies __main__.py wires up the server."""

    def test_ping_via_subprocess(self):
        """Start the server via python -m ulysses_ai and ping it."""
        import subprocess

        proc = subprocess.Popen(
            [sys.executable, "-m", "ulysses_ai", "--log-level", "error"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            # Send a ping request
            request = make_request(1, "ping", {}) + "\n"
            stdout, stderr = proc.communicate(input=request, timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise

        lines = [l for l in stdout.strip().split("\n") if l]
        assert len(lines) >= 1, f"expected at least 1 response, got stdout: {stdout!r}, stderr: {stderr!r}"

        response = json.loads(lines[0])
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["result"] == "pong"

    def test_multiple_requests_via_subprocess(self):
        """Send multiple requests and verify all get correct responses."""
        import subprocess

        proc = subprocess.Popen(
            [sys.executable, "-m", "ulysses_ai", "--log-level", "error"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Send 3 requests
        requests = (
            make_request(1, "ping", {}) + "\n"
            + make_request(2, "ping", {}) + "\n"
            + make_request(3, "ping", {}) + "\n"
        )

        try:
            stdout, stderr = proc.communicate(input=requests, timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise

        lines = [l for l in stdout.strip().split("\n") if l]
        assert len(lines) == 3, f"expected 3 responses, got {len(lines)}: {stdout!r}"

        ids = []
        for line in lines:
            resp = json.loads(line)
            assert resp["result"] == "pong"
            ids.append(resp["id"])

        assert sorted(ids) == [1, 2, 3]
