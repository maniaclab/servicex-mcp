from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from mcp.types import TextContent

from servicex_mcp.auth.factory import EnvBasedClientFactory

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.types import CallToolResult


@pytest.fixture
def tool_text() -> Callable[[CallToolResult], str]:
    """Return a helper that extracts a tool's CallToolResult's markdown text block.

    Every servicex_* tool returns exactly one TextContent block alongside its
    (optional) structured_content -- this is the substring-assertion
    equivalent of the plain-string return the tools used to have.
    """

    def _tool_text(result: CallToolResult) -> str:
        block = result.content[0]
        assert isinstance(block, TextContent)
        return block.text

    return _tool_text


@pytest.fixture
def mock_servicex_client() -> MagicMock:
    """Return a MagicMock that mimics servicex.ServiceXClient."""
    return MagicMock()


@pytest.fixture
def mock_ctx(mock_servicex_client: MagicMock) -> MagicMock:
    """Return a mock MCP Context with a factory-wrapped ServiceXClient."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.lifespan_context = {
        "client_factory": EnvBasedClientFactory(client=mock_servicex_client),
        "read_only": False,
    }
    return ctx


@pytest.fixture
def mock_ctx_readonly(mock_servicex_client: MagicMock) -> MagicMock:
    """Return a mock MCP Context with read_only=True."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.lifespan_context = {
        "client_factory": EnvBasedClientFactory(client=mock_servicex_client),
        "read_only": True,
    }
    return ctx


def pytest_addoption(parser: Any) -> None:
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )


def pytest_collection_modifyitems(config: Any, items: Any) -> None:
    if not config.getoption("--runslow"):
        skip_slow = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
