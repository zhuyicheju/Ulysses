"""Tests for ulysses_ai.protocol — JSON-RPC 2.0 type definitions.

Covers all five message types, error code constants, message discrimination,
and real-world examples from api-spec.md.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ulysses_ai.protocol import (
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCNotification,
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
    RATE_LIMIT_EXCEEDED,
    CONTEXT_LENGTH_EXCEEDED,
    AUTH_ERROR,
    API_TIMEOUT,
    MODEL_NOT_AVAILABLE,
)


# =============================================================================
# JSONRPCRequest
# =============================================================================


class TestJSONRPCRequest:
    """Tests for JSON-RPC 2.0 Request."""

    def test_valid_construction(self):
        """Can construct a valid request with all fields."""
        req = JSONRPCRequest(
            id=1,
            method="ping",
            params={},
        )
        assert req.jsonrpc == "2.0"
        assert req.id == 1
        assert req.method == "ping"
        assert req.params == {}

    def test_jsonrpc_defaults_to_2_0(self):
        """jsonrpc field defaults to '2.0'."""
        req = JSONRPCRequest(id=1, method="chat")
        assert req.jsonrpc == "2.0"

    def test_params_defaults_to_none(self):
        """params defaults to None when not provided."""
        req = JSONRPCRequest(id=1, method="ping")
        assert req.params is None

    def test_serialization_round_trip(self):
        """JSON serialization and deserialization produce the same object."""
        original = JSONRPCRequest(
            id=42,
            method="chat",
            params={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "Hello"}]},
        )
        json_str = original.model_dump_json()
        parsed = JSONRPCRequest.model_validate_json(json_str)
        assert parsed.id == 42
        assert parsed.method == "chat"
        assert parsed.params == {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "Hello"}]}
        assert parsed.jsonrpc == "2.0"

    def test_serialization_excludes_none_with_option(self):
        """When params is None, exclude_none=True excludes it from output."""
        req = JSONRPCRequest(id=1, method="ping")
        json_str = req.model_dump_json(exclude_none=True)
        data = json.loads(json_str)
        assert "params" not in data

    def test_serialization_includes_none_by_default(self):
        """By default (without exclude_none), None params is included."""
        req = JSONRPCRequest(id=1, method="ping")
        json_str = req.model_dump_json()
        data = json.loads(json_str)
        assert data["params"] is None

    def test_missing_id_raises_validation_error(self):
        """id is required — missing it raises ValidationError."""
        with pytest.raises(ValidationError):
            JSONRPCRequest(method="ping")

    def test_missing_method_raises_validation_error(self):
        """method is required — missing it raises ValidationError."""
        with pytest.raises(ValidationError):
            JSONRPCRequest(id=1)

    def test_deserialize_from_api_spec_example(self):
        """Can parse a request exactly matching api-spec.md Section 3.1 example."""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "chat",
            "params": {},
        })
        req = JSONRPCRequest.model_validate_json(json_str)
        assert req.jsonrpc == "2.0"
        assert req.id == 1
        assert req.method == "chat"
        assert req.params == {}


# =============================================================================
# JSONRPCResponse
# =============================================================================


class TestJSONRPCResponse:
    """Tests for JSON-RPC 2.0 success Response."""

    def test_valid_construction(self):
        """Can construct a valid success response."""
        resp = JSONRPCResponse(
            id=1,
            result="pong",
        )
        assert resp.jsonrpc == "2.0"
        assert resp.id == 1
        assert resp.result == "pong"

    def test_result_can_be_string(self):
        """result can be a plain string."""
        resp = JSONRPCResponse(id=1, result="pong")
        json_str = resp.model_dump_json()
        data = json.loads(json_str)
        assert data["result"] == "pong"

    def test_result_can_be_object(self):
        """result can be a complex object."""
        resp = JSONRPCResponse(
            id=2,
            result={
                "id": "msg_01AbCdEf",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello!"}],
                "model": "claude-sonnet-4-6",
                "stop_reason": "end_turn",
            },
        )
        json_str = resp.model_dump_json()
        data = json.loads(json_str)
        assert data["result"]["id"] == "msg_01AbCdEf"
        assert data["result"]["role"] == "assistant"

    def test_result_can_be_none(self):
        """result can be None."""
        resp = JSONRPCResponse(id=1, result=None)
        json_str = resp.model_dump_json()
        data = json.loads(json_str)
        assert data["result"] is None

    def test_serialization_round_trip(self):
        """JSON round-trip preserves all fields."""
        original = JSONRPCResponse(
            id=99,
            result={"count": 42, "items": ["a", "b"]},
        )
        json_str = original.model_dump_json()
        parsed = JSONRPCResponse.model_validate_json(json_str)
        assert parsed.id == 99
        assert parsed.result == {"count": 42, "items": ["a", "b"]}
        assert parsed.jsonrpc == "2.0"

    def test_missing_id_raises_validation_error(self):
        """id is required."""
        with pytest.raises(ValidationError):
            JSONRPCResponse(result="ok")


# =============================================================================
# JSONRPCError
# =============================================================================


class TestJSONRPCError:
    """Tests for JSON-RPC 2.0 Error object."""

    def test_valid_construction(self):
        """Can construct an error object."""
        err = JSONRPCError(code=-32603, message="Internal error")
        assert err.code == -32603
        assert err.message == "Internal error"
        assert err.data is None

    def test_with_data(self):
        """Error can carry additional data."""
        err = JSONRPCError(
            code=-32002,
            message="Auth Error",
            data={"type": "AuthenticationError", "detail": "Invalid API key"},
        )
        assert err.data == {"type": "AuthenticationError", "detail": "Invalid API key"}

    def test_serialization_round_trip(self):
        """JSON round-trip preserves error fields."""
        original = JSONRPCError(
            code=-32602,
            message="Invalid params",
            data={"missing": ["model", "messages"]},
        )
        json_str = original.model_dump_json()
        parsed = JSONRPCError.model_validate_json(json_str)
        assert parsed.code == -32602
        assert parsed.message == "Invalid params"
        assert parsed.data == {"missing": ["model", "messages"]}

    def test_data_excluded_when_none_with_option(self):
        """data excluded from output when None with exclude_none=True."""
        err = JSONRPCError(code=-32601, message="Method not found")
        json_str = err.model_dump_json(exclude_none=True)
        data = json.loads(json_str)
        assert "data" not in data

    def test_data_included_when_none_by_default(self):
        """By default, None data is included in output."""
        err = JSONRPCError(code=-32601, message="Method not found")
        json_str = err.model_dump_json()
        data = json.loads(json_str)
        assert data["data"] is None


# =============================================================================
# JSONRPCErrorResponse
# =============================================================================


class TestJSONRPCErrorResponse:
    """Tests for JSON-RPC 2.0 error Response."""

    def test_valid_construction(self):
        """Can construct a valid error response."""
        resp = JSONRPCErrorResponse(
            id=1,
            error=JSONRPCError(code=-32601, message="Method not found"),
        )
        assert resp.jsonrpc == "2.0"
        assert resp.id == 1
        assert resp.error.code == -32601

    def test_null_id_for_parse_errors(self):
        """id can be None when the request id couldn't be determined (e.g., parse errors)."""
        resp = JSONRPCErrorResponse(
            id=None,
            error=JSONRPCError(code=-32700, message="Parse error"),
        )
        json_str = resp.model_dump_json()
        data = json.loads(json_str)
        assert data["id"] is None

    def test_serialization_round_trip(self):
        """JSON round-trip preserves error response."""
        original = JSONRPCErrorResponse(
            id=3,
            error=JSONRPCError(
                code=-32003,
                message="Connection lost",
                data={"traceback": "..."},
            ),
        )
        json_str = original.model_dump_json()
        parsed = JSONRPCErrorResponse.model_validate_json(json_str)
        assert parsed.id == 3
        assert parsed.error.code == -32003
        assert parsed.error.message == "Connection lost"
        assert parsed.error.data == {"traceback": "..."}

    def test_deserialize_from_api_spec_example(self):
        """Can parse error response matching api-spec.md Section 3.3 example."""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32603,
                "message": "Internal error",
                "data": {
                    "type": "AuthenticationError",
                    "detail": "Invalid API key",
                },
            },
        })
        resp = JSONRPCErrorResponse.model_validate_json(json_str)
        assert resp.jsonrpc == "2.0"
        assert resp.id == 1
        assert resp.error.code == -32603
        assert resp.error.data["type"] == "AuthenticationError"

    def test_missing_error_raises_validation_error(self):
        """error field is required."""
        with pytest.raises(ValidationError):
            JSONRPCErrorResponse(id=1)


