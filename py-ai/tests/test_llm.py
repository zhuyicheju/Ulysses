"""Tests for ulysses_ai.handlers.llm — chat handler.

Follows TDD: each test is written BEFORE the corresponding implementation.
Uses mocked Anthropic clients to test success and error cases.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from ulysses_ai.protocol import (
    API_TIMEOUT,
    AUTH_ERROR,
    CONTEXT_LENGTH_EXCEEDED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    MODEL_NOT_AVAILABLE,
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


def _make_mock_response(status_code: int = 200) -> MagicMock:
    """Create a minimal mock httpx.Response for constructing anthropic exceptions."""
    mock_headers = MagicMock()
    mock_headers.get.return_value = None
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.headers = mock_headers
    return mock_resp


def _make_mock_request() -> MagicMock:
    """Create a minimal mock httpx.Request for APITimeoutError/APIConnectionError."""
    return MagicMock(spec=httpx.Request)


def _make_mock_message(data: dict) -> MagicMock:
    """Create a mock Anthropic Message whose model_dump() returns data."""
    msg = MagicMock()
    msg.model_dump.return_value = data
    return msg


def _make_mock_client(
    mock_message: MagicMock | None = None,
    side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock AsyncAnthropic client with a patched messages.create.

    Args:
        mock_message: The Message to return from create().
        side_effect: An exception to raise from create().

    Returns a MagicMock that can be used as _client.
    """
    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    create_mock = AsyncMock()
    if side_effect is not None:
        create_mock.side_effect = side_effect
    elif mock_message is not None:
        create_mock.return_value = mock_message
    else:
        create_mock.return_value = _make_mock_message({})
    mock_client.messages.create = create_mock
    return mock_client


def _register_chat_and_call(
    params: dict,
    mock_client: MagicMock,
) -> dict:
    """Register the chat handler with mock client, send request, return parsed response.

    Patches handlers.llm._client with the mock, then dispatches a chat request
    through RPCServer._handle_line and returns the parsed JSON response.
    """
    import io
    import sys

    # Import here to avoid circular issues at module level
    from ulysses_ai.handlers.llm import chat

    server = RPCServer()
    server.register("chat", chat)
    line = make_request(1, "chat", params)

    output = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = output

    try:
        with patch("ulysses_ai.handlers.llm._client", mock_client, create=True):
            asyncio.run(server._handle_line(line))
    finally:
        sys.stdout = original_stdout

    raw = output.getvalue().strip()
    return json.loads(raw)


# =============================================================================
# TestChatSuccess — happy-path scenarios
# =============================================================================


