"""LLM client methods.

Handlers for the `chat`, `chat_stream`, and `count_tokens` JSON-RPC methods.
These are called by the Go runtime through the stdio bridge.

The `chat` handler uses the Anthropic Python SDK (AsyncAnthropic) to call
the Messages API. A module-level singleton client is lazily created on the
first request and reused for connection pooling.

Error handling: Anthropic SDK exceptions are caught and re-raised as
JSONRPCException with the appropriate JSON-RPC error codes, per the
API specification.
"""

from __future__ import annotations

import logging
from typing import Any

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
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
    JSONRPCException,
)

logger = logging.getLogger(__name__)

# Module-level Anthropic async client (lazily initialized singleton)
_client: AsyncAnthropic | None = None
_base_url: str | None = None
_api_key: str | None = None

# Recognized optional params that map directly to messages.create() kwargs
_OPTIONAL_PARAMS = frozenset({
    "system",
    "tools",
    "temperature",
    "top_p",
    "top_k",
    "stop_sequences",
    "tool_choice",
    "thinking",
    "metadata",
})


def configure(base_url: str | None = None, api_key: str | None = None) -> None:
    """Configure connection parameters for the Anthropic client.

    Must be called before the first chat request. Parameters are stored
    as module globals and used when lazily creating the client.
    """
    global _base_url, _api_key
    _base_url = base_url
    _api_key = api_key


def _get_client() -> AsyncAnthropic:
    """Return the shared AsyncAnthropic client, creating it if necessary."""
    global _client
    if _client is None:
        logger.info(
            "creating Anthropic client",
            extra={"base_url": _base_url or "default"},
        )
        _client = AsyncAnthropic(
            api_key=_api_key,
            base_url=_base_url,
        )
    return _client


async def ping(params: dict[str, Any] | None) -> str:
    """Health check — returns 'pong'."""
    return "pong"


async def chat(params: dict[str, Any] | None) -> dict[str, Any]:
    """Non-streaming chat completion via Anthropic Messages API.

    Params directly mirror the Anthropic messages.create() arguments.
    Result is the Anthropic Message object serialized to a dict with
    exclude_none=True.

    Raises JSONRPCException with appropriate error codes for:
    - Missing/invalid params (INVALID_PARAMS, -32602)
    - Auth failures (AUTH_ERROR, -32002)
    - Rate limits (RATE_LIMIT_EXCEEDED, -32000)
    - Context length exceeded (CONTEXT_LENGTH_EXCEEDED, -32001)
    - Timeout/connection errors (API_TIMEOUT, -32003)
    - Model not found (MODEL_NOT_AVAILABLE, -32004)
    """
    if params is None:
        raise JSONRPCException(INVALID_PARAMS, "params is required")

    model = params.get("model")
    if not model:
        raise JSONRPCException(INVALID_PARAMS, "model is required")

    messages = params.get("messages")
    if not messages:
        raise JSONRPCException(INVALID_PARAMS, "messages is required")

    max_tokens = params.get("max_tokens")
    if max_tokens is None:
        raise JSONRPCException(INVALID_PARAMS, "max_tokens is required")

    client = _get_client()

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    # Forward optional params (only if present in the request)
    for key in _OPTIONAL_PARAMS:
        if key in params:
            kwargs[key] = params[key]

    try:
        response = await client.messages.create(**kwargs)
    except RateLimitError as e:
        raise JSONRPCException(
            RATE_LIMIT_EXCEEDED,
            "Rate limit exceeded",
            data={"type": "RateLimitError", "detail": str(e)},
        ) from e
    except AuthenticationError as e:
        raise JSONRPCException(
            AUTH_ERROR,
            "Authentication failed",
            data={"type": "AuthenticationError", "detail": str(e)},
        ) from e
    except PermissionDeniedError as e:
        raise JSONRPCException(
            AUTH_ERROR,
            "Permission denied",
            data={"type": "PermissionDeniedError", "detail": str(e)},
        ) from e
    except BadRequestError as e:
        body = getattr(e, "body", None)
        if body and isinstance(body, dict):
            error_obj = body.get("error", {})
            if isinstance(error_obj, dict) and error_obj.get("type") == "context_length_exceeded":
                raise JSONRPCException(
                    CONTEXT_LENGTH_EXCEEDED,
                    "Context length exceeded",
                    data={"type": "BadRequestError", "detail": str(e)},
                ) from e
        err_msg = str(e).lower()
        if any(kw in err_msg for kw in ("context", "too long", "too large")):
            raise JSONRPCException(
                CONTEXT_LENGTH_EXCEEDED,
                "Context length exceeded",
                data={"type": "BadRequestError", "detail": str(e)},
            ) from e
        raise JSONRPCException(
            INVALID_PARAMS,
            f"Invalid parameters: {e}",
            data={"type": "BadRequestError", "detail": str(e)},
        ) from e
    except NotFoundError as e:
        raise JSONRPCException(
            MODEL_NOT_AVAILABLE,
            f"Model not available: {e}",
            data={"type": "NotFoundError", "detail": str(e)},
        ) from e
    except APITimeoutError as e:
        raise JSONRPCException(
            API_TIMEOUT,
            "API request timed out",
            data={"type": "APITimeoutError", "detail": str(e)},
        ) from e
    except APIConnectionError as e:
        raise JSONRPCException(
            API_TIMEOUT,
            "API connection error",
            data={"type": "APIConnectionError", "detail": str(e)},
        ) from e
    except InternalServerError as e:
        raise JSONRPCException(
            INTERNAL_ERROR,
            f"Anthropic API internal error: {e}",
            data={"type": "InternalServerError", "detail": str(e)},
        ) from e
    except APIStatusError as e:
        # Catch-all for other HTTP-level errors not covered above
        raise JSONRPCException(
            INTERNAL_ERROR,
            f"API error (HTTP {e.status_code}): {e}",
            data={"type": "APIStatusError", "detail": str(e)},
        ) from e

    # Anthropic SDK response models are Pydantic v2 BaseModel subclasses.
    # Serialize to dict excluding None fields for a cleaner JSON-RPC result.
    return response.model_dump(exclude_none=True)


