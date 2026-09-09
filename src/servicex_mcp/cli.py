"""Command-line interface for servicex-mcp."""

from __future__ import annotations

import argparse
import logging
import sys

from servicex_mcp.server import serve, serve_http


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
    serve_parser.add_argument(
        "--backend-url",
        default=None,
        metavar="URL",
        help="Base URL of the ServiceX deployment (required for --transport http).",
    )
    serve_parser.add_argument(
        "--resource-url",
        default=None,
        metavar="URL",
        help="Public URL of this MCP server (required for --transport http).",
    )
    serve_parser.add_argument(
        "--broker-url",
        default=None,
        metavar="URL",
        help="Base URL of an AF MCP broker (maniaclab/af-mcp-platform). When "
        "set, --transport http runs in broker mode: clients authenticate "
        "with an AF Broker Identity Token (not a ServiceX personal refresh "
        "token), redeemed for a ServiceX access token via the broker's "
        "POST /v1/credentials/servicex/redeem. Requires "
        "maniaclab/af-mcp-platform's ServiceXTokenProvider (issue #295).",
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument(
        "--cache-dir", default="/tmp/servicex_mcp_cache", metavar="PATH"
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
            if not args.backend_url or not args.resource_url:
                parser.error(
                    "--transport http requires --backend-url and --resource-url"
                )

            serve_http(
                backend_url=args.backend_url,
                resource_url=args.resource_url,
                broker_url=args.broker_url,
                host=args.host,
                port=args.port,
                read_only=args.read_only,
                cache_dir=args.cache_dir,
                log_level=args.log_level,
            )
    else:
        parser.print_help()
        sys.exit(0)