class TestChatSuccess:
    """Tests for successful chat calls with mocked Anthropic client."""

    def test_simple_text_response(self):
        """A simple text-only chat returns the expected message structure."""
        expected = {
            "id": "msg_01Test",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello! How can I help?"}],
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 15,
                "output_tokens": 10,
            },
        }
        mock_client = _make_mock_client(mock_message=_make_mock_message(expected))

        response = _register_chat_and_call(
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello!"}],
                "max_tokens": 100,
            },
            mock_client,
        )

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "error" not in response
        assert response["result"]["id"] == "msg_01Test"
        assert response["result"]["type"] == "message"
        assert response["result"]["role"] == "assistant"
        assert response["result"]["content"][0]["type"] == "text"
        assert response["result"]["stop_reason"] == "end_turn"
        assert response["result"]["usage"]["input_tokens"] == 15
        assert response["result"]["usage"]["output_tokens"] == 10

    def test_tool_use_response(self):
        """A response with tool_use returns correct content blocks and stop_reason."""
        expected = {
            "id": "msg_02Tool",
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me check that."},
                {
                    "type": "tool_use",
                    "id": "toolu_01Test",
                    "name": "read_file",
                    "input": {"path": "/etc/hosts"},
                },
            ],
            "model": "claude-sonnet-4-6",
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 20, "output_tokens": 25},
        }
        mock_client = _make_mock_client(mock_message=_make_mock_message(expected))

        response = _register_chat_and_call(
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Read /etc/hosts"}],
                "max_tokens": 100,
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read a file",
                        "input_schema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    }
                ],
            },
            mock_client,
        )

        assert response["result"]["stop_reason"] == "tool_use"
        assert len(response["result"]["content"]) == 2
        assert response["result"]["content"][0]["type"] == "text"
        assert response["result"]["content"][1]["type"] == "tool_use"
        assert response["result"]["content"][1]["name"] == "read_file"

    def test_optional_params_forwarded(self):
        """All optional params present in the request are forwarded to the API."""
        expected = {
            "id": "msg_03",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Ok"}],
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_client = _make_mock_client(mock_message=_make_mock_message(expected))

        params = {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 50,
            "system": "You are helpful.",
            "temperature": 0.5,
            "top_p": 0.9,
            "stop_sequences": ["\n\n"],
            "metadata": {"user_id": "test"},
        }
        _register_chat_and_call(params, mock_client)

        # Verify all params were passed through to messages.create
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["messages"] == [{"role": "user", "content": "Hi"}]
        assert call_kwargs["max_tokens"] == 50
        assert call_kwargs["system"] == "You are helpful."
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["top_p"] == 0.9
        assert call_kwargs["stop_sequences"] == ["\n\n"]
        assert call_kwargs["metadata"] == {"user_id": "test"}

    def test_system_as_content_blocks(self):
        """System prompt passed as a list of TextBlocks is forwarded correctly."""
        expected = {
            "id": "msg_04",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Ok"}],
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_client = _make_mock_client(mock_message=_make_mock_message(expected))

        system_blocks = [
            {"type": "text", "text": "You are a helpful assistant."},
            {"type": "text", "text": "Be concise."},
        ]
        _register_chat_and_call(
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 50,
                "system": system_blocks,
            },
            mock_client,
        )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == system_blocks

    def test_no_extra_params_leaked(self):
        """Only recognized params are forwarded; extras are not."""
        expected = {
            "id": "msg_05",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Ok"}],
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_client = _make_mock_client(mock_message=_make_mock_message(expected))

        _register_chat_and_call(
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 50,
                "unknown_param": "should_not_appear",
                "another_extra": 123,
            },
            mock_client,
        )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "unknown_param" not in call_kwargs
        assert "another_extra" not in call_kwargs


# =============================================================================
# TestChatValidation — parameter validation
# =============================================================================


class TestChatValidation:
    """Tests that invalid params produce INVALID_PARAMS errors."""

    def test_none_params(self):
        """params is None → INVALID_PARAMS."""
        response = _register_chat_and_call(
            None,
            _make_mock_client(),
        )
        assert response["error"]["code"] == INVALID_PARAMS

    def test_missing_model(self):
        """params missing 'model' → INVALID_PARAMS."""
        response = _register_chat_and_call(
            {"messages": [{"role": "user", "content": "Hi"}], "max_tokens": 50},
            _make_mock_client(),
        )
        assert response["error"]["code"] == INVALID_PARAMS

    def test_empty_model(self):
        """model is empty string → INVALID_PARAMS."""
        response = _register_chat_and_call(
            {"model": "", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 50},
            _make_mock_client(),
        )
        assert response["error"]["code"] == INVALID_PARAMS

    def test_missing_messages(self):
        """params missing 'messages' → INVALID_PARAMS."""
        response = _register_chat_and_call(
            {"model": "claude-sonnet-4-6", "max_tokens": 50},
            _make_mock_client(),
        )
        assert response["error"]["code"] == INVALID_PARAMS

    def test_empty_messages(self):
        """messages is empty list → INVALID_PARAMS."""
        response = _register_chat_and_call(
            {"model": "claude-sonnet-4-6", "messages": [], "max_tokens": 50},
            _make_mock_client(),
        )
        assert response["error"]["code"] == INVALID_PARAMS

    def test_missing_max_tokens(self):
        """params missing 'max_tokens' → INVALID_PARAMS."""
        response = _register_chat_and_call(
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hi"}],
            },
            _make_mock_client(),
        )
        assert response["error"]["code"] == INVALID_PARAMS


# =============================================================================
# TestChatErrorMapping — Anthropic SDK exceptions → JSON-RPC error codes
# =============================================================================