async def chat_stream(
    params: dict[str, Any] | None,
    send_notification: Any = None,
) -> dict[str, Any]:
    """Streaming chat completion via Anthropic Messages streaming API.

    Maps Anthropic SSE events to JSON-RPC notifications emitted via
    *send_notification*. Returns a final result with ``status``.

    Phase 1 errors (validation failures, auth errors before any event is
    emitted) are raised as :class:`JSONRPCException` so the server produces a
    standard JSON-RPC error response.

    Phase 2 errors (connection lost during streaming, after at least one
    event has been sent) produce a ``stream/error`` notification followed
    by a final response with ``status: "error"``.
    """
    if send_notification is None:
        raise RuntimeError("chat_stream handler requires send_notification")

    # --- Phase 1: validation (same rules as ``chat``) -----------------------
    if params is None:
        raise JSONRPCException(INVALID_PARAMS, "params is required")

    model = params.get("model")
    if not model:
        raise JSONRPCException(INVALID_PARAMS, "model is required")

    messages = params.get("messages")
    if not messages:
        raise JSONRPCException(INVALID_PARAMS, "messages is required")

    max_tokens = params.get("max_tokens")
    if max_tokens is None:
        raise JSONRPCException(INVALID_PARAMS, "max_tokens is required")

    client = _get_client()

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    for key in _OPTIONAL_PARAMS:
        if key in params:
            kwargs[key] = params[key]

    # --- Phase 2: stream and map events to notifications --------------------
    any_event_sent = False
    try:
        async with client.messages.stream(**kwargs) as stream:
            async for event in stream:
                await _handle_stream_event(event, send_notification)
                any_event_sent = True
    except JSONRPCException:
        # Validation errors raised by _handle_stream_event pass through.
        raise
    except Exception as exc:
        error_code, error_message = _map_api_error(exc)
        if not any_event_sent:
            # Phase 1: no events sent → standard JSON-RPC error response.
            raise JSONRPCException(
                error_code, error_message,
                data={"type": type(exc).__name__, "detail": str(exc)},
            ) from exc
        # Phase 2: some events already sent → notify Go side of the error.
        logger.warning(
            "stream error after events sent",
            extra={"code": error_code, "err_msg": error_message},
        )
        await send_notification("stream/error", {
            "code": error_code,
            "message": error_message,
        })
        return {
            "status": "error",
            "error": {"code": error_code, "message": error_message},
        }

    return {"status": "completed"}


