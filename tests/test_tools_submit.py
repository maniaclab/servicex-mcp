"""Tests for servicex_submit_query."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from servicex_mcp.tools.submit import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestServicexSubmitQuery:
    async def test_submits_rucio_dataset_and_returns_request_id(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_query = MagicMock()
        mock_query.servicex.submit_transform = AsyncMock(return_value="req-123")
        mock_servicex_client.generic_query.return_value = mock_query

        fn = registered_tools["servicex_submit_query"]
        result = await fn(
            dataset="mc20_13TeV:mc20_13TeV.700320.deriv.DAOD_PHYS",
            dataset_kind="rucio",
            query="(call ResultTTree ...)",
            codegen="atlasr22",
            ctx=mock_ctx,
        )
        assert "req-123" in result
        mock_servicex_client.generic_query.assert_called_once()
        call_kwargs = mock_servicex_client.generic_query.call_args.kwargs
        assert call_kwargs["codegen"] == "atlasr22"

    async def test_rejects_unknown_dataset_kind(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["servicex_submit_query"]
        result = await fn(
            dataset="x", dataset_kind="not-a-kind", query="q", codegen="c", ctx=mock_ctx
        )
        assert result.startswith("Error:")

    async def test_read_only_mode_blocks_submission(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
    ) -> None:
        fn = registered_tools["servicex_submit_query"]
        result = await fn(
            dataset="x",
            dataset_kind="rucio",
            query="q",
            codegen="c",
            ctx=mock_ctx_readonly,
        )
        assert "read-only" in result.lower()

    async def test_returns_error_on_submit_failure(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_query = MagicMock()
        mock_query.servicex.submit_transform = AsyncMock(
            side_effect=ValueError("Invalid transform request: bad codegen")
        )
        mock_servicex_client.generic_query.return_value = mock_query
        fn = registered_tools["servicex_submit_query"]
        result = await fn(
            dataset="x", dataset_kind="rucio", query="q", codegen="c", ctx=mock_ctx
        )
        assert result.startswith("Error:")
