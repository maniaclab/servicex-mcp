"""Tools for ServiceX server connectivity and code generator discovery."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002

from servicex_mcp.tools._helpers import build_hints, classify_error, get_servicex_client


def register(mcp: MCPServer) -> None:
    """Register info tools with the MCP server."""

    @mcp.tool()
    async def servicex_info(*, ctx: Context[Any, Any]) -> str:
        """Return the ServiceX server version and its advertised capabilities.

        Use this tool to verify the ServiceX backend is reachable and to see
        which optional server capabilities are available (e.g. whether
        long sample titles or local-transform polling are supported).
        """
        client = get_servicex_client(ctx)
        try:
            info = await client.servicex.get_servicex_info()
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        lines = [
            f"- **app_version:** {info.app_version}",
            f"- **capabilities:** {', '.join(info.capabilities) or '(none)'}",
        ]
        hints = build_hints(
            ["Use `servicex_list_code_generators` to see available codegens"]
        )
        return "\n".join(lines) + hints

    @mcp.tool()
    async def servicex_list_code_generators(*, ctx: Context[Any, Any]) -> str:
        """List the code generators deployed on this ServiceX instance.

        Each code generator (e.g. `func_adl_uproot`, `python`, `uproot-raw`)
        maps to a query language you can use with `servicex_submit_query`.
        """
        client = get_servicex_client(ctx)
        try:
            generators = client.get_code_generators()
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        if not generators:
            return "No code generators are registered on this ServiceX instance."
        lines = [f"- **{name}:** {image}" for name, image in generators.items()]
        hints = build_hints(
            ["Use `servicex_submit_query` with one of these codegen names"]
        )
        return "\n".join(lines) + hints
