"""Entry point for the Ulysses AI Python process.

Invoked by the Go runtime via:
    python -m ulysses_ai [--model MODEL] [--base-url URL] [--api-key KEY]

When run with --version, prints the version and exits.
Otherwise starts the JSON-RPC over stdio server loop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys

from ulysses_ai import __version__
from ulysses_ai.logging import setup_logging
from ulysses_ai.server import RPCServer
from ulysses_ai.protocol import INTERNAL_ERROR
from ulysses_ai.handlers.llm import register_all


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ulysses-ai",
        description="Ulysses AI — Python LLM bridge",
    )
    parser.add_argument(
        "--version", action="store_true", help="print version and exit"
    )
    parser.add_argument(
        "--model", default=None, help="default model name"
    )
    parser.add_argument(
        "--base-url", default=None, help="LLM API base URL"
    )
    parser.add_argument(
        "--api-key", default=None, help="LLM API key"
    )
    parser.add_argument(
        "--log-level", default="info",
        choices=["debug", "info", "warn", "error"],
        help="log level (default: info)"
    )
    parser.add_argument(
        "--log-format", default="json",
        choices=["json", "text"],
        help="log output format (default: json)"
    )
    args = parser.parse_args()

    if args.version:
        print(f"ulysses-ai {__version__}")
        sys.exit(0)

    try:
        # Initialize structured logging before anything else.
        setup_logging(level=args.log_level, fmt=args.log_format)
        logger = logging.getLogger(__name__)
        logger.info("starting ulysses-ai JSON-RPC server",
                    extra={"log_level": args.log_level, "log_format": args.log_format})

        # Start the JSON-RPC over stdio server loop.
        # Use an explicit event loop so we can register a SIGTERM handler
        # for graceful shutdown — completing in-flight requests before exiting.
        server = RPCServer()
        register_all(
            server,
            base_url=args.base_url,
            api_key=args.api_key,
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.add_signal_handler(signal.SIGTERM, server.shutdown)
        try:
            loop.run_until_complete(server.serve_forever())
        finally:
            loop.close()
    except Exception:
        # Log the full traceback if the logging system is available.
        # If logging itself failed, the inner try/except prevents a second error.
        try:
            logging.getLogger(__name__).exception(
                "fatal error during server startup or runtime"
            )
        except Exception:
            pass
        # Always attempt to write a JSON-RPC error response to stdout
        # so the caller receives a valid protocol response.
        try:
            error_response = json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": INTERNAL_ERROR,
                    "message": "Internal error",
                },
            })
            sys.stdout.write(error_response + "\n")
            sys.stdout.flush()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