# =============================================================================
# JSONRPCNotification
# =============================================================================


class TestJSONRPCNotification:
    """Tests for JSON-RPC 2.0 Notification."""

    def test_valid_construction(self):
        """Can construct a valid notification."""
        notif = JSONRPCNotification(
            method="stream/content_block_delta",
            params={"request_id": 3, "index": 0, "delta": {"type": "text_delta", "text": "Hello"}},
        )
        assert notif.jsonrpc == "2.0"
        assert notif.method == "stream/content_block_delta"
        assert notif.params["request_id"] == 3

    def test_no_id_field_in_output(self):
        """Notification must NOT have an id field in serialized output."""
        notif = JSONRPCNotification(method="stream/message_stop", params={"request_id": 3})
        json_str = notif.model_dump_json()
        data = json.loads(json_str)
        assert "id" not in data
        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "stream/message_stop"

    def test_params_defaults_to_none(self):
        """params defaults to None."""
        notif = JSONRPCNotification(method="stream/ping")
        assert notif.params is None

    def test_serialization_round_trip(self):
        """JSON round-trip preserves notification fields."""
        original = JSONRPCNotification(
            method="stream/content_block_start",
            params={
                "request_id": 3,
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        )
        json_str = original.model_dump_json()
        parsed = JSONRPCNotification.model_validate_json(json_str)
        assert parsed.method == "stream/content_block_start"
        assert parsed.params["request_id"] == 3
        assert parsed.jsonrpc == "2.0"

    def test_missing_method_raises_validation_error(self):
        """method is required."""
        with pytest.raises(ValidationError):
            JSONRPCNotification(params={})

    def test_deserialize_stream_notification_from_api_spec(self):
        """Can parse stream notification matching api-spec.md Section 3.4 example."""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "method": "stream/content_block_delta",
            "params": {
                "request_id": 3,
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello"},
            },
        })
        notif = JSONRPCNotification.model_validate_json(json_str)
        assert notif.method == "stream/content_block_delta"
        assert notif.params["request_id"] == 3
        # Notification has no id — this is how Go distinguishes notification from response
        assert not hasattr(notif, "id") or notif.id is None


