"""Tests for servicex_info and servicex_list_code_generators tools."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from servicex_mcp.tools.info import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp.types import CallToolResult


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestServicexInfo:
    async def test_returns_capabilities(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        info = MagicMock(
            app_version="3.1.0", capabilities=["poll_local_transformation_results"]
        )
        mock_servicex_client.servicex.get_servicex_info = MagicMock(
            return_value=_async_return(info)
        )
        fn = registered_tools["servicex_info"]
        result = await fn(ctx=mock_ctx)
        text = tool_text(result)
        assert "3.1.0" in text
        assert "poll_local_transformation_results" in text
        assert result.structured_content == {
            "app_version": "3.1.0",
            "capabilities": ["poll_local_transformation_results"],
        }

    async def test_no_capabilities_renders_none(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        info = MagicMock(app_version="3.1.0", capabilities=[])
        mock_servicex_client.servicex.get_servicex_info = MagicMock(
            return_value=_async_return(info)
        )
        fn = registered_tools["servicex_info"]
        result = await fn(ctx=mock_ctx)
        assert "(none)" in tool_text(result)
        assert result.structured_content is not None
        assert result.structured_content["capabilities"] == []

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        async def _raise() -> None:
            msg = "unreachable"
            raise ConnectionError(msg)

        mock_servicex_client.servicex.get_servicex_info = MagicMock(side_effect=_raise)
        fn = registered_tools["servicex_info"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestServicexListCodeGenerators:
    async def test_returns_generators(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_code_generators.return_value = {
            "uproot-raw": "sslhep/servicex_func_adl_uproot_codegen:v1",
            "python": "sslhep/servicex_generic_codegen:v1",
        }
        fn = registered_tools["servicex_list_code_generators"]
        result = await fn(ctx=mock_ctx)
        text = tool_text(result)
        assert "uproot-raw" in text
        assert "python" in text
        assert "servicex_submit_query" in text
        assert result.structured_content == {
            "generators": {
                "uproot-raw": "sslhep/servicex_func_adl_uproot_codegen:v1",
                "python": "sslhep/servicex_generic_codegen:v1",
            }
        }

    async def test_no_generators_returns_message(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_code_generators.return_value = {}
        fn = registered_tools["servicex_list_code_generators"]
        result = await fn(ctx=mock_ctx)
        assert (
            tool_text(result)
            == "No code generators are registered on this ServiceX instance."
        )
        assert result.structured_content == {"generators": {}}

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_code_generators.side_effect = RuntimeError("boom")
        fn = registered_tools["servicex_list_code_generators"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


def _async_return(value: object) -> object:
    async def _coro() -> object:
        return value

    return _coro()
