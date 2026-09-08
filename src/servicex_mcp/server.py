"""FastMCP server setup for servicex-mcp (stdio and HTTP transports)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.mcpserver import MCPServer
from pydantic import AnyHttpUrl
from servicex.servicex_client import ServiceXClient

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, MutableMapping

from servicex_mcp.auth.bridge_provider import (
    ServiceXBridgeProvider,
    _authorize_redirect_uri,
)
from servicex_mcp.auth.bridge_routes import register_bridge_routes
from servicex_mcp.auth.factory import BearerTokenClientFactory, EnvBasedClientFactory
from servicex_mcp.auth.session_cache import SessionCache
from servicex_mcp.tools import datasets, info, submit, transforms

_STDIO_PREAMBLE = (
    "MCP server for ServiceX data delivery. "
    "Provides tools to discover code generators, submit transform (query) "
    "requests against a dataset, and inspect/manage transforms and cached "
    "datasets. Authentication is configured via a local .servicex/servicex.yaml "
    "file (selected with --backend) before starting the server."
)


def _make_stdio_mcp(
    *,
    backend: str | None = None,
    config_path: str | None = None,
    read_only: bool = False,
) -> MCPServer:
    """Build and return a configured MCPServer instance for stdio transport."""

    @asynccontextmanager
    async def _lifespan(_server: MCPServer) -> AsyncGenerator[dict[str, Any], None]:
        client = ServiceXClient(backend=backend, config_path=config_path)
        factory = EnvBasedClientFactory(client=client)
        try:
            yield {"client_factory": factory, "read_only": read_only}
        finally:
            factory.close()

    mcp = MCPServer("servicex-mcp", lifespan=_lifespan, instructions=_STDIO_PREAMBLE)

    for _module in [info, transforms, datasets, submit]:
        _module.register(mcp)

    return mcp


def serve(*, backend: str | None, config_path: str | None, read_only: bool) -> None:
    """Entry point used by the CLI's `serve` subcommand (stdio only, for now)."""
    mcp = _make_stdio_mcp(backend=backend, config_path=config_path, read_only=read_only)
    mcp.run(transport="stdio")


_HTTP_PREAMBLE = (
    "MCP server for ServiceX data delivery. "
    "Provides tools to discover code generators, submit transform (query) "
    "requests, and inspect/manage transforms and cached datasets. "
    "Authentication uses your personal ServiceX refresh token via the OAuth "
    "2.1 bridge — no local .servicex file is required."
)


class _AuthorizeContextMiddleware:
    """ASGI middleware that exposes the /authorize redirect_uri to the provider.

    For every ``/authorize`` request it extracts the ``redirect_uri`` query
    parameter and stores it in the ``_authorize_redirect_uri`` contextvar for
    the lifetime of that request.

    ``ServiceXBridgeProvider._resolve_cimd()`` reads this contextvar so that a
    CIMD client's ephemeral-port loopback ``redirect_uri`` can be matched
    port-agnostically against its Client ID Metadata Document.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path", "").endswith("/authorize"):
            qs = parse_qs(scope.get("query_string", b"").decode())
            redirect_uris = qs.get("redirect_uri", [])
            if redirect_uris:
                token = _authorize_redirect_uri.set(redirect_uris[0])
                try:
                    await self._app(scope, receive, send)
                finally:
                    _authorize_redirect_uri.reset(token)
                return
        await self._app(scope, receive, send)


def _augment_as_metadata(body: bytes) -> bytes:
    """Add CIMD advertisement to the SDK's AS metadata JSON.

    The mcp SDK's ``build_metadata`` does not emit
    ``client_id_metadata_document_supported`` and hard-codes
    ``token_endpoint_auth_methods_supported`` without ``"none"``.  Claude selects
    CIMD only when both are present (the CIMD client authenticates as a public
    client — PKCE only, no secret), so we patch them in here.
    """
    try:
        meta = json.loads(body)
    except ValueError:
        return body
    meta["client_id_metadata_document_supported"] = True
    methods = meta.get("token_endpoint_auth_methods_supported") or []
    if "none" not in methods:
        meta["token_endpoint_auth_methods_supported"] = ["none", *methods]
    return json.dumps(meta).encode()


class _CimdMetadataMiddleware:
    """Rewrite the AS metadata response to advertise CIMD support.

    Buffers the response body to recompute Content-Length after the rewrite.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        if scope.get("type") != "http" or not path.endswith(
            "/.well-known/oauth-authorization-server"
        ):
            await self._app(scope, receive, send)
            return

        start_message: dict[str, Any] = {}
        body_chunks: list[bytes] = []

        async def _buffer(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                start_message.update(message)
            elif message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(body_chunks)
                if start_message.get("status") == 200:
                    body = _augment_as_metadata(body)
                headers = [
                    (k, v)
                    for k, v in start_message.get("headers", [])
                    if k.lower() != b"content-length"
                ]
                headers.append((b"content-length", str(len(body)).encode()))
                await send({**start_message, "headers": headers})
                await send(
                    {"type": "http.response.body", "body": body, "more_body": False}
                )

        await self._app(scope, receive, _buffer)


def _make_http_mcp(
    *, backend_url: str, resource_url: str, read_only: bool, cache_dir: str
) -> tuple[MCPServer, ServiceXBridgeProvider]:
    """Build the MCPServer instance for HTTP transport."""
    provider = ServiceXBridgeProvider(
        backend_url=backend_url, resource_url=resource_url
    )
    cache = SessionCache()

    @asynccontextmanager
    async def _http_lifespan(
        _server: MCPServer,
    ) -> AsyncGenerator[dict[str, Any], None]:
        factory = BearerTokenClientFactory(
            cache=cache, backend_url=backend_url, cache_dir=cache_dir
        )
        try:
            yield {"client_factory": factory, "read_only": read_only}
        finally:
            factory.close()

    mcp = MCPServer(
        "servicex-mcp",
        instructions=_HTTP_PREAMBLE,
        lifespan=_http_lifespan,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(resource_url),
            resource_server_url=AnyHttpUrl(resource_url),
            # DCR disabled: clients are identified via CIMD only.
            client_registration_options=ClientRegistrationOptions(enabled=False),
            required_scopes=[],
        ),
    )

    register_bridge_routes(mcp, provider)
    for _module in [info, transforms, datasets, submit]:
        _module.register(mcp)

    return mcp, provider


def serve_http(
    *,
    backend_url: str,
    resource_url: str,
    host: str,
    port: int,
    read_only: bool,
    cache_dir: str,
) -> None:
    """Entry point used by the CLI's `serve --transport http` path."""
    mcp, _provider = _make_http_mcp(
        backend_url=backend_url,
        resource_url=resource_url,
        read_only=read_only,
        cache_dir=cache_dir,
    )
    app = _CimdMetadataMiddleware(
        _AuthorizeContextMiddleware(mcp.streamable_http_app())
    )
    uvicorn.run(app, host=host, port=port)
