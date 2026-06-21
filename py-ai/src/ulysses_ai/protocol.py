"""JSON-RPC 2.0 type definitions.

Shared protocol types used by both the server and handlers.
Matches the types defined in Go at internal/rpc/types.go.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field


class JSONRPCRequest(BaseModel):
    """A JSON-RPC 2.0 request
    """

    jsonrpc: Literal["2.0"] = "2.0"
    id: int
    method: str
    params: dict[str, Any] | None = None


class JSONRPCResponse(BaseModel):
    """A JSON-RPC 2.0 success response."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: int
    result: Any = None


class JSONRPCError(BaseModel):
    """A JSON-RPC 2.0 error object."""

    code: int
    message: str
    data: Any = None


class JSONRPCErrorResponse(BaseModel):
    """A JSON-RPC 2.0 error response."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None = None
    error: JSONRPCError


class JSONRPCNotification(BaseModel):
    """A JSON-RPC 2.0 notification (no id, no response expected)."""

    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: dict[str, Any] | None = None


# Union type for anything that can arrive on the wire
JSONRPCMessage = Union[JSONRPCRequest, JSONRPCResponse, JSONRPCErrorResponse, JSONRPCNotification]


PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
RATE_LIMIT_EXCEEDED = -32000
CONTEXT_LENGTH_EXCEEDED = -32001
AUTH_ERROR = -32002
API_TIMEOUT = -32003
MODEL_NOT_AVAILABLE = -32004
