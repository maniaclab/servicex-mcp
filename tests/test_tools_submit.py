"""Tests for servicex_submit_query."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.mcpserver import MCPServer
from servicex.dataset_identifier import (
    CERNOpenDataDatasetIdentifier,
    FileListDataset,
    RucioDatasetIdentifier,
    XRootDDatasetIdentifier,
)

from servicex_mcp.tools.submit import _build_dataset_identifier, register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class TestBuildDatasetIdentifier:
    def test_rucio(self) -> None:
        dsid = _build_dataset_identifier(
            "mc20_13TeV:mc20_13TeV.700320.deriv.DAOD_PHYS", "rucio", None
        )
        assert isinstance(dsid, RucioDatasetIdentifier)
        assert dsid.dataset == "mc20_13TeV:mc20_13TeV.700320.deriv.DAOD_PHYS"

    def test_rucio_passes_num_files(self) -> None:
        dsid = _build_dataset_identifier("ns:name", "rucio", 5)
        assert isinstance(dsid, RucioDatasetIdentifier)
        assert dsid.num_files == 5

    def test_file_list_splits_on_comma(self) -> None:
        dsid = _build_dataset_identifier(
            "root://a.root,root://b.root", "file_list", None
        )
        assert isinstance(dsid, FileListDataset)
        assert dsid.files == ["root://a.root", "root://b.root"]

    def test_file_list_strips_whitespace_around_entries(self) -> None:
        # A natural "a, b" list (comma + space) must not bake a leading
        # space into the second URI — that would silently fail only that
        # one file at transform time instead of raising here.
        dsid = _build_dataset_identifier(
            "root://a.root, root://b.root", "file_list", None
        )
        assert isinstance(dsid, FileListDataset)
        assert dsid.files == ["root://a.root", "root://b.root"]

    def test_xrootd(self) -> None:
        dsid = _build_dataset_identifier("root://*/data*.root", "xrootd", 10)
        assert isinstance(dsid, XRootDDatasetIdentifier)
        assert dsid.dataset == "root://*/data*.root"
        assert dsid.num_files == 10

    def test_cernopendata(self) -> None:
        dsid = _build_dataset_identifier("12345", "cernopendata", None)
        assert isinstance(dsid, CERNOpenDataDatasetIdentifier)
        assert dsid.dataset == "12345"

    def test_unknown_kind_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown dataset_kind"):
            _build_dataset_identifier("x", "not-a-kind", None)


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

    async def test_rejects_unknown_result_format(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["servicex_submit_query"]
        result = await fn(
            dataset="ns:name",
            dataset_kind="rucio",
            query="q",
            codegen="c",
            result_format="xml",
            ctx=mock_ctx,
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
