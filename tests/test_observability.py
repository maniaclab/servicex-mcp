"""Observability contract: JSON logs, the broker's request id, the access line
and a tool.call line, exercised through the real HTTP app built by serve_http.
"""

from __future__ import annotations

import io
import json
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from servicex_mcp.observability import (
    RequestLogMiddleware,
    configure_json_logging,
)
from servicex_mcp.server import serve_http

if TYPE_CHECKING:
    from collections.abc import Iterator

_RESOURCE_URL = "http://localhost:8000"
_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Authorization": "Bearer broker-token",
}


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    configure_json_logging("info", stream=stream)
    # TestClient's own httpx client logs each call; those lines are the test's
    # client side, not the server under test.
    for client_logger in ("httpx", "httpx2", "httpcore"):
        logging.getLogger(client_logger).setLevel(logging.WARNING)
    yield stream
    logging.getLogger().handlers.clear()


def _lines(stream: io.StringIO) -> list[dict[str, Any]]:
    """Every log line written so far, each of which must be a JSON object."""
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def _server_lines(stream: io.StringIO, event: str) -> list[dict[str, Any]]:
    return [line for line in _lines(stream) if line["event"] == event]


# L2 ----------------------------------------------------------------------


def test_every_line_is_json_with_the_standard_fields(
    log_stream: io.StringIO,
) -> None:
    logging.getLogger("servicex_mcp.test").info("something.happened")
    (line,) = _lines(log_stream)
    assert line["event"] == "something.happened"
    assert line["logger"] == "servicex_mcp.test"
    assert line["level"] == "info"
    assert line["timestamp"].endswith("+00:00")


def test_uvicorn_lines_are_json_when_uvicorn_leaves_logging_alone(
    log_stream: io.StringIO,
) -> None:
    logging.getLogger("uvicorn.error").info("Started server process [1]")
    (line,) = _lines(log_stream)
    assert line["event"] == "Started server process [1]"


# L1 and L3: the ASGI edge ---------------------------------------------------


async def _logging_endpoint(_request: Any) -> PlainTextResponse:
    logging.getLogger("servicex_mcp.test").info("inside.request")
    return PlainTextResponse("ok")


async def _failing_health(_request: Any) -> PlainTextResponse:
    return PlainTextResponse("down", status_code=503)


@pytest.fixture
def edge_client(log_stream: io.StringIO) -> TestClient:  # noqa: ARG001
    app = Starlette(
        routes=[
            Route("/mcp", _logging_endpoint, methods=["POST"]),
            Route("/healthz", _logging_endpoint, methods=["GET"]),
            Route("/readyz", _failing_health, methods=["GET"]),
        ]
    )
    return TestClient(RequestLogMiddleware(app))


def test_every_line_of_a_request_carries_the_brokers_request_id(
    edge_client: TestClient, log_stream: io.StringIO
) -> None:
    edge_client.post("/mcp", headers={"X-Request-ID": "abc"})
    lines = _lines(log_stream)
    assert {line["event"] for line in lines} == {"inside.request", "http.request"}
    assert [line["request_id"] for line in lines] == ["abc", "abc"]


def test_access_line_has_method_path_status_and_duration(
    edge_client: TestClient, log_stream: io.StringIO
) -> None:
    edge_client.post("/mcp", headers={"X-Request-ID": "abc"})
    (access,) = _server_lines(log_stream, "http.request")
    assert (access["method"], access["path"], access["status"]) == (
        "POST",
        "/mcp",
        200,
    )
    assert access["duration_ms"] >= 0


def test_request_id_is_generated_when_the_header_is_absent(
    edge_client: TestClient, log_stream: io.StringIO
) -> None:
    edge_client.post("/mcp")
    ids = {line["request_id"] for line in _lines(log_stream)}
    assert len(ids) == 1
    assert ids != {""}


def test_request_id_is_truncated_to_128_characters(
    edge_client: TestClient, log_stream: io.StringIO
) -> None:
    edge_client.post("/mcp", headers={"X-Request-ID": "x" * 300})
    assert {line["request_id"] for line in _lines(log_stream)} == {"x" * 128}


def test_request_id_does_not_leak_into_the_next_request(
    edge_client: TestClient, log_stream: io.StringIO
) -> None:
    edge_client.post("/mcp", headers={"X-Request-ID": "first"})
    logging.getLogger("servicex_mcp.test").info("between.requests")
    (between,) = _server_lines(log_stream, "between.requests")
    assert "request_id" not in between


