"""Integration tests against a real ServiceX instance.

Requires a valid .servicex/servicex.yaml with a working backend and a
refresh token that hasn't expired. Run with:

    pytest tests/integration/ --runslow -v
"""

from __future__ import annotations

import pytest

from servicex_mcp.server import _make_stdio_mcp

pytestmark = pytest.mark.slow


class TestLiveServiceX:
    async def test_servicex_info_reaches_real_backend(self) -> None:
        mcp = _make_stdio_mcp()
        assert mcp is not None
        # Enter the lifespan manually (see test_server.py's async lifespan test
        # for the exact AsyncExitStack idiom) to get a real ctx, then:
        # tools = {t.name: t.fn for t in mcp._tool_manager.list_tools()}
        # result = await tools["servicex_info"](ctx=ctx)
        # assert "app_version" in result
        pytest.skip("Wire up a real lifespan-entered ctx before enabling this test")
