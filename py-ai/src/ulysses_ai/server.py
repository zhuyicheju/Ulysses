"""JSON-RPC 2.0 server over stdio transport.

Reads newline-delimited JSON requests from stdin, dispatches them to
registered handlers, and writes newline-delimited JSON responses to stdout.
Stderr is reserved exclusively for logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Awaitable, Callable
from pydantic import ValidationError

from ulysses_ai.protocol import (
    INVALID_REQUEST,
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
)

# Handler signature: async fn(params) -> result
Handler = Callable[[dict[str, Any] | None], Awaitable[Any]]

logger = logging.getLogger(__name__)


class RPCServer:
    """JSON-RPC 2.0 server using stdio for transport."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._write_lock: asyncio.Lock | None = None

    def register(self, method: str, handler: Handler) -> None:
        """Register a handler for the given method name."""
        self._handlers[method] = handler
        logger.debug("registered handler", extra={"method": method})

    async def serve_forever(self) -> None:
        """Read requests from stdin in a loop until EOF.

        Each request is handled concurrently via asyncio.create_task.
        Stdout writes are serialized via a lock to prevent interleaving.
        """
        logger.info("JSON-RPC server listening on stdin")
        self._write_lock = asyncio.Lock()
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break  # EOF — parent process closed stdin

            line = line.strip()
            if not line:
                continue

            asyncio.create_task(self._handle_line(line))

    def _write_response(self, response: JSONRPCResponse | JSONRPCErrorResponse) -> None:
        """Write a response to stdout as a single JSON line."""
        json_str = response.model_dump_json(exclude_none=True)
        # JSON-RPC spec requires `id` in all responses, even when null (parse errors)
        if isinstance(response, JSONRPCErrorResponse) and response.id is None:
            data = json.loads(json_str)
            data["id"] = None
            json_str = json.dumps(data)
        sys.stdout.write(json_str + "\n")
        sys.stdout.flush()

    async def _handle_line(self, line: str) -> None:
        """Parse a single JSON line and dispatch to the registered handler.

        Handles three cases:
        1. JSON-RPC Request (has id + method) → dispatch and write response
        2. JSON-RPC Notification (has method, no id) → dispatch only, no response
        3. Invalid message → write error response
        """
        logger.debug("received message", extra={"raw_line": line})

        # Try parsing as a Request (has id) first
        try:
            data = JSONRPCRequest.model_validate_json(line)
        except ValidationError as req_err:
            # Could be: invalid JSON, invalid request, or a notification (no id)
            is_json_error = any(
                err.get("type") == "json_invalid"
                for err in req_err.errors(include_url=False)
            )
            if is_json_error:
                logger.error("parse error", extra={"error": str(req_err)})
                self._write_response(
                    JSONRPCErrorResponse(
                        id=None,
                        error=JSONRPCError(
                            code=PARSE_ERROR,
                            message=f"Parse error: {req_err}",
                        ),
                    )
                )
                return

            # Not invalid JSON — try parsing as a Notification (method but no id)
            try:
                notif = JSONRPCNotification.model_validate_json(line)
            except ValidationError:
                # Neither a valid request nor a valid notification → Invalid Request
                logger.error("invalid request", extra={"error": str(req_err)})
                self._write_response(
                    JSONRPCErrorResponse(
                        id=None,
                        error=JSONRPCError(
                            code=INVALID_REQUEST,
                            message=f"Invalid request: {req_err}",
                        ),
                    )
                )
                return

            # It's a notification — dispatch without sending a response
            logger.debug(
                "dispatching notification",
                extra={"method": notif.method},
            )
            handler = self._handlers.get(notif.method)
            if handler is not None:
                try:
                    await handler(notif.params)
                except Exception as e:
                    logger.error(
                        "notification handler error",
                        extra={"method": notif.method, "error": str(e)},
                    )
            else:
                logger.debug(
                    "no handler for notification",
                    extra={"method": notif.method},
                )
            return

        # Valid Request — dispatch and write response
        req_id = data.id
        method = data.method
        params = data.params

        logger.debug("dispatching request", extra={"method": method, "id": req_id})

        handler = self._handlers.get(method)
        if handler is None:
            logger.warning("method not found", extra={"method": method})
            self._write_response(
                JSONRPCErrorResponse(
                    id=req_id,
                    error=JSONRPCError(
                        code=METHOD_NOT_FOUND,
                        message=f"Method not found: {method}",
                    ),
                )
            )
            return

        try:
            result = await handler(params)
            self._write_response(
                JSONRPCResponse(id=req_id, result=result)
            )
        except Exception as e:
            logger.error("handler error", extra={"method": method, "error": str(e)})
            self._write_response(
                JSONRPCErrorResponse(
                    id=req_id,
                    error=JSONRPCError(
                        code=INTERNAL_ERROR,
                        message=str(e),
                    )
                )
            )
