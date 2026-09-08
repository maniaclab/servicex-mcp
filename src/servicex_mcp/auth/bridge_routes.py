"""Starlette route handlers for the OAuth bridge interstitial page.

The "bridge" lets a user complete the MCP OAuth flow by pasting their own
ServiceX personal refresh token (obtained from the ServiceX deployment's web
UI) rather than an external IdP redirect. Validation happens synchronously
in the POST handler — there is no polling step.

GET  /bridge?session=<sid>   — render the paste-token form
POST /bridge?session=<sid>   — validate the pasted token; on success, 302
                                redirect to redirect_uri?code=...&state=...;
                                on failure, re-render the form with an error
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.server.mcpserver import MCPServer
    from starlette.requests import Request

    from servicex_mcp.auth.bridge_provider import ServiceXBridgeProvider


def make_bridge_handlers(
    provider: ServiceXBridgeProvider,
) -> tuple[Callable[..., object], Callable[..., object]]:
    """Return (bridge_get_handler, bridge_post_handler) closures over *provider*."""

    async def bridge_get(request: Request) -> Response:
        session_id = request.query_params.get("session")
        if not session_id:
            return JSONResponse({"error": "missing session parameter"}, status_code=400)
        session = provider.store.get_by_session_id(session_id)
        if session is None:
            return Response("Session not found or expired", status_code=404)
        return HTMLResponse(_build_form_html(session_id=session_id))

    async def bridge_post(request: Request) -> Response:
        session_id = request.query_params.get("session")
        if not session_id:
            return JSONResponse({"error": "missing session parameter"}, status_code=400)
        session = provider.store.get_by_session_id(session_id)
        if session is None:
            return Response("Session not found or expired", status_code=404)
        form = await request.form()
        token = str(form.get("token", "")).strip()
        if not token:
            return HTMLResponse(
                _build_form_html(session_id=session_id, error="Token is required"),
                status_code=400,
            )
        try:
            await provider.submit_token(session_id, token)
        except Exception as exc:  # noqa: BLE001
            return HTMLResponse(
                _build_form_html(session_id=session_id, error=f"Invalid token: {exc}"),
                status_code=400,
            )
        done_session = provider.store.get_by_session_id(session_id)
        # session was popped only on /token exchange, not here — still present
        assert done_session is not None
        params = {"code": done_session.auth_code}
        if done_session.state:
            params["state"] = done_session.state
        # status_code=302: RedirectResponse defaults to 307, but this module's
        # own docstring and the plan's test guidance both specify a 302 here.
        return RedirectResponse(
            f"{done_session.redirect_uri}?{urlencode(params)}", status_code=302
        )

    return bridge_get, bridge_post


def register_bridge_routes(mcp: MCPServer, provider: ServiceXBridgeProvider) -> None:
    """Register the /bridge GET+POST routes using the provider's session store."""
    bridge_get, bridge_post = make_bridge_handlers(provider)
    mcp.custom_route("/bridge", methods=["GET"])(bridge_get)
    mcp.custom_route("/bridge", methods=["POST"])(bridge_post)


def _build_form_html(*, session_id: str, error: str | None = None) -> str:
    # Escape both values before interpolation: session_id is only reachable
    # here after matching a secrets.token_urlsafe(32) session (safe in
    # practice), but error ultimately wraps an exception raised by
    # ServiceXAdapter/the ServiceX backend — never assume its text is safe
    # to interpolate as raw HTML, since a future exception type or a
    # compromised backend could echo attacker-influenced content into it.
    safe_session_id = html.escape(session_id)
    error_html = f'<p style="color:#c00">{html.escape(error)}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Connect ServiceX</title>
  <style>
    body {{ font-family: sans-serif; max-width: 600px; margin: 4rem auto; padding: 0 1rem; }}
    input[type=password] {{ width: 100%; padding: .5rem; font-family: monospace; }}
    button {{ margin-top: 1rem; padding: .6rem 1.2rem; background: #0070f3;
              color: #fff; border: none; border-radius: 4px; cursor: pointer; }}
  </style>
</head>
<body>
  <h1>Connect your ServiceX account</h1>
  <p>Paste your ServiceX personal refresh token below (from your ServiceX
  deployment's web UI).</p>
  {error_html}
  <form method="post" action="?session={safe_session_id}">
    <input type="password" name="token" placeholder="ServiceX refresh token" required>
    <button type="submit">Connect</button>
  </form>
</body>
</html>"""
