"""Tests for servicex_list_transforms, servicex_get_transform_status,
servicex_cancel_transform, and servicex_delete_transform."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.mcpserver import MCPServer
from servicex.models import TransformStatus

from servicex_mcp.tools.transforms import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
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
        "submit-time": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        "finish-time": datetime.datetime(2026, 1, 1, 1, tzinfo=datetime.timezone.utc),
        "log-url": "http://log",
    }
    fields.update(overrides)
    return TransformStatus(**fields)


class TestServicexListTransforms:
    async def test_returns_table(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.get_transforms_async = AsyncMock(
            return_value=[_make_transform_status(request_id="req-1")]
        )
        fn = registered_tools["servicex_list_transforms"]
        result = await fn(ctx=mock_ctx)
        assert "req-1" in result
        assert "Complete" in result
        assert "servicex_get_transform_status" in result

    async def test_empty_list_returns_message(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.get_transforms_async = AsyncMock(return_value=[])
        fn = registered_tools["servicex_list_transforms"]
        result = await fn(ctx=mock_ctx)
        assert result == "No transforms found."

    async def test_pagination_via_limit_and_offset(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        transforms = [_make_transform_status(request_id=f"req-{i}") for i in range(3)]
        mock_servicex_client.get_transforms_async = AsyncMock(return_value=transforms)
        fn = registered_tools["servicex_list_transforms"]
        result = await fn(limit=2, offset=0, ctx=mock_ctx)
        assert "req-0" in result
        assert "req-1" in result
        assert "req-2" not in result
        assert "offset=2" in result

        result_page_2 = await fn(limit=2, offset=2, ctx=mock_ctx)
        assert "req-2" in result_page_2
        assert "req-0" not in result_page_2

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.get_transforms_async = AsyncMock(
            side_effect=ConnectionError("unreachable")
        )
        fn = registered_tools["servicex_list_transforms"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")


class TestServicexGetTransformStatus:
    async def test_returns_detail(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.get_transform_status_async = AsyncMock(
            return_value=_make_transform_status(
                request_id="req-42", **{"files-completed": 5}
            )
        )
        fn = registered_tools["servicex_get_transform_status"]
        result = await fn(transform_id="req-42", ctx=mock_ctx)
        assert "req-42" in result
        assert "Complete" in result
        assert "servicex_cancel_transform" in result
        assert "servicex_delete_transform" in result

    async def test_returns_error_when_not_found(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.get_transform_status_async = AsyncMock(
            side_effect=ValueError("Transform req-missing not found")
        )
        fn = registered_tools["servicex_get_transform_status"]
        result = await fn(transform_id="req-missing", ctx=mock_ctx)
        assert result.startswith("Error:")


class TestServicexCancelTransform:
    async def test_cancels_transform(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.cancel_transform = MagicMock(return_value=None)
        fn = registered_tools["servicex_cancel_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx)
        assert "req-1" in result
        assert "cancelled" in result.lower()
        mock_servicex_client.cancel_transform.assert_called_once_with("req-1")

    async def test_read_only_mode_blocks_cancel(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        fn = registered_tools["servicex_cancel_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx_readonly)
        assert result == (
            "Error: server is running in read-only mode (--read-only flag). "
            "This operation modifies ServiceX state and is not permitted."
        )
        mock_servicex_client.cancel_transform.assert_not_called()

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.cancel_transform = MagicMock(
            side_effect=ValueError("Transform req-1 not found")
        )
        fn = registered_tools["servicex_cancel_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx)
        assert result.startswith("Error:")


class TestServicexDeleteTransform:
    async def test_deletes_transform(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.delete_transform = MagicMock(return_value=None)
        fn = registered_tools["servicex_delete_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx)
        assert "req-1" in result
        assert "deleted" in result.lower()
        mock_servicex_client.delete_transform.assert_called_once_with("req-1")

    async def test_read_only_mode_blocks_delete(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        fn = registered_tools["servicex_delete_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx_readonly)
        assert result == (
            "Error: server is running in read-only mode (--read-only flag). "
            "This operation modifies ServiceX state and is not permitted."
        )
        mock_servicex_client.delete_transform.assert_not_called()

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.delete_transform = MagicMock(
            side_effect=ValueError("Transform req-1 not found")
        )
        fn = registered_tools["servicex_delete_transform"]
        result = await fn(transform_id="req-1", ctx=mock_ctx)
        assert result.startswith("Error:")
