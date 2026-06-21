"""LLM client methods.

Handlers for the `chat`, `chat_stream`, and `count_tokens` JSON-RPC methods.
These are called by the Go runtime through the stdio bridge.

TODO (Phase 2): Implement actual LLM API calls using the `openai` SDK.
"""

from __future__ import annotations

from typing import Any


async def ping(params: dict[str, Any] | None) -> str:
    """Health check — returns 'pong'."""
    return "pong"


async def chat(params: dict[str, Any] | None) -> dict[str, Any]:
    """Non-streaming chat completion.

    Expected params: {model, messages, tools?, max_tokens?, temperature?}
    Returns: {content, tool_calls?, usage}
    """
    # Phase 2: Implement with openai SDK
    raise NotImplementedError("chat not yet implemented")


async def chat_stream(params: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Streaming chat completion.

    Expected params: same as chat.
    Returns a list of stream events; each chunk is also sent as a notification
    during streaming via stream/chunk.
    """
    # Phase 2: Implement with openai SDK
    raise NotImplementedError("chat_stream not yet implemented")


async def count_tokens(params: dict[str, Any] | None) -> dict[str, Any]:
    """Count tokens for the given messages.

    Expected params: {model, messages}
    Returns: {count}
    """
    # Phase 2: Implement with tiktoken or similar
    raise NotImplementedError("count_tokens not yet implemented")


def register_all(server: Any) -> None:
    """Register all LLM-related handlers with the server."""
    server.register("ping", ping)
    server.register("chat", chat)
    server.register("chat_stream", chat_stream)
    server.register("count_tokens", count_tokens)