# =============================================================================
# Error code constants
# =============================================================================


class TestErrorCodes:
    """Tests for JSON-RPC 2.0 error code constants."""

    def test_standard_jsonrpc_error_codes(self):
        """Standard JSON-RPC 2.0 error codes match the spec."""
        assert PARSE_ERROR == -32700
        assert INVALID_REQUEST == -32600
        assert METHOD_NOT_FOUND == -32601
        assert INVALID_PARAMS == -32602
        assert INTERNAL_ERROR == -32603

    def test_application_error_codes(self):
        """Application-specific error codes match api-spec.md Section 7."""
        assert RATE_LIMIT_EXCEEDED == -32000
        assert CONTEXT_LENGTH_EXCEEDED == -32001
        assert AUTH_ERROR == -32002
        assert API_TIMEOUT == -32003
        assert MODEL_NOT_AVAILABLE == -32004

    def test_all_error_codes_are_negative(self):
        """All error codes are negative integers per JSON-RPC 2.0 spec."""
        codes = [
            PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND,
            INVALID_PARAMS, INTERNAL_ERROR,
            RATE_LIMIT_EXCEEDED, CONTEXT_LENGTH_EXCEEDED,
            AUTH_ERROR, API_TIMEOUT, MODEL_NOT_AVAILABLE,
        ]
        for code in codes:
            assert isinstance(code, int)
            assert code < 0


# =============================================================================
# Message discrimination (Union type)
# =============================================================================


