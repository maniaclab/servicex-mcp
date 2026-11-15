"""Request id, JSON logs, access line and tool-call line.

Implements the AF MCP platform's backend logging contract (L1 to L3): one JSON
object per line on stdout, the broker's ``X-Request-ID`` as ``request_id`` on
every line of the request, and a ``tool.call`` line per tool invocation.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TextIO

from mcp.server.context import ServerMiddleware
from mcp.types import CallToolResult
from starlette.datastructures import Headers

if TYPE_CHECKING:
    from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEALTH_PATHS = frozenset({"/healthz", "/readyz"})
MAX_REQUEST_ID_CHARS = 128

log = logging.getLogger("servicex_mcp")

# The broker's X-Request-ID for the request being served. A ContextVar so tool
# code and library log calls carry it without passing it around.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """One JSON object per line with the standard fields.

    Call-specific fields travel as ``extra={"fields": {...}}``.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render the record as a single JSON line."""
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        if request_id := request_id_var.get():
            entry["request_id"] = request_id
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_json_logging(level: str, stream: TextIO | None = None) -> None:
    """Send every log line, this server's and uvicorn's, to *stream* (stdout) as JSON."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)


def _request_id_from(header: str) -> str:
    """Return the broker's id, bounded; generate one only when it is absent."""
    return header[:MAX_REQUEST_ID_CHARS] or uuid.uuid4().hex


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


class RequestLogMiddleware:
    """Bind ``X-Request-ID`` for the request and write its access line.

    The broker's id is authoritative; one is generated only when the header is
    absent, so every line still carries an id. A health or readiness probe
    that succeeds writes no access line; a failing one does.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap *app*."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve one request inside its request-id context."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        reset = request_id_var.set(
            _request_id_from(Headers(scope=scope).get("x-request-id", ""))
        )
        status = 500
        started = time.perf_counter()

        async def send_and_note_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_note_status)
        finally:
            if scope["path"] not in HEALTH_PATHS or status >= 400:
                log.info(
                    "http.request",
                    extra={
                        "fields": {
                            "method": scope["method"],
                            "path": scope["path"],
                            "status": status,
                            "duration_ms": _elapsed_ms(started),
                        }
                    },
                )
            request_id_var.reset(reset)


class ToolCallLogMiddleware(ServerMiddleware[Any]):
    """One ``tool.call`` log line per tool invocation.

    The MCP session may run a request's handler outside the HTTP request's own
    context, so the request id is read again from the request's headers here.
    ``subject`` is deliberately absent: in broker mode this server does not
    verify the broker token itself (the broker's redeem call does), so any
    identity it could log would be unverified.
    """

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        """Time a ``tools/call`` and log its outcome; pass other methods through."""
        if ctx.method != "tools/call":
            return await call_next(ctx)
        name = (ctx.params or {}).get("name")
        headers = getattr(ctx.request, "headers", None)
        reset = (
            request_id_var.set(_request_id_from(headers.get("x-request-id", "")))
            if headers is not None
            else None
        )
        outcome = "error"
        started = time.perf_counter()
        try:
            result = await call_next(ctx)
            # A tool error reaches this layer as the model or as its wire-form
            # dict, the same two shapes the SDK's OpenTelemetry middleware matches.
            match result:
                case CallToolResult(is_error=True) | {"isError": True}:
                    outcome = "error"
                case _:
                    outcome = "ok"
        finally:
            log.info(
                "tool.call",
                extra={
                    "fields": {
                        "tool": name,
                        "duration_ms": _elapsed_ms(started),
                        "outcome": outcome,
                    }
                },
            )
            if reset is not None:
                request_id_var.reset(reset)
        return result
