"""Tests for servicex_list_transforms, servicex_get_transform_status,
servicex_cancel_transform, and servicex_delete_transform."""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.mcpserver import MCPServer
from servicex.models import TransformStatus

from servicex_mcp.tools.transforms import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp.types import CallToolResult


def _sync_facade_over_asyncio_run() -> None:
    """Mimic ServiceXClient.cancel_transform/delete_transform's real shape.

    Both are sync methods that internally call asyncio.run(...). Calling
    asyncio.run from within an already-running event loop (as any MCP tool
    coroutine does) raises RuntimeError, so a tool that calls these
    directly instead of via asyncio.to_thread would break against a real
    client. A plain MagicMock can't catch that regression; this side_effect
    reproduces the real failure mode so the happy-path tests actually
    exercise it.
    """

    async def _inner() -> None:
        return None

    asyncio.run(_inner())


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


def _make_transform_status(**overrides: object) -> TransformStatus:
    """Build a real TransformStatus, filling in required fields with defaults.

    `TransformStatus` uses hyphenated `validation_alias`es (e.g. "tree-name")
    without `populate_by_name`, so aliased fields must be supplied via the
    hyphenated key rather than the Python attribute name.
    """
    fields: dict[str, object] = {
        "request_id": "req-1",
        "did": "rucio://mc20_13TeV:mc20_13TeV.700320",
        "did_id": 1,
        "title": "my query",
        "selection": "(call ResultTTree)",
        "tree-name": "tree",
        "image": "sslhep/servicex_func_adl_uproot_transformer:v1",
        "result-destination": "object-store",
        "result-format": "parquet",
        "generated-code-cm": "cm-name",
        "status": "Complete",
        "app-version": "3.1.0",
        "files": 10,
        "files-completed": 10,
        "files-failed": 0,
        "files-remaining": 0,
        "submit-time": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        "finish-time": datetime.datetime(2026, 1, 1, 1, tzinfo=datetime.UTC),
        "log-url": "http://log",
    }
    fields.update(overrides)
    return TransformStatus(**fields)


class TestServicexListTransforms:
    async def test_returns_table(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_transforms_async = AsyncMock(
            return_value=[_make_transform_status(request_id="req-1")]
        )
        fn = registered_tools["servicex_list_transforms"]
        result = await fn(ctx=mock_ctx)
        text = tool_text(result)
        assert "req-1" in text
        assert "Complete" in text
        assert "servicex_get_transform_status" in text
        assert result.structured_content is not None
        assert result.structured_content["transforms"][0]["request_id"] == "req-1"
        assert result.structured_content["truncated"] is False

    async def test_empty_list_returns_message(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_transforms_async = AsyncMock(return_value=[])
        fn = registered_tools["servicex_list_transforms"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result) == "No transforms found."
        assert result.structured_content == {
            "transforms": [],
            "offset": 0,
            "limit": 50,
            "truncated": False,
        }

    async def test_pagination_via_limit_and_offset(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        transforms = [_make_transform_status(request_id=f"req-{i}") for i in range(3)]
        mock_servicex_client.get_transforms_async = AsyncMock(return_value=transforms)
        fn = registered_tools["servicex_list_transforms"]
        result = await fn(limit=2, offset=0, ctx=mock_ctx)
        text = tool_text(result)
        assert "req-0" in text
        assert "req-1" in text
        assert "req-2" not in text
        assert "offset=2" in text
        assert result.structured_content is not None
        assert result.structured_content["truncated"] is True

        result_page_2 = await fn(limit=2, offset=2, ctx=mock_ctx)
        text_page_2 = tool_text(result_page_2)
        assert "req-2" in text_page_2
        assert "req-0" not in text_page_2

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_transforms_async = AsyncMock(
            side_effect=ConnectionError("unreachable")
        )
        fn = registered_tools["servicex_list_transforms"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestServicexGetTransformStatus:
    async def test_returns_detail(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_transform_status_async = AsyncMock(
            return_value=_make_transform_status(
                request_id="req-42", **{"files-completed": 5}
            )
        )
        fn = registered_tools["servicex_get_transform_status"]
        result = await fn(transform_id="req-42", ctx=mock_ctx)
        text = tool_text(result)
        assert "req-42" in text
        assert "Complete" in text
        assert "servicex_cancel_transform" in text
        assert "servicex_delete_transform" in text
        assert result.structured_content is not None
        assert result.structured_content["request_id"] == "req-42"
        assert result.structured_content["log_url"] == "http://log"

    async def test_returns_error_when_not_found(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_transform_status_async = AsyncMock(
            side_effect=ValueError("Transform req-missing not found")
        )
        fn = registered_tools["servicex_get_transform_status"]
        result = await fn(transform_id="req-missing", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestServicexCancelTransform:
    async def test_cancels_transform(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.cancel_transform = MagicMock(
            side_effect=lambda _transform_id: _sync_facade_over_asyncio_run()
        )
        fn = registered_tools["servicex_cancel_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx)
        text = tool_text(result)
        assert "req-1" in text
        assert "cancelled" in text.lower()
        assert result.structured_content == {"transform_id": "req-1"}
        mock_servicex_client.cancel_transform.assert_called_once_with("req-1")

    async def test_read_only_mode_blocks_cancel(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx_readonly: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["servicex_cancel_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx_readonly)
        assert tool_text(result) == (
            "Error: server is running in read-only mode (--read-only flag). "
            "This operation modifies ServiceX state and is not permitted."
        )
        assert result.is_error is True
        mock_servicex_client.cancel_transform.assert_not_called()

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.cancel_transform = MagicMock(
            side_effect=ValueError("Transform req-1 not found")
        )
        fn = registered_tools["servicex_cancel_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestServicexDeleteTransform:
    async def test_deletes_transform(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.delete_transform = MagicMock(
            side_effect=lambda _transform_id: _sync_facade_over_asyncio_run()
        )
        fn = registered_tools["servicex_delete_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx)
        text = tool_text(result)
        assert "req-1" in text
        assert "deleted" in text.lower()
        assert result.structured_content == {"transform_id": "req-1"}
        mock_servicex_client.delete_transform.assert_called_once_with("req-1")

    async def test_read_only_mode_blocks_delete(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx_readonly: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["servicex_delete_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx_readonly)
        assert tool_text(result) == (
            "Error: server is running in read-only mode (--read-only flag). "
            "This operation modifies ServiceX state and is not permitted."
        )
        assert result.is_error is True
        mock_servicex_client.delete_transform.assert_not_called()

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.delete_transform = MagicMock(
            side_effect=ValueError("Transform req-1 not found")
        )
        fn = registered_tools["servicex_delete_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True
