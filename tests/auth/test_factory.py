"""Tests for ServiceXClientFactory and EnvBasedClientFactory."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from servicex_mcp.auth.factory import EnvBasedClientFactory, ServiceXClientFactory


def test_factory_is_abstract() -> None:
    with pytest.raises(TypeError):
        ServiceXClientFactory()  # type: ignore[abstract]


class TestEnvBasedClientFactory:
    def test_get_client_returns_stored_client(self) -> None:
        client = MagicMock()
        factory = EnvBasedClientFactory(client=client)
        assert factory.get_client(MagicMock()) is client

    def test_get_client_ignores_ctx(self) -> None:
        client = MagicMock()
        factory = EnvBasedClientFactory(client=client)
        assert factory.get_client(None) is client

    def test_close_is_noop(self) -> None:
        factory = EnvBasedClientFactory(client=MagicMock())
        factory.close()  # must not raise