def test_successful_health_probe_writes_no_access_line(
    edge_client: TestClient, log_stream: io.StringIO
) -> None:
    edge_client.get("/healthz")
    assert {line["event"] for line in _lines(log_stream)} == {"inside.request"}


def test_failing_health_probe_is_logged(
    edge_client: TestClient, log_stream: io.StringIO
) -> None:
    edge_client.get("/readyz")
    (access,) = _server_lines(log_stream, "http.request")
    assert (access["path"], access["status"]) == ("/readyz", 503)


# L1 and L2: the real app ---------------------------------------------------


@pytest.fixture
def broker_app() -> Any:
    """The ASGI app serve_http hands to uvicorn, in broker mode."""
    with patch("servicex_mcp.server.uvicorn.run") as run:
        serve_http(
            backend_url="https://servicex.example.com",
            resource_url=_RESOURCE_URL,
            broker_url="https://broker.example.com",
            host="127.0.0.1",
            port=8000,
            read_only=False,
            cache_dir="/tmp/servicex_mcp_cache_test",
        )
    return run.call_args.args[0]


def _call_tool(client: TestClient, name: str, request_id: str) -> dict[str, Any]:
    headers = {**_HEADERS, "X-Request-ID": request_id}
    init = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
    )
    headers["mcp-session-id"] = init.headers["mcp-session-id"]
    client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        },
    )
    (data_line,) = [
        line for line in response.text.splitlines() if line.startswith("data: ")
    ]
    return json.loads(data_line.removeprefix("data: "))  # type: ignore[no-any-return]


def _working_client() -> MagicMock:
    client = MagicMock()
    client.servicex.get_servicex_info = AsyncMock(
        return_value=SimpleNamespace(app_version="1.2.3", capabilities=[])
    )
    return client


def test_tool_call_line_has_the_standard_fields_and_the_request_id(
    broker_app: Any, log_stream: io.StringIO
) -> None:
    with (
        patch(
            "servicex_mcp.tools.info.get_servicex_client",
            return_value=_working_client(),
        ),
        TestClient(broker_app, base_url=_RESOURCE_URL) as client,
    ):
        result = _call_tool(client, "servicex_info", "abc")
    assert result["result"]["isError"] is False
    (call,) = _server_lines(log_stream, "tool.call")
    assert call["tool"] == "servicex_info"
    assert call["outcome"] == "ok"
    assert call["request_id"] == "abc"
    assert call["duration_ms"] >= 0
    assert {"timestamp", "level", "logger"} <= call.keys()


def test_tool_call_line_reports_a_failed_tool_as_error(
    broker_app: Any, log_stream: io.StringIO
) -> None:
    failing = MagicMock()
    failing.servicex.get_servicex_info = AsyncMock(side_effect=RuntimeError("boom"))
    with (
        patch("servicex_mcp.tools.info.get_servicex_client", return_value=failing),
        TestClient(broker_app, base_url=_RESOURCE_URL) as client,
    ):
        result = _call_tool(client, "servicex_info", "abc")
    assert result["result"]["isError"] is True
    (call,) = _server_lines(log_stream, "tool.call")
    assert call["outcome"] == "error"


def test_tool_call_line_never_carries_the_token_or_arguments(
    broker_app: Any, log_stream: io.StringIO
) -> None:
    with (
        patch(
            "servicex_mcp.tools.info.get_servicex_client",
            return_value=_working_client(),
        ),
        TestClient(broker_app, base_url=_RESOURCE_URL) as client,
    ):
        _call_tool(client, "servicex_info", "abc")
    assert "broker-token" not in log_stream.getvalue()


def test_the_real_app_writes_one_access_line_per_request_with_the_id(
    broker_app: Any, log_stream: io.StringIO
) -> None:
    with TestClient(broker_app, base_url=_RESOURCE_URL) as client:
        client.post(
            "/mcp",
            headers={**_HEADERS, "X-Request-ID": "abc"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
    accesses = [
        line
        for line in _server_lines(log_stream, "http.request")
        if line["path"] == "/mcp"
    ]
    assert [a["request_id"] for a in accesses] == ["abc"]
