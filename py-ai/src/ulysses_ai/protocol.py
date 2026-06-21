"""JSON-RPC 2.0 type definitions.

Shared protocol types used by both the server and handlers.
Matches the types defined in Go at internal/rpc/types.go.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field


class JSONRPCRequest(BaseModel):
    """A JSON-RPC 2.0 request or notification.

    Notifications omit the `id` field and expect no response.
    """

    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] | None = None


class JSONRPCResponse(BaseModel):
    """A JSON-RPC 2.0 success response."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None = None
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


# Standard error codes
PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
LLM_RATE_LIMITED = -32000
LLM_CONTEXT_TOO_LONG = -32001
