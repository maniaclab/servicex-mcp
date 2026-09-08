"""FastMCP server setup for servicex-mcp (stdio transport)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer
from servicex.servicex_client import ServiceXClient

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from servicex_mcp.auth.factory import EnvBasedClientFactory
from servicex_mcp.tools import datasets, info, submit, transforms

_STDIO_PREAMBLE = (
    "MCP server for ServiceX data delivery. "
    "Provides tools to discover code generators, submit transform (query) "
    "requests against a dataset, and inspect/manage transforms and cached "
    "datasets. Authentication is configured via a local .servicex/servicex.yaml "
    "file (selected with --backend) before starting the server."
)


def _make_stdio_mcp(
    *,
    backend: str | None = None,
    config_path: str | None = None,
    read_only: bool = False,
) -> MCPServer:
    """Build and return a configured MCPServer instance for stdio transport."""

    @asynccontextmanager
    async def _lifespan(_server: MCPServer) -> AsyncGenerator[dict[str, Any], None]:
        client = ServiceXClient(backend=backend, config_path=config_path)
        factory = EnvBasedClientFactory(client=client)
        try:
            yield {"client_factory": factory, "read_only": read_only}
        finally:
            factory.close()

    mcp = MCPServer("servicex-mcp", lifespan=_lifespan, instructions=_STDIO_PREAMBLE)

    for _module in [info, transforms, datasets, submit]:
        _module.register(mcp)

    return mcp


def serve(*, backend: str | None, config_path: str | None, read_only: bool) -> None:
    """Entry point used by the CLI's `serve` subcommand (stdio only, for now)."""
    mcp = _make_stdio_mcp(backend=backend, config_path=config_path, read_only=read_only)
    mcp.run(transport="stdio")
