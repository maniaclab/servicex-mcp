"""The /healthz liveness and readiness probe, served by the real HTTP app."""

from __future__ import annotations

import logging

import pytest
from starlette.testclient import TestClient

from servicex_mcp.observability import RequestLogMiddleware
from servicex_mcp.server import (
    _make_http_mcp,
    _transport_security_from_resource_url,
)

_RESOURCE_URL = "https://servicex-mcp.example.org"
# kubelet probes the pod IP, so the Host header is never the public hostname.
_PROBE_HEADERS = {"Host": "10.1.2.3:9000"}


@pytest.fixture(params=["bridge", "broker"])
def client(request: pytest.FixtureRequest) -> TestClient:
    mcp, _provider = _make_http_mcp(
        backend_url="https://servicex.example.com",
        resource_url=_RESOURCE_URL,
        read_only=False,
        cache_dir="/tmp/servicex_mcp_cache_test",
        broker_url="https://mcp.example.org" if request.param == "broker" else None,
    )
    app = mcp.streamable_http_app(
        transport_security=_transport_security_from_resource_url(_RESOURCE_URL)
    )
    return TestClient(app)


def test_healthz_needs_no_auth_and_reports_ok(client: TestClient) -> None:
    response = client.get("/healthz", headers=_PROBE_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_successful_probe_writes_no_access_line(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="servicex_mcp"):
        TestClient(RequestLogMiddleware(client.app)).get(
            "/healthz", headers=_PROBE_HEADERS
        )
    assert [r for r in caplog.records if r.name == "servicex_mcp"] == []
