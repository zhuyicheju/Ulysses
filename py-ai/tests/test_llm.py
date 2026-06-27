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
# Streaming helpers
# =============================================================================


class _MockStreamCtx:
    """Mock async context manager + async iterator for client.messages.stream().

    Yields mock stream events that have .type and type-specific attributes.
    """

    def __init__(self, events: list[MagicMock]) -> None:
        self._events = list(events)

    async def __aenter__(self) -> "_MockStreamCtx":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    def __aiter__(self) -> "_MockStreamCtx":
        return self

    async def __anext__(self) -> MagicMock:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class _MockStreamCtxWithError:
    """Mock stream that yields events then raises an error on __anext__."""

    def __init__(self, events: list[MagicMock], error: Exception) -> None:
        self._events = list(events)
        self._error = error
        self._idx = 0

    async def __aenter__(self) -> "_MockStreamCtxWithError":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    def __aiter__(self) -> "_MockStreamCtxWithError":
        return self

    async def __anext__(self) -> MagicMock:
        if self._idx >= len(self._events):
            raise self._error
        event = self._events[self._idx]
        self._idx += 1
        return event


def _make_mock_stream_event(event_type: str, **kwargs: object) -> MagicMock:
    """Create a mock Anthropic RawMessageStreamEvent with the given type and attrs."""
    event = MagicMock()
    event.type = event_type
    for key, value in kwargs.items():
        setattr(event, key, value)
    return event


