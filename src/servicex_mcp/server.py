"""FastMCP server setup for servicex-mcp (stdio and HTTP transports)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import uvicorn
from af_credentials.proxy import ProxyClient
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from servicex.servicex_client import ServiceXClient

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, MutableMapping

from servicex_mcp.auth.bridge_provider import (
    ServiceXBridgeProvider,
    _authorize_redirect_uri,
)
from servicex_mcp.auth.bridge_routes import register_bridge_routes
from servicex_mcp.auth.factory import (
    BearerTokenClientFactory,
    BrokerServiceXClientFactory,
    EnvBasedClientFactory,
    ServiceXRedeemer,
)
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


def _transport_security_from_resource_url(
    resource_url: str,
) -> TransportSecuritySettings:
    """Build an explicit DNS-rebinding allow-list from the server's public URL.

    The MCP SDK's `streamable_http_app(host=...)` only auto-enables DNS
    rebinding protection (and only allows 127.0.0.1/localhost/::1) when the
    *bind* host it's given is loopback — it has no idea what public
    `resource_url` clients actually reach the server through. Since we never
    pass a `host=` derived from the real bind address, that auto-enable
    branch would silently never fire for any non-loopback deployment, and
    `TransportSecurityMiddleware` falls back to
    `enable_dns_rebinding_protection=False` when given no explicit settings
    at all — i.e. the failure mode isn't "server refuses to start," it's
    "DNS rebinding protection is silently off" for a real public bind, or
    (if a bind host happens to be loopback while resource_url isn't) the
    server 421s every request. Building this explicitly from `resource_url`
    is correct for both local (http://localhost:PORT) and hosted
    (https://servicex-mcp.example.org) deployments.
    """
    parsed = urlparse(resource_url)
    netloc = parsed.netloc
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[netloc],
        allowed_origins=[f"{parsed.scheme}://{netloc}"],
    )


def _make_broker_http_mcp(
    *, backend_url: str, broker_url: str, read_only: bool, cache_dir: str
) -> MCPServer:
    """Build the MCPServer instance for HTTP transport in broker mode.

    Unlike bridge mode (below), this server runs no OAuth 2.1 authorization
    server of its own and registers no /bridge routes: the AF MCP broker's
    aggregator already authenticated the caller and forwards an AF Broker
    Identity Token as this request's own bearer — the same shape every
    other broker-mediated backend in that platform relies on (see
    maniaclab/af-mcp-platform#295). resource_url-derived transport security
    (DNS-rebinding protection) still applies uniformly in serve_http,
    independent of this OAuth-provider distinction.

    The concrete redeemer is constructed here, not in auth/factory.py, so
    that module stays independent of af-credentials' release status — see
    BrokerServiceXClientFactory's docstring.
    """
    cache = SessionCache()
    # af-credentials' kind="servicex"/access_token() support shipped in
    # v0.3.1 (maniaclab/af-credentials#9) — this construction is the one
    # place in this codebase that imports af_credentials directly; every
    # *downstream* use of `redeemer` (e.g. BrokerServiceXClientFactory's
    # constructor) stays typed against the ServiceXRedeemer protocol instead.
    redeemer: ServiceXRedeemer = ProxyClient(broker_url, kind="servicex")

    @asynccontextmanager
    async def _broker_lifespan(
        _server: MCPServer,
    ) -> AsyncGenerator[dict[str, Any], None]:
        factory = BrokerServiceXClientFactory(
            cache=cache, redeemer=redeemer, backend_url=backend_url, cache_dir=cache_dir
        )
        try:
            yield {"client_factory": factory, "read_only": read_only}
        finally:
            factory.close()

    mcp = MCPServer(
        "servicex-mcp",
        instructions=_HTTP_PREAMBLE,
        lifespan=_broker_lifespan,
    )

    for _module in [info, transforms, datasets, submit]:
        _module.register(mcp)

    return mcp


def _make_http_mcp(
    *,
    backend_url: str,
    resource_url: str,
    read_only: bool,
    cache_dir: str,
    broker_url: str | None = None,
) -> tuple[MCPServer, ServiceXBridgeProvider | None]:
    """Build the MCPServer instance for HTTP transport.

    *broker_url*, when given, selects broker mode (see
    ``_make_broker_http_mcp``) — the returned provider is ``None`` since
    broker mode registers no OAuth 2.1 authorization server of its own.
    """
    if broker_url is not None:
        return (
            _make_broker_http_mcp(
                backend_url=backend_url,
                broker_url=broker_url,
                read_only=read_only,
                cache_dir=cache_dir,
            ),
            None,
        )

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
    log_level: str = "info",
    broker_url: str | None = None,
) -> None:
    """Entry point used by the CLI's `serve --transport http` path."""
    mcp, _provider = _make_http_mcp(
        backend_url=backend_url,
        resource_url=resource_url,
        read_only=read_only,
        cache_dir=cache_dir,
        broker_url=broker_url,
    )
    http_app = mcp.streamable_http_app(
        transport_security=_transport_security_from_resource_url(resource_url)
    )
    app = _CimdMetadataMiddleware(_AuthorizeContextMiddleware(http_app))
    # log_level is forwarded explicitly: uvicorn's own "uvicorn"/"uvicorn.error"/
    # "uvicorn.access" loggers are configured with propagate=False by its
    # default LOGGING_CONFIG, so they never inherit the level set on the root
    # logger via logging.basicConfig() in cli.py -- without this, --log-level
    # controls this app's own logs but not uvicorn's startup/access noise.
    uvicorn.run(app, host=host, port=port, log_level=log_level)