async def _handle_stream_event(
    event: Any,
    send_notification: Any,
) -> None:
    """Map a single Anthropic RawMessageStreamEvent to a JSON-RPC notification.

    Uses ``model_dump(exclude_none=True)`` for SDK event objects and falls
    back to plain dict access so that the same code works with mocks.
    """
    event_type = event.type

    if event_type == "message_start":
        msg = event.message
        if not isinstance(msg, dict):
            msg = msg.model_dump(exclude_none=True)
        await send_notification("stream/message_start", {
            "message": {
                "id": msg["id"],
                "type": msg["type"],
                "role": msg["role"],
                "model": msg["model"],
            },
        })

    elif event_type == "content_block_start":
        block = event.content_block
        if not isinstance(block, dict):
            block = block.model_dump(exclude_none=True)
        await send_notification("stream/content_block_start", {
            "index": event.index,
            "content_block": block,
        })

    elif event_type == "content_block_delta":
        delta = event.delta
        if not isinstance(delta, dict):
            delta = delta.model_dump(exclude_none=True)
        await send_notification("stream/content_block_delta", {
            "index": event.index,
            "delta": delta,
        })

    elif event_type == "content_block_stop":
        await send_notification("stream/content_block_stop", {
            "index": event.index,
        })

    elif event_type == "message_delta":
        delta = event.delta
        if not isinstance(delta, dict):
            delta = delta.model_dump(exclude_none=True)
        usage = event.usage
        if not isinstance(usage, dict):
            usage = usage.model_dump(exclude_none=True)
        await send_notification("stream/message_delta", {
            "delta": delta,
            "usage": usage,
        })

    elif event_type == "message_stop":
        await send_notification("stream/message_stop", {})

    elif event_type == "ping":
        # Optional heartbeat — Go side ignores these.
        pass

    else:
        logger.debug("unknown stream event type", extra={"type": event_type})


def _map_api_error(exc: Exception) -> tuple[int, str]:
    """Map an Anthropic SDK exception to (error_code, error_message).

    Same mapping as the ``except`` blocks in :func:`chat`, but returns
    values instead of raising.
    """
    if isinstance(exc, RateLimitError):
        return RATE_LIMIT_EXCEEDED, "Rate limit exceeded"
    if isinstance(exc, AuthenticationError):
        return AUTH_ERROR, "Authentication failed"
    if isinstance(exc, PermissionDeniedError):
        return AUTH_ERROR, "Permission denied"
    if isinstance(exc, BadRequestError):
        body = getattr(exc, "body", None)
        if body and isinstance(body, dict):
            error_obj = body.get("error", {}) if isinstance(body.get("error"), dict) else {}
            if error_obj.get("type") == "context_length_exceeded":
                return CONTEXT_LENGTH_EXCEEDED, "Context length exceeded"
        err_msg = str(exc).lower()
        if any(kw in err_msg for kw in ("context", "too long", "too large")):
            return CONTEXT_LENGTH_EXCEEDED, "Context length exceeded"
        return INVALID_PARAMS, f"Invalid parameters: {exc}"
    if isinstance(exc, NotFoundError):
        return MODEL_NOT_AVAILABLE, f"Model not available: {exc}"
    if isinstance(exc, APITimeoutError):
        return API_TIMEOUT, "API request timed out"
    if isinstance(exc, APIConnectionError):
        return API_TIMEOUT, "API connection error"
    if isinstance(exc, InternalServerError):
        return INTERNAL_ERROR, f"Anthropic API internal error: {exc}"
    if isinstance(exc, APIStatusError):
        return INTERNAL_ERROR, f"API error (HTTP {exc.status_code}): {exc}"
    return INTERNAL_ERROR, str(exc)


async def count_tokens(params: dict[str, Any] | None) -> dict[str, Any]:
    """Count tokens for the given messages.

    Expected params: {model, messages}
    Returns: {count}
    """
    # Phase 2: Implement with tiktoken or similar
    raise NotImplementedError("count_tokens not yet implemented")


def register_all(
    server: Any,
    base_url: str | None = None,
    api_key: str | None = None,
) -> None:
    """Register all LLM-related handlers with the server.

    Args:
        server: The RPCServer instance.
        base_url: Optional Anthropic API base URL override.
        api_key: Optional Anthropic API key (overrides ANTHROPIC_API_KEY env).
    """
    configure(base_url=base_url, api_key=api_key)
    server.register("ping", ping)
    server.register("chat", chat)

    # chat_stream needs send_notification — wrap in closure for safety.
    async def _chat_stream_handler(
        params: dict[str, Any] | None,
        send_notification: Any = None,
    ) -> dict[str, Any]:
        return await chat_stream(params, send_notification)

    server.register("chat_stream", _chat_stream_handler)
    server.register("count_tokens", count_tokens)
