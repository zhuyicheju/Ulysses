"""JSON-RPC 2.0 server over stdio transport.

Reads newline-delimited JSON requests from stdin, dispatches them to
registered handlers, and writes newline-delimited JSON responses to stdout.
Stderr is reserved exclusively for logging.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Awaitable, Callable
from pydantic import ValidationError

from ulysses_ai.protocol import (
    INVALID_REQUEST,
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCRequest,
    JSONRPCResponse,
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
)

# Handler signature: async fn(params) -> result
Handler = Callable[[dict[str, Any] | None], Awaitable[Any]]


class RPCServer:
    """JSON-RPC 2.0 server using stdio for transport."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, method: str, handler: Handler) -> None:
        """Register a handler for the given method name."""
        self._handlers[method] = handler

    async def serve_forever(self) -> None:
        """Read requests from stdin in a loop until EOF."""
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break  # EOF — parent process closed stdin

            line = line.strip()
            if not line:
                continue

            await self._handle_line(line)

    def _write_response(self, response: JSONRPCResponse | JSONRPCErrorResponse) -> None:
        """Write a response to stdout as a single JSON line."""
        sys.stdout.write(response.model_dump_json(exclude_none=True) + "\n")
        sys.stdout.flush()

    async def _handle_line(self, line: str) -> None:
        """Parse a single JSON line and dispatch to the registered handler."""
        # Parse the request
        try:
            data = JSONRPCRequest.model_validate_json(line)
        except json.JSONDecodeError as e:
            self._write_response(
                JSONRPCErrorResponse(
                    error=JSONRPCError(
                        code=PARSE_ERROR,
                        message=f"Invalid JSON: {e}",
                    )
                )
            )
            return
        except ValidationError as e:
            self._write_response(
                JSONRPCErrorResponse(
                    error=JSONRPCError(
                        code=INVALID_REQUEST,
                        message=f"Invalid request: {e}",
                    ),
                    id=None
                )
            )
            return

        req_id = data.get("id")
        method = data.get("method")
        params = data.get("params")

        # Find and invoke the handler
        handler = self._handlers.get(method)
        if handler is None:
            self._write_response(
                JSONRPCErrorResponse(
                    id=req_id,
                    error=JSONRPCError(
                        code=METHOD_NOT_FOUND,
                        message=f"Method not found: {method}",
                    )
                )
            )
            return

        try:
            result = await handler(params)
            self._write_response(
                JSONRPCResponse(id=req_id, result=result)
            )
        except Exception as e:
            self._write_response(
                JSONRPCErrorResponse(
                    id=req_id,
                    error=JSONRPCError(
                        code=INTERNAL_ERROR,
                        message=str(e),
                    )
                )
            )