class TestMessageDiscrimination:
    """Tests that model_validate_json correctly discriminates message types."""

    def test_request_from_json(self):
        """JSON with id+method → JSONRPCRequest."""
        msg = JSONRPCRequest.model_validate_json(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
        )
        assert isinstance(msg, JSONRPCRequest)
        assert msg.method == "ping"

    def test_response_from_json(self):
        """JSON with id+result (no method) → JSONRPCResponse."""
        msg = JSONRPCResponse.model_validate_json(
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": "pong"})
        )
        assert isinstance(msg, JSONRPCResponse)
        assert msg.result == "pong"

    def test_error_response_from_json(self):
        """JSON with id+error → JSONRPCErrorResponse."""
        msg = JSONRPCErrorResponse.model_validate_json(
            json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "error": {"code": -32601, "message": "Method not found"},
            })
        )
        assert isinstance(msg, JSONRPCErrorResponse)
        assert msg.error.code == -32601

    def test_notification_from_json(self):
        """JSON with method but no id → JSONRPCNotification."""
        msg = JSONRPCNotification.model_validate_json(
            json.dumps({
                "jsonrpc": "2.0",
                "method": "stream/message_stop",
                "params": {"request_id": 3},
            })
        )
        assert isinstance(msg, JSONRPCNotification)
        assert msg.method == "stream/message_stop"

    def test_notification_has_no_id_attribute(self):
        """notification has no id — accessed via model_dump to check absence."""
        notif = JSONRPCNotification.model_validate_json(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"request_id": 5}})
        )
        data = notif.model_dump()
        assert "id" not in data

    def test_request_requires_both_id_and_method(self):
        """JSON with id but no method fails for Request (not a valid Request)."""
        # Must have both id and method for Request
        with pytest.raises(ValidationError):
            JSONRPCRequest.model_validate_json(
                json.dumps({"jsonrpc": "2.0", "id": 1})
            )

    def test_response_without_result_has_none_default(self):
        """JSON with id but no result defaults result to None (valid)."""
        resp = JSONRPCResponse.model_validate_json(
            json.dumps({"jsonrpc": "2.0", "id": 1})
        )
        assert resp.id == 1
        assert resp.result is None


# =============================================================================
# Real-world examples from api-spec.md
# =============================================================================


