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
    JSONRPCException,
    MODEL_NOT_AVAILABLE,
    RATE_LIMIT_EXCEEDED,
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
        # Detect context-length-exceeded via body type or message content
        body = getattr(e, "body", None)
        if body and isinstance(body, dict) and body.get("type") == "context_length_exceeded":
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


async def chat_stream(params: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Streaming chat completion.

    Expected params: same as chat.
    Returns a list of stream events; each chunk is also sent as a notification
    during streaming via stream/chunk.
    """
    # Phase 2.3.2: Implement streaming
    raise NotImplementedError("chat_stream not yet implemented")


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
    server.register("chat_stream", chat_stream)
    server.register("count_tokens", count_tokens)
