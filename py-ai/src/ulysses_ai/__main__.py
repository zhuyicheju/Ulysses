"""Entry point for the Ulysses AI Python process.

Invoked by the Go runtime via:
    python -m ulysses_ai [--model MODEL] [--base-url URL] [--api-key KEY]

When run with --version, prints the version and exits.
Otherwise starts the JSON-RPC over stdio server loop.
"""

import argparse
import sys

from ulysses_ai import __version__


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
    args = parser.parse_args()

    if args.version:
        print(f"ulysses-ai {__version__}")
        sys.exit(0)

    # TODO (Phase 2): start JSON-RPC over stdio server loop
    print("ulysses-ai: JSON-RPC server not yet implemented", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
