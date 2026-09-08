"""Command-line interface for servicex-mcp."""

from __future__ import annotations

import argparse
import logging
import sys

from servicex_mcp.server import serve


def main() -> None:
    """Entry point for the servicex-mcp command."""
    parser = argparse.ArgumentParser(
        prog="servicex-mcp",
        description="MCP Server for ServiceX",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    serve_parser = subparsers.add_parser("serve", help="Start the MCP server")
    serve_parser.add_argument(
        "--read-only",
        action="store_true",
        default=False,
        help="Disable all write operations (submit/cancel/delete).",
    )
    serve_parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="Transport to use (default: stdio).",
    )
    serve_parser.add_argument(
        "--backend",
        default=None,
        metavar="NAME",
        help="Name of the ServiceX backend to use, as configured in your "
        ".servicex/servicex.yaml file (defaults to that file's default-endpoint).",
    )
    serve_parser.add_argument(
        "--config-path",
        default=None,
        metavar="PATH",
        help="Path to a .servicex/servicex.yaml file (default: search cwd upward, then $HOME).",
    )
    serve_parser.add_argument(
        "--log-level",
        default="info",
        choices=("debug", "info", "warning", "error"),
        help="Logging verbosity (default: info).",
    )

    args = parser.parse_args()

    if args.command == "serve":
        # basicConfig's default stream is stderr — this must stay that way:
        # stdio transport carries MCP's JSON-RPC framing on stdout, and any
        # log line written there would corrupt the protocol.
        logging.basicConfig(
            level=getattr(logging, args.log_level.upper()),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        if args.transport == "stdio":
            serve(
                backend=args.backend,
                config_path=args.config_path,
                read_only=args.read_only,
            )
        else:
            # HTTP transport is wired in a later task (cli http args) --
            # placeholder error until that task lands, so `--transport http`
            # fails loudly rather than silently starting stdio.
            sys.stderr.write("HTTP transport is not yet implemented.\n")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(0)
