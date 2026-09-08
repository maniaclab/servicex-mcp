"""Tests for _make_stdio_mcp."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from servicex_mcp.server import _make_stdio_mcp

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def _enter_lifespan(mcp: MCPServer) -> AbstractAsyncContextManager[dict[str, Any]]:
    # mcp.settings.lifespan is typed Optional even though _make_stdio_mcp
    # always sets it; narrow it here so callers don't repeat the assert.
    assert mcp.settings.lifespan is not None
    return mcp.settings.lifespan(mcp)


class TestMakeStdioMcp:
    def test_registers_expected_tools(self) -> None:
        with patch("servicex_mcp.server.ServiceXClient"):
            mcp = _make_stdio_mcp(backend="test-backend")
        names = {tool.name for tool in mcp._tool_manager.list_tools()}
        # Exact set, not membership: a future tool module registered but
        # left off this list (or a duplicate/typo'd name colliding across
        # modules) should fail this test loudly, not silently pass.
        assert names == {
            "servicex_info",
            "servicex_list_code_generators",
            "servicex_list_transforms",
            "servicex_get_transform_status",
            "servicex_cancel_transform",
            "servicex_delete_transform",
            "servicex_list_datasets",
            "servicex_get_dataset",
            "servicex_delete_dataset",
            "servicex_submit_query",
        }

    def test_does_not_construct_client_at_build_time(self) -> None:
        # ServiceXClient() must only be constructed inside the lifespan, not
        # eagerly by _make_stdio_mcp itself -- otherwise a real .servicex
        # config file would be required just to build the MCPServer object.
        with patch("servicex_mcp.server.ServiceXClient") as mock_client_cls:
            _make_stdio_mcp(backend="test-backend")
        mock_client_cls.assert_not_called()

    def test_read_only_flag_propagates_to_lifespan(self) -> None:
        with patch("servicex_mcp.server.ServiceXClient"):
            mcp = _make_stdio_mcp(backend="test-backend", read_only=True)
        assert mcp is not None  # lifespan_context is only populated once entered;
        # a fuller assertion requires an async lifespan test -- see below.


class TestStdioLifespan:
    async def test_read_only_threaded_into_lifespan_context(self) -> None:
        with patch("servicex_mcp.server.ServiceXClient"):
            mcp = _make_stdio_mcp(backend="test-backend", read_only=True)
            async with AsyncExitStack() as stack:
                context = await stack.enter_async_context(_enter_lifespan(mcp))
                assert context["read_only"] is True
                assert context["client_factory"] is not None

    async def test_read_only_defaults_to_false_in_lifespan_context(self) -> None:
        with patch("servicex_mcp.server.ServiceXClient"):
            mcp = _make_stdio_mcp(backend="test-backend")
            async with AsyncExitStack() as stack:
                context = await stack.enter_async_context(_enter_lifespan(mcp))
                assert context["read_only"] is False

    async def test_lifespan_builds_client_with_backend_and_config_path(self) -> None:
        with patch("servicex_mcp.server.ServiceXClient") as mock_client_cls:
            mcp = _make_stdio_mcp(backend="test-backend", config_path="/some/path")
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(_enter_lifespan(mcp))
        mock_client_cls.assert_called_once_with(
            backend="test-backend", config_path="/some/path"
        )
