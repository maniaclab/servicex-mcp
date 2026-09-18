"""Tests for _make_stdio_mcp."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from servicex_mcp.server import _make_stdio_mcp

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def _enter_lifespan(mcp: MCPServer) -> AbstractAsyncContextManager[dict[str, Any]]:
    # mcp.settings.lifespan is typed Optional even though _make_stdio_mcp
    # always sets it; narrow it here so callers don't repeat the assert.
    assert mcp.settings.lifespan is not None
    return mcp.settings.lifespan(mcp)


_JSON_RPC_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _initialize_session(client: TestClient) -> dict[str, str]:
    """Do the MCP initialize handshake over *client* and return headers carrying the session id."""
    init_resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        headers=_JSON_RPC_HEADERS,
    )
    session_id = init_resp.headers["mcp-session-id"]
    headers = {**_JSON_RPC_HEADERS, "mcp-session-id": session_id}
    client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
    )
    return headers


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

    def test_every_tool_declares_annotations_and_output_schema(self) -> None:
        """Drift guard: every servicex_* tool must publish annotations and an outputSchema.

        This is the one test that would catch a future tool being added
        (or an existing one being refactored) without following the
        Annotated[CallToolResult, Model] + ToolAnnotations pattern all
        ten tools use today -- see CLAUDE.md's tool registration pattern.
        """
        with patch("servicex_mcp.server.ServiceXClient"):
            mcp = _make_stdio_mcp(backend="test-backend")
        for tool in mcp._tool_manager.list_tools():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is not None, tool.name
            assert tool.output_schema is not None, tool.name


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


class TestStdioAppOverTheWire:
    """Wire-level assertions that bypass every unit test's tool.fn shortcut.

    Every existing tool test calls the raw callable directly, which never
    goes through the mcp SDK's serialization -- none of them would notice
    a missing annotations/outputSchema on the wire. These do, via a real
    JSON-RPC round trip through the built ASGI app (see A.4/A.1 of the
    interop plan).
    """

    @pytest.fixture
    def client(self) -> Any:
        with patch("servicex_mcp.server.ServiceXClient") as mock_client_cls:
            mock_client_cls.return_value.get_code_generators.return_value = {
                "python": "sslhep/servicex_generic_codegen:v1",
            }
            mcp = _make_stdio_mcp(backend="test-backend")
            app = mcp.streamable_http_app(
                streamable_http_path="/mcp", json_response=True
            )
            with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
                yield test_client

    def test_tools_list_carries_annotations_and_output_schema(
        self, client: TestClient
    ) -> None:
        headers = _initialize_session(client)
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers=headers,
        )
        assert resp.status_code == 200
        tools = {tool["name"]: tool for tool in resp.json()["result"]["tools"]}
        assert set(tools) == {
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
        for tool in tools.values():
            assert tool["outputSchema"] is not None
            assert tool["annotations"]["readOnlyHint"] is not None

        # Spot-check one tool from each annotation bucket (A.3 of the
        # interop plan): read-only, mutating-non-destructive, destructive.
        assert tools["servicex_list_code_generators"]["annotations"] == {
            "title": "List code generators",
            "readOnlyHint": True,
            "openWorldHint": True,
        }
        assert tools["servicex_submit_query"]["annotations"] == {
            "title": "Submit query",
            "readOnlyHint": False,
        }
        assert tools["servicex_delete_dataset"]["annotations"] == {
            "title": "Delete dataset",
            "readOnlyHint": False,
            "destructiveHint": True,
        }

    def test_tools_call_carries_text_and_structured_content(
        self, client: TestClient
    ) -> None:
        headers = _initialize_session(client)
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "servicex_list_code_generators", "arguments": {}},
            },
            headers=headers,
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["isError"] is False
        assert result["content"][0]["type"] == "text"
        assert "python" in result["content"][0]["text"]
        structured = result["structuredContent"]
        assert structured["generators"] == {
            "python": "sslhep/servicex_generic_codegen:v1"
        }
