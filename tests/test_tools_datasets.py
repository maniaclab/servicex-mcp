"""Tests for servicex_list_datasets, servicex_get_dataset, and
servicex_delete_dataset."""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING, TypeVar
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer
from servicex.models import CachedDataset

from servicex_mcp.tools.datasets import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp.types import CallToolResult

_T = TypeVar("_T")


def _sync_facade_over_asyncio_run(return_value: _T) -> _T:
    """Mimic ServiceXClient.get_datasets/get_dataset/delete_dataset's real shape.

    All three are sync methods that internally call asyncio.run(...). Calling
    asyncio.run from within an already-running event loop (as any MCP tool
    coroutine does) raises RuntimeError, so a tool that calls these directly
    instead of via asyncio.to_thread would break against a real client. A
    plain MagicMock can't catch that regression; this side_effect reproduces
    the real failure mode so the happy-path tests actually exercise it.
    """

    async def _inner() -> _T:
        return return_value

    return asyncio.run(_inner())


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


def _make_cached_dataset(**overrides: object) -> CachedDataset:
    """Build a real CachedDataset, filling in required fields with defaults."""
    fields: dict[str, object] = {
        "id": 1,
        "name": "mc20_13TeV:mc20_13TeV.700320.deriv.DAOD_PHYS",
        "did_finder": "rucio",
        "n_files": 10,
        "size": 50_000_000_000_000,
        "events": 12345,
        "last_used": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        "last_updated": datetime.datetime(2026, 1, 1, 1, tzinfo=datetime.UTC),
        "lookup_status": "complete",
        "is_stale": False,
    }
    fields.update(overrides)
    return CachedDataset(**fields)


class TestServicexListDatasets:
    async def test_returns_table(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_datasets = MagicMock(
            side_effect=lambda *_a, **_kw: _sync_facade_over_asyncio_run(
                [_make_cached_dataset(id=1)]
            )
        )
        fn = registered_tools["servicex_list_datasets"]
        result = await fn(ctx=mock_ctx)
        text = tool_text(result)
        assert "mc20_13TeV" in text
        assert "45.47 TB" in text
        assert "12345" in text
        assert "servicex_get_dataset" in text
        assert result.structured_content is not None
        assert result.structured_content["datasets"][0]["id"] == 1
        assert result.structured_content["datasets"][0]["size"] == 50_000_000_000_000
        assert result.structured_content["truncated"] is False

    async def test_empty_list_returns_message(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_datasets = MagicMock(return_value=[])
        fn = registered_tools["servicex_list_datasets"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result) == "No datasets found."
        assert result.structured_content == {
            "datasets": [],
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
        datasets = [_make_cached_dataset(id=i, name=f"ds-{i}") for i in range(3)]
        mock_servicex_client.get_datasets = MagicMock(return_value=datasets)
        fn = registered_tools["servicex_list_datasets"]
        result = await fn(limit=2, offset=0, ctx=mock_ctx)
        text = tool_text(result)
        assert "ds-0" in text
        assert "ds-1" in text
        assert "ds-2" not in text
        assert "offset=2" in text
        assert result.structured_content is not None
        assert result.structured_content["truncated"] is True

        result_page_2 = await fn(limit=2, offset=2, ctx=mock_ctx)
        text_page_2 = tool_text(result_page_2)
        assert "ds-2" in text_page_2
        assert "ds-0" not in text_page_2

    async def test_passes_did_finder_and_show_deleted(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.get_datasets = MagicMock(return_value=[])
        fn = registered_tools["servicex_list_datasets"]
        await fn(did_finder="rucio", show_deleted=True, ctx=mock_ctx)
        mock_servicex_client.get_datasets.assert_called_once_with("rucio", True)

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_datasets = MagicMock(
            side_effect=ConnectionError("unreachable")
        )
        fn = registered_tools["servicex_list_datasets"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestServicexGetDataset:
    async def test_returns_detail(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_dataset = MagicMock(
            side_effect=lambda _id: _sync_facade_over_asyncio_run(
                _make_cached_dataset(id=42)
            )
        )
        fn = registered_tools["servicex_get_dataset"]
        result = await fn(dataset_id=42, ctx=mock_ctx)
        text = tool_text(result)
        assert "42" in text
        assert "45.47 TB" in text
        assert "servicex_delete_dataset" in text
        assert result.structured_content is not None
        assert result.structured_content["id"] == 42
        mock_servicex_client.get_dataset.assert_called_once_with(42)

    async def test_returns_error_when_not_found(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.get_dataset = MagicMock(
            side_effect=ValueError("Dataset 999 not found")
        )
        fn = registered_tools["servicex_get_dataset"]
        result = await fn(dataset_id=999, ctx=mock_ctx)
        text = tool_text(result)
        assert text.startswith("Error:")
        assert "not found" in text.lower()
        assert result.is_error is True


class TestServicexDeleteDataset:
    async def test_deletes_dataset(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.delete_dataset = MagicMock(
            side_effect=lambda _id: _sync_facade_over_asyncio_run(True)
        )
        fn = registered_tools["servicex_delete_dataset"]
        result = await fn(dataset_id=1, ctx=mock_ctx)
        text = tool_text(result)
        assert "1" in text
        assert "deleted" in text.lower()
        assert "stale=True" in text
        assert result.structured_content == {"dataset_id": 1, "stale": True}
        mock_servicex_client.delete_dataset.assert_called_once_with(1)

    async def test_read_only_mode_blocks_delete(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx_readonly: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["servicex_delete_dataset"]
        result = await fn(dataset_id=1, ctx=mock_ctx_readonly)
        assert tool_text(result) == (
            "Error: server is running in read-only mode (--read-only flag). "
            "This operation modifies ServiceX state and is not permitted."
        )
        assert result.is_error is True
        mock_servicex_client.delete_dataset.assert_not_called()

    async def test_returns_error_when_not_found(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_servicex_client.delete_dataset = MagicMock(
            side_effect=ValueError("Dataset 999 not found")
        )
        fn = registered_tools["servicex_delete_dataset"]
        result = await fn(dataset_id=999, ctx=mock_ctx)
        text = tool_text(result)
        assert text.startswith("Error:")
        assert "not found" in text.lower()
        assert result.is_error is True