def _make_mock_client_stream(
    events: list[MagicMock] | None = None,
    side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock AsyncAnthropic client with patched messages.stream.

    Args:
        events: Stream events to yield from the mock.
        side_effect: Exception to raise from messages.stream() itself
                     (simulates Phase 1 error, before __aenter__).

    Returns a MagicMock that can be used as _client.
    """
    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    stream_mock = MagicMock()
    if side_effect is not None:
        stream_mock.side_effect = side_effect
    elif events is not None:
        stream_mock.return_value = _MockStreamCtx(events)
    else:
        stream_mock.return_value = _MockStreamCtx([])
    mock_client.messages.stream = stream_mock
    return mock_client


def _make_mock_client_stream_with_error(
    events: list[MagicMock],
    error: Exception,
) -> MagicMock:
    """Create a mock client whose stream yields events then raises an error.

    Simulates a Phase 2 error (during streaming).
    """
    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream.return_value = _MockStreamCtxWithError(events, error)
    return mock_client


def _register_stream_and_call(
    params: dict | None,
    mock_client: MagicMock,
) -> tuple[list[dict], dict | None]:
    """Register chat_stream handler, send request, return (notifications, final_response).

    Patches handlers.llm._client with the mock, then dispatches a chat_stream
    request through RPCServer._handle_line and parses all stdout output.
    """
    import io
    import sys

    from ulysses_ai.handlers.llm import chat_stream

    server = RPCServer()
    server.register("chat_stream", chat_stream)
    line = make_request(1, "chat_stream", params)

    output = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = output

    try:
        with patch("ulysses_ai.handlers.llm._client", mock_client, create=True):
            asyncio.run(server._handle_line(line))
    finally:
        sys.stdout = original_stdout

    raw = output.getvalue().strip()
    lines = [ln for ln in raw.split("\n") if ln.strip()]

    notifications: list[dict] = []
    final_response: dict | None = None
    for ln in lines:
        obj = json.loads(ln)
        # Notifications have a 'method' field and no 'id' field
        if "method" in obj and "id" not in obj:
            notifications.append(obj)
        else:
            final_response = obj

    return notifications, final_response


# =============================================================================
# TestChatStreamSuccess — happy-path streaming scenarios
# =============================================================================


class TestChatStreamSuccess:
    """Tests for successful chat_stream calls with mocked Anthropic client."""

    def test_single_text_block_single_delta(self):
        """A simple text-only stream with one content block and one delta."""
        events = [
            _make_mock_stream_event(
                "message_start",
                message=_make_mock_message({
                    "id": "msg_01Str",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                }),
            ),
            _make_mock_stream_event(
                "content_block_start",
                index=0,
                content_block=_make_mock_message({
                    "type": "text",
                    "text": "",
                }),
            ),
            _make_mock_stream_event(
                "content_block_delta",
                index=0,
                delta=_make_mock_message({
                    "type": "text_delta",
                    "text": "Hello! How can I help?",
                }),
            ),
            _make_mock_stream_event(
                "content_block_stop",
                index=0,
            ),
            _make_mock_stream_event(
                "message_delta",
                delta=_make_mock_message({
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                }),
                usage=_make_mock_message({
                    "output_tokens": 10,
                }),
            ),
            _make_mock_stream_event(
                "message_stop",
            ),
        ]
        mock_client = _make_mock_client_stream(events=events)

        notifications, final = _register_stream_and_call(
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello!"}],
                "max_tokens": 100,
            },
            mock_client,
        )

        # Verify notification count and types
        assert len(notifications) == 6, f"expected 6 notifications, got {len(notifications)}"
        methods = [n["method"] for n in notifications]
        assert methods == [
            "stream/message_start",
            "stream/content_block_start",
            "stream/content_block_delta",
            "stream/content_block_stop",
            "stream/message_delta",
            "stream/message_stop",
        ], f"unexpected notification sequence: {methods}"

        # message_start
        ms = notifications[0]
        assert ms["params"]["request_id"] == 1
        assert ms["params"]["message"]["id"] == "msg_01Str"
        assert ms["params"]["message"]["type"] == "message"
        assert ms["params"]["message"]["role"] == "assistant"
        assert ms["params"]["message"]["model"] == "claude-sonnet-4-6"

        # content_block_start
        cbs = notifications[1]
        assert cbs["params"]["request_id"] == 1
        assert cbs["params"]["index"] == 0
        assert cbs["params"]["content_block"]["type"] == "text"

        # content_block_delta
        cbd = notifications[2]
        assert cbd["params"]["request_id"] == 1
        assert cbd["params"]["index"] == 0
        assert cbd["params"]["delta"]["type"] == "text_delta"
        assert cbd["params"]["delta"]["text"] == "Hello! How can I help?"

        # content_block_stop
        cb_stop = notifications[3]
        assert cb_stop["params"]["request_id"] == 1
        assert cb_stop["params"]["index"] == 0

        # message_delta
        md = notifications[4]
        assert md["params"]["request_id"] == 1
        assert md["params"]["delta"]["stop_reason"] == "end_turn"
        assert md["params"]["usage"]["output_tokens"] == 10

        # message_stop
        mstop = notifications[5]
        assert mstop["params"]["request_id"] == 1

        # Final response
        assert final is not None
        assert final["jsonrpc"] == "2.0"
        assert final["id"] == 1
        assert "error" not in final
        assert final["result"]["status"] == "completed"

    def test_multiple_text_deltas(self):
        """A text stream with 3 deltas accumulated progressively."""
        events = [
            _make_mock_stream_event(
                "message_start",
                message=_make_mock_message({
                    "id": "msg_02Str",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                }),
            ),
            _make_mock_stream_event(
                "content_block_start",
                index=0,
                content_block=_make_mock_message({"type": "text", "text": ""}),
            ),
            _make_mock_stream_event(
                "content_block_delta",
                index=0,
                delta=_make_mock_message({"type": "text_delta", "text": "Hello"}),
            ),
            _make_mock_stream_event(
                "content_block_delta",
                index=0,
                delta=_make_mock_message({"type": "text_delta", "text": "! How"}),
            ),
            _make_mock_stream_event(
                "content_block_delta",
                index=0,
                delta=_make_mock_message({"type": "text_delta", "text": " can I help?"}),
            ),
            _make_mock_stream_event("content_block_stop", index=0),
            _make_mock_stream_event(
                "message_delta",
                delta=_make_mock_message({"stop_reason": "end_turn", "stop_sequence": None}),
                usage=_make_mock_message({"output_tokens": 24}),
            ),
            _make_mock_stream_event("message_stop"),
        ]
        mock_client = _make_mock_client_stream(events=events)

        notifications, final = _register_stream_and_call(
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 100,
            },
            mock_client,
        )

        assert len(notifications) == 8
        # Verify all deltas have correct index and request_id
        deltas = [n for n in notifications if n["method"] == "stream/content_block_delta"]
        assert len(deltas) == 3
        for d in deltas:
            assert d["params"]["request_id"] == 1
            assert d["params"]["index"] == 0
            assert d["params"]["delta"]["type"] == "text_delta"
        assert deltas[0]["params"]["delta"]["text"] == "Hello"
        assert deltas[1]["params"]["delta"]["text"] == "! How"
        assert deltas[2]["params"]["delta"]["text"] == " can I help?"

        assert final["result"]["status"] == "completed"

    def test_tool_use_stream(self):
        """Tool use stream: text block then tool_use block with input_json_delta."""
        events = [
            _make_mock_stream_event(
                "message_start",
                message=_make_mock_message({
                    "id": "msg_03Tool",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                }),
            ),
            # Text block
            _make_mock_stream_event(
                "content_block_start",
                index=0,
                content_block=_make_mock_message({"type": "text", "text": ""}),
            ),
            _make_mock_stream_event(
                "content_block_delta",
                index=0,
                delta=_make_mock_message({"type": "text_delta", "text": "Let me check that."}),
            ),
            _make_mock_stream_event("content_block_stop", index=0),
            # Tool use block
            _make_mock_stream_event(
                "content_block_start",
                index=1,
                content_block=_make_mock_message({
                    "type": "tool_use",
                    "id": "toolu_01Test",
                    "name": "read_file",
                    "input": {},
                }),
            ),
            _make_mock_stream_event(
                "content_block_delta",
                index=1,
                delta=_make_mock_message({
                    "type": "input_json_delta",
                    "partial_json": '{"path":"/etc/hosts"}',
                }),
            ),
            _make_mock_stream_event("content_block_stop", index=1),
            _make_mock_stream_event(
                "message_delta",
                delta=_make_mock_message({"stop_reason": "tool_use", "stop_sequence": None}),
                usage=_make_mock_message({"output_tokens": 30}),
            ),
            _make_mock_stream_event("message_stop"),
        ]
        mock_client = _make_mock_client_stream(events=events)

        notifications, final = _register_stream_and_call(
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

        assert len(notifications) == 9

        # Check content_block_start for text (index 0)
        cb_starts = [n for n in notifications if n["method"] == "stream/content_block_start"]
        assert len(cb_starts) == 2
        assert cb_starts[0]["params"]["index"] == 0
        assert cb_starts[0]["params"]["content_block"]["type"] == "text"
        assert cb_starts[1]["params"]["index"] == 1
        assert cb_starts[1]["params"]["content_block"]["type"] == "tool_use"
        assert cb_starts[1]["params"]["content_block"]["id"] == "toolu_01Test"
        assert cb_starts[1]["params"]["content_block"]["name"] == "read_file"
        assert cb_starts[1]["params"]["content_block"]["input"] == {}

        # Check input_json_delta
        deltas = [n for n in notifications if n["method"] == "stream/content_block_delta"]
        assert len(deltas) == 2
        assert deltas[1]["params"]["delta"]["type"] == "input_json_delta"
        assert deltas[1]["params"]["delta"]["partial_json"] == '{"path":"/etc/hosts"}'

        # message_delta has tool_use stop_reason
        msg_delta = [n for n in notifications if n["method"] == "stream/message_delta"]
        assert msg_delta[0]["params"]["delta"]["stop_reason"] == "tool_use"

        assert final["result"]["status"] == "completed"

    def test_optional_params_forwarded_to_stream(self):
        """All optional params in the request are forwarded to client.messages.stream()."""
        events = [
            _make_mock_stream_event(
                "message_start",
                message=_make_mock_message({
                    "id": "msg_04",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                }),
            ),
            _make_mock_stream_event(
                "content_block_start",
                index=0,
                content_block=_make_mock_message({"type": "text", "text": ""}),
            ),
            _make_mock_stream_event(
                "content_block_delta",
                index=0,
                delta=_make_mock_message({"type": "text_delta", "text": "Ok"}),
            ),
            _make_mock_stream_event("content_block_stop", index=0),
            _make_mock_stream_event(
                "message_delta",
                delta=_make_mock_message({"stop_reason": "end_turn", "stop_sequence": None}),
                usage=_make_mock_message({"output_tokens": 5}),
            ),
            _make_mock_stream_event("message_stop"),
        ]
        mock_client = _make_mock_client_stream(events=events)

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
        _register_stream_and_call(params, mock_client)

        # Verify params were passed to messages.stream
        call_kwargs = mock_client.messages.stream.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["messages"] == [{"role": "user", "content": "Hi"}]
        assert call_kwargs["max_tokens"] == 50
        assert call_kwargs["system"] == "You are helpful."
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["top_p"] == 0.9
        assert call_kwargs["stop_sequences"] == ["\n\n"]
        assert call_kwargs["metadata"] == {"user_id": "test"}

    def test_no_extra_params_leaked_stream(self):
        """Only recognized params are forwarded to stream; extras are not."""
        events = [
            _make_mock_stream_event(
                "message_start",
                message=_make_mock_message({
                    "id": "msg_05",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                }),
            ),
            _make_mock_stream_event(
                "content_block_start",
                index=0,
                content_block=_make_mock_message({"type": "text", "text": ""}),
            ),
            _make_mock_stream_event(
                "content_block_delta",
                index=0,
                delta=_make_mock_message({"type": "text_delta", "text": "Ok"}),
            ),
            _make_mock_stream_event("content_block_stop", index=0),
            _make_mock_stream_event(
                "message_delta",
                delta=_make_mock_message({"stop_reason": "end_turn", "stop_sequence": None}),
                usage=_make_mock_message({"output_tokens": 5}),
            ),
            _make_mock_stream_event("message_stop"),
        ]
        mock_client = _make_mock_client_stream(events=events)

        _register_stream_and_call(
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 50,
                "unknown_param": "should_not_appear",
                "another_extra": 123,
            },
            mock_client,
        )

        call_kwargs = mock_client.messages.stream.call_args.kwargs
        assert "unknown_param" not in call_kwargs
        assert "another_extra" not in call_kwargs


# =============================================================================
# TestChatStreamValidation — parameter validation (Phase 1 errors)
# =============================================================================


class TestChatStreamValidation:
    """Tests that invalid params for chat_stream produce INVALID_PARAMS errors."""

    def test_none_params(self):
        """params is None → INVALID_PARAMS (Phase 1, no notifications)."""
        notifications, final = _register_stream_and_call(
            None,
            _make_mock_client_stream(),
        )
        assert len(notifications) == 0
        assert final is not None
        assert final["error"]["code"] == INVALID_PARAMS

    def test_missing_model(self):
        """params missing 'model' → INVALID_PARAMS."""
        notifications, final = _register_stream_and_call(
            {"messages": [{"role": "user", "content": "Hi"}], "max_tokens": 50},
            _make_mock_client_stream(),
        )
        assert len(notifications) == 0
        assert final["error"]["code"] == INVALID_PARAMS

    def test_empty_model(self):
        """model is empty string → INVALID_PARAMS."""
        notifications, final = _register_stream_and_call(
            {"model": "", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 50},
            _make_mock_client_stream(),
        )
        assert len(notifications) == 0
        assert final["error"]["code"] == INVALID_PARAMS

    def test_missing_messages(self):
        """params missing 'messages' → INVALID_PARAMS."""
        notifications, final = _register_stream_and_call(
            {"model": "claude-sonnet-4-6", "max_tokens": 50},
            _make_mock_client_stream(),
        )
        assert len(notifications) == 0
        assert final["error"]["code"] == INVALID_PARAMS

    def test_empty_messages(self):
        """messages is empty list → INVALID_PARAMS."""
        notifications, final = _register_stream_and_call(
            {"model": "claude-sonnet-4-6", "messages": [], "max_tokens": 50},
            _make_mock_client_stream(),
        )
        assert len(notifications) == 0
        assert final["error"]["code"] == INVALID_PARAMS

    def test_missing_max_tokens(self):
        """params missing 'max_tokens' → INVALID_PARAMS."""
        notifications, final = _register_stream_and_call(
            {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "Hi"}]},
            _make_mock_client_stream(),
        )
        assert len(notifications) == 0
        assert final["error"]["code"] == INVALID_PARAMS


# =============================================================================
# TestChatStreamErrorMapping — stream error handling (Phase 1 & Phase 2)
# =============================================================================


class TestChatStreamErrorMapping:
    """Tests that stream errors produce correct error responses.

    Phase 1: error before any event sent → standard JSON-RPC error response.
    Phase 2: error during stream → stream/error notification + error status response.
    """

    def test_auth_error_before_stream(self):
        """AuthenticationError before stream → standard JSON-RPC error (Phase 1)."""
        exc = AuthenticationError(
            "Invalid API key",
            response=_make_mock_response(401),
            body={"error": "invalid key"},
        )
        notifications, final = _register_stream_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client_stream(side_effect=exc),
        )
        # Phase 1: no notifications, single error response
        assert len(notifications) == 0
        assert final is not None
        assert final["error"]["code"] == AUTH_ERROR

    def test_rate_limit_before_stream(self):
        """RateLimitError before stream → standard JSON-RPC error (Phase 1)."""
        exc = RateLimitError(
            "Too many requests",
            response=_make_mock_response(429),
            body={"error": "rate limited"},
        )
        notifications, final = _register_stream_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client_stream(side_effect=exc),
        )
        assert len(notifications) == 0
        assert final["error"]["code"] == RATE_LIMIT_EXCEEDED

    def test_model_not_found_before_stream(self):
        """NotFoundError before stream → standard JSON-RPC error (Phase 1)."""
        exc = NotFoundError(
            "Model not found",
            response=_make_mock_response(404),
            body={"error": "not found"},
        )
        notifications, final = _register_stream_and_call(
            {"model": "claude", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            _make_mock_client_stream(side_effect=exc),
        )
        assert len(notifications) == 0
        assert final["error"]["code"] == MODEL_NOT_AVAILABLE

    def test_connection_error_during_stream(self):
        """APIConnectionError during stream (Phase 2) → stream/error notification + error result."""
        events = [
            _make_mock_stream_event(
                "message_start",
                message=_make_mock_message({
                    "id": "msg_Err",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                }),
            ),
        ]
        exc = APIConnectionError(
            message="Connection lost mid-stream",
            request=_make_mock_request(),
        )
        mock_client = _make_mock_client_stream_with_error(events=events, error=exc)

        notifications, final = _register_stream_and_call(
            {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10},
            mock_client,
        )

        # Phase 2: message_start notification should have been sent
        assert len(notifications) >= 1
        assert notifications[0]["method"] == "stream/message_start"

        # Check that stream/error notification is present
        error_notifs = [n for n in notifications if n["method"] == "stream/error"]
        assert len(error_notifs) == 1
        assert error_notifs[0]["params"]["request_id"] == 1
        assert error_notifs[0]["params"]["code"] == API_TIMEOUT
        assert "API connection" in error_notifs[0]["params"]["message"]

        # Final response has error status
        assert final is not None
        assert final["result"]["status"] == "error"
        assert final["result"]["error"]["code"] == API_TIMEOUT


# =============================================================================
# TestChatStreamIntegration — end-to-end with real Anthropic API
# =============================================================================


class TestChatStreamIntegration:
    """End-to-end streaming test via subprocess with real Anthropic API.

    Requires ANTHROPIC_API_KEY to be set in the environment.
    """

    def test_chat_stream_via_subprocess(self):
        """Send a chat_stream request and verify notifications + final response."""
        import os
        import subprocess
        import sys
        from dotenv import load_dotenv

        load_dotenv()

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            pytest.skip("ANTHROPIC_API_KEY not set")

        proc = subprocess.Popen(
            [
                sys.executable, "-m", "ulysses_ai",
                "--log-level", "error",
                "--base-url", "https://api.deepseek.com/anthropic",
                "--api-key", api_key,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        request = make_request(1, "chat_stream", {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "Reply with exactly: Hello"}],
            "max_tokens": 50,
        }) + "\n"

        try:
            stdout, stderr = proc.communicate(input=request, timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise AssertionError(
                f"subprocess timed out after 30s\n"
                f"stdout: {stdout!r}\n"
                f"stderr: {stderr!r}\n"
            )

        # Parse all output lines
        lines = [ln for ln in stdout.strip().split("\n") if ln.strip()]
        assert lines, (
            f"subprocess produced no stdout (exit code {proc.returncode})\n"
            f"stderr: {stderr!r}"
        )
        assert proc.returncode == 0, (
            f"subprocess exited with code {proc.returncode}\n"
            f"stdout: {stdout!r}\n"
            f"stderr: {stderr!r}"
        )

        # Separate notifications from final response
        notifications = []
        final_response = None
        for ln in lines:
            obj = json.loads(ln)
            if "method" in obj and "id" not in obj:
                notifications.append(obj)
            else:
                final_response = obj

        print("\n=== Stream Output ===")
        print(f"Notifications: {len(notifications)}")
        for n in notifications:
            print(f"  {n['method']}")
        print(f"Final: {json.dumps(final_response, indent=2) if final_response else 'None'}")
        print("=====================\n")

        # Basic structural assertions
        assert len(notifications) >= 2, f"expected at least 2 notifications, got {len(notifications)}"

        # Should have message_start and message_stop
        methods = [n["method"] for n in notifications]
        assert "stream/message_start" in methods, f"missing message_start in {methods}"
        assert "stream/message_stop" in methods, f"missing message_stop in {methods}"

        # All notifications must have correct request_id
        for n in notifications:
            assert n["params"]["request_id"] == 1

        # Final response must have status=completed and correct id
        assert final_response is not None, "missing final response"
        assert final_response["jsonrpc"] == "2.0"
        assert final_response["id"] == 1
        assert "error" not in final_response
        assert final_response["result"]["status"] == "completed"


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
        from dotenv import load_dotenv

        load_dotenv()

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            pytest.skip("ANTHROPIC_API_KEY not set")

        proc = subprocess.Popen(
            [sys.executable, "-m", "ulysses_ai", "--log-level", "error", "--base-url", "https://api.deepseek.com/anthropic", "--api-key", api_key],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        request = make_request(1, "chat", {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "Reply with exactly: Hello"}],
            "max_tokens": 50,
        }) + "\n"

        try:
            stdout, stderr = proc.communicate(input=request, timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise AssertionError(
                f"subprocess timed out after 30s\n"
                f"stdout: {stdout!r}\n"
                f"stderr: {stderr!r}\n"
            )

        # Diagnostic checks before JSON parsing — provide context on failure.
        assert stdout.strip(), (
            f"subprocess produced no stdout (exit code {proc.returncode})\n"
            f"stderr: {stderr!r}"
        )
        assert proc.returncode == 0, (
            f"subprocess exited with code {proc.returncode}\n"
            f"stdout: {stdout!r}\n"
            f"stderr: {stderr!r}"
        )

        response = json.loads(stdout.strip())

        print("\n=== Response ===")
        print(json.dumps(response, indent=2))
        print("================\n")
        
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "error" not in response, (
            f"Unexpected error: {response.get('error')}\n"
            f"stderr: {stderr!r}"
        )
        assert response["result"]["type"] == "message"
        assert response["result"]["role"] == "assistant"
        assert "content" in response["result"]
        assert len(response["result"]["content"]) > 0
