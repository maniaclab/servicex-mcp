from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from servicex_mcp.auth.factory import EnvBasedClientFactory


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
