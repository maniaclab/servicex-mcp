"""Tests for servicex_info and servicex_list_code_generators tools."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from servicex_mcp.tools.info import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestServicexInfo:
    async def test_returns_capabilities(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        info = MagicMock(
            app_version="3.1.0", capabilities=["poll_local_transformation_results"]
        )
        mock_servicex_client.servicex.get_servicex_info = MagicMock(
            return_value=_async_return(info)
        )
        fn = registered_tools["servicex_info"]
        result = await fn(ctx=mock_ctx)
        assert "3.1.0" in result

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        async def _raise() -> None:
            msg = "unreachable"
            raise ConnectionError(msg)

        mock_servicex_client.servicex.get_servicex_info = MagicMock(side_effect=_raise)
        fn = registered_tools["servicex_info"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")


class TestServicexListCodeGenerators:
    async def test_returns_generators(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.get_code_generators.return_value = {
            "uproot-raw": "sslhep/servicex_func_adl_uproot_codegen:v1",
            "python": "sslhep/servicex_generic_codegen:v1",
        }
        fn = registered_tools["servicex_list_code_generators"]
        result = await fn(ctx=mock_ctx)
        assert "uproot-raw" in result

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.get_code_generators.side_effect = RuntimeError("boom")
        fn = registered_tools["servicex_list_code_generators"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")


def _async_return(value: object) -> object:
    async def _coro() -> object:
        return value

    return _coro()