class TestChatErrorMapping:
    """Tests that Anthropic SDK exceptions map to correct JSON-RPC error codes."""

    def test_auth_error(self):
        """AuthenticationError → AUTH_ERROR (-32002)."""
        exc = AuthenticationError(
            "Invalid API key",
            response=_make_mock_response(401),
            body={"error": "invalid key"},
        )
        response = _register_chat_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client(side_effect=exc),
        )
        assert response["error"]["code"] == AUTH_ERROR
        assert "Authentication failed" in response["error"]["message"]

    def test_permission_denied_error(self):
        """PermissionDeniedError → AUTH_ERROR (-32002)."""
        exc = PermissionDeniedError(
            "No access",
            response=_make_mock_response(403),
            body={"error": "forbidden"},
        )
        response = _register_chat_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client(side_effect=exc),
        )
        assert response["error"]["code"] == AUTH_ERROR

    def test_rate_limit_error(self):
        """RateLimitError → RATE_LIMIT_EXCEEDED (-32000)."""
        exc = RateLimitError(
            "Too many requests",
            response=_make_mock_response(429),
            body={"error": "rate limited"},
        )
        response = _register_chat_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client(side_effect=exc),
        )
        assert response["error"]["code"] == RATE_LIMIT_EXCEEDED

    def test_context_length_exceeded_via_body(self):
        """BadRequestError with body.type=context_length_exceeded → CONTEXT_LENGTH_EXCEEDED."""
        exc = BadRequestError(
            "Context too long",
            response=_make_mock_response(400),
            body={"type": "context_length_exceeded", "message": "too many tokens"},
        )
        response = _register_chat_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client(side_effect=exc),
        )
        assert response["error"]["code"] == CONTEXT_LENGTH_EXCEEDED

    def test_context_length_exceeded_via_message(self):
        """BadRequestError mentioning 'context' → CONTEXT_LENGTH_EXCEEDED (-32001)."""
        exc = BadRequestError(
            "prompt is too long for context window",
            response=_make_mock_response(400),
            body=None,
        )
        response = _register_chat_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client(side_effect=exc),
        )
        assert response["error"]["code"] == CONTEXT_LENGTH_EXCEEDED

    def test_bad_request_generic(self):
        """BadRequestError (non-context) → INVALID_PARAMS (-32602)."""
        exc = BadRequestError(
            "model not supported for this endpoint",
            response=_make_mock_response(400),
            body=None,
        )
        response = _register_chat_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client(side_effect=exc),
        )
        assert response["error"]["code"] == INVALID_PARAMS

    def test_timeout_error(self):
        """APITimeoutError → API_TIMEOUT (-32003)."""
        exc = APITimeoutError(request=_make_mock_request())
        response = _register_chat_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client(side_effect=exc),
        )
        assert response["error"]["code"] == API_TIMEOUT

    def test_connection_error(self):
        """APIConnectionError → API_TIMEOUT (-32003)."""
        exc = APIConnectionError(
            message="Connection refused",
            request=_make_mock_request(),
        )
        response = _register_chat_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client(side_effect=exc),
        )
        assert response["error"]["code"] == API_TIMEOUT

    def test_model_not_found(self):
        """NotFoundError → MODEL_NOT_AVAILABLE (-32004)."""
        exc = NotFoundError(
            "Model not found",
            response=_make_mock_response(404),
            body={"error": "not found"},
        )
        response = _register_chat_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client(side_effect=exc),
        )
        assert response["error"]["code"] == MODEL_NOT_AVAILABLE

    def test_internal_server_error(self):
        """InternalServerError → INTERNAL_ERROR (-32603)."""
        exc = InternalServerError(
            "Server error",
            response=_make_mock_response(500),
            body={"error": "internal"},
        )
        response = _register_chat_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client(side_effect=exc),
        )
        assert response["error"]["code"] == INTERNAL_ERROR


# =============================================================================
# TestChatIntegration — end-to-end with real Anthropic API
# =============================================================================


class TestChatIntegration:
    """End-to-end test via subprocess with real Anthropic API.

    Requires ANTHROPIC_API_KEY to be set in the environment.
    """

    def test_chat_via_subprocess(self):
        """Send a chat request to the running server and verify the real response."""
        import os
        import subprocess
        import sys

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            pytest.skip("ANTHROPIC_API_KEY not set")

        proc = subprocess.Popen(
            [sys.executable, "-m", "ulysses_ai", "--log-level", "error"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        request = make_request(1, "chat", {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Reply with exactly: Hello"}],
            "max_tokens": 50,
        }) + "\n"

        try:
            stdout, stderr = proc.communicate(input=request, timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise

        response = json.loads(stdout.strip())
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "error" not in response, f"Unexpected error: {response.get('error')}"
        assert response["result"]["type"] == "message"
        assert response["result"]["role"] == "assistant"
        assert "content" in response["result"]
        assert len(response["result"]["content"]) > 0