class TestRealWorldExamples:
    """Validate types against concrete examples from docs/api-spec.md."""

    def test_ping_request_and_response(self):
        """api-spec Section 4.1: ping round-trip."""
        # Request
        req = JSONRPCRequest.model_validate_json(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
        )
        assert req.method == "ping"

        # Response
        resp = JSONRPCResponse.model_validate_json(
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": "pong"})
        )
        assert resp.result == "pong"

    def test_chat_request_with_tools(self):
        """api-spec Section 5.2: chat request with tools."""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "chat",
            "params": {
                "model": "claude-sonnet-4-6",
                "system": "You are a helpful assistant.",
                "messages": [{"role": "user", "content": "Hello!"}],
                "max_tokens": 4096,
                "tools": [{
                    "name": "read_file",
                    "description": "Read the contents of a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "description": "Path to the file"}},
                        "required": ["path"],
                    },
                }],
            },
        })
        req = JSONRPCRequest.model_validate_json(json_str)
        assert req.id == 2
        assert req.method == "chat"
        assert req.params["model"] == "claude-sonnet-4-6"
        assert len(req.params["tools"]) == 1
        assert req.params["tools"][0]["name"] == "read_file"

    def test_chat_response(self):
        """api-spec Section 5.2: chat success response."""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "id": "msg_01AbCdEfGhIjKlMnOpQrStUv",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello! How can I help you today?"}],
                "model": "claude-sonnet-4-6",
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 15,
                    "output_tokens": 10,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        })
        resp = JSONRPCResponse.model_validate_json(json_str)
        assert resp.id == 2
        assert resp.result["id"] == "msg_01AbCdEfGhIjKlMnOpQrStUv"
        assert resp.result["stop_reason"] == "end_turn"
        assert resp.result["usage"]["input_tokens"] == 15

    def test_chat_response_with_tool_use(self):
        """api-spec Section 5.2: chat response with tool_use."""
        json_str = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "id": "msg_01XyZ",
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me read that file for you."},
                    {
                        "type": "tool_use",
                        "id": "toolu_01AbCdEfGhIjKlMnOpQrStUv",
                        "name": "read_file",
                        "input": {"path": "/etc/hosts"},
                    },
                ],
                "model": "claude-sonnet-4-6",
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 45, "output_tokens": 30},
            },
        })
        resp = JSONRPCResponse.model_validate_json(json_str)
        assert resp.result["stop_reason"] == "tool_use"
        assert len(resp.result["content"]) == 2
        assert resp.result["content"][1]["type"] == "tool_use"
        assert resp.result["content"][1]["name"] == "read_file"

    def test_count_tokens_request_and_response(self):
        """api-spec Section 5.4: count_tokens round-trip."""
        req = JSONRPCRequest.model_validate_json(
            json.dumps({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "count_tokens",
                "params": {
                    "model": "claude-sonnet-4-6",
                    "system": "You are a helpful assistant.",
                    "messages": [{"role": "user", "content": "Hello!"}],
                },
            })
        )
        assert req.method == "count_tokens"

        resp = JSONRPCResponse.model_validate_json(
            json.dumps({"jsonrpc": "2.0", "id": 4, "result": {"count": 15}})
        )
        assert resp.result["count"] == 15

    def test_shutdown_request_and_response(self):
        """api-spec Section 5.5: shutdown round-trip."""
        req = JSONRPCRequest.model_validate_json(
            json.dumps({"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": {}})
        )
        assert req.method == "shutdown"

        resp = JSONRPCResponse.model_validate_json(
            json.dumps({"jsonrpc": "2.0", "id": 5, "result": "ok"})
        )
        assert resp.result == "ok"

    def test_stream_notifications(self):
        """api-spec Section 5.3: stream notification sequence."""
        message_start = JSONRPCNotification.model_validate_json(
            json.dumps({
                "jsonrpc": "2.0",
                "method": "stream/message_start",
                "params": {
                    "request_id": 3,
                    "message": {"id": "msg_01", "type": "message", "role": "assistant", "model": "claude-sonnet-4-6"},
                },
            })
        )
        assert message_start.method == "stream/message_start"
        assert message_start.params["request_id"] == 3

        delta = JSONRPCNotification.model_validate_json(
            json.dumps({
                "jsonrpc": "2.0",
                "method": "stream/content_block_delta",
                "params": {
                    "request_id": 3,
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello"},
                },
            })
        )
        assert delta.method == "stream/content_block_delta"
        assert delta.params["delta"]["text"] == "Hello"
        # notification is never a response
        assert "id" not in delta.model_dump()

    def test_cancelled_notification(self):
        """api-spec Section 6.3: cancelled notification."""
        notif = JSONRPCNotification.model_validate_json(
            json.dumps({
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"request_id": 3},
            })
        )
        assert notif.method == "notifications/cancelled"

    def test_parse_error_response(self):
        """api-spec Section 7: Parse Error response with null id."""
        resp = JSONRPCErrorResponse.model_validate_json(
            json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            })
        )
        assert resp.id is None
        assert resp.error.code == -32700


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:
    """Edge case tests for JSON-RPC types."""

    def test_request_with_large_id(self):
        """Request id can be up to 2^53-1 per api-spec."""
        large_id = 2**53 - 1
        req = JSONRPCRequest(id=large_id, method="ping")
        json_str = req.model_dump_json()
        parsed = JSONRPCRequest.model_validate_json(json_str)
        assert parsed.id == large_id

    def test_notification_without_params(self):
        """Notification without params is valid — exclude_none removes params."""
        notif = JSONRPCNotification(method="stream/ping")
        # Wire format (exclude_none=True) excludes None params
        json_str = notif.model_dump_json(exclude_none=True)
        data = json.loads(json_str)
        assert "params" not in data
        assert "id" not in data

    def test_response_result_with_nested_json(self):
        """Response result can contain deeply nested structures."""
        result = {
            "level1": {
                "level2": {
                    "level3": [{"key": "value"}, None, 42],
                },
            },
        }
        resp = JSONRPCResponse(id=1, result=result)
        json_str = resp.model_dump_json()
        parsed = JSONRPCResponse.model_validate_json(json_str)
        assert parsed.result["level1"]["level2"]["level3"][0]["key"] == "value"
        assert parsed.result["level1"]["level2"]["level3"][1] is None

    def test_error_with_empty_data(self):
        """Error data can be an empty dict."""
        err = JSONRPCError(code=-32603, message="Internal error", data={})
        json_str = err.model_dump_json()
        data = json.loads(json_str)
        assert data["data"] == {}
