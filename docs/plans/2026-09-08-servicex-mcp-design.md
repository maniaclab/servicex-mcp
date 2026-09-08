# servicex-mcp design

Status: approved, implementing both transports together.

## Purpose

MCP server exposing ServiceX (IRIS-HEP data-delivery service for ATLAS/CMS)
operations as tools for LLMs: discover cached datasets, inspect/manage
transforms, and submit new transform (query) requests. Modeled on the
structure of `rucio-mcp` and `ami-mcp` (pyproject/hatch/pixi, charts, CI,
docs, tools/auth layout), and on the interface-design lessons in
`~/2026-09-08-pyhepdev-mcp/presentation.html` (wrap the client library not
the CLI; bound every output; errors name the next tool; identity is
ambient; no stored credentials; CIMD not DCR).

## Backend

Wraps the `servicex` PyPI package (`ServiceXClient` / `ServiceXAdapter`),
the official IRIS-HEP client — same relationship rucio-mcp has to
`rucio.client` and ami-mcp has to pyAMI.

Key methods used: `get_transforms`, `get_transform_status`, `get_datasets`,
`get_dataset`, `delete_dataset`, `delete_transform`, `cancel_transform`,
`get_code_generators`, `get_servicex_info`/capabilities, and
`generic_query(...)` + the adapter's `submit_transform(transform_request)`
for submission (called directly on the adapter, not via `Query.submit_and_download`,
so submission returns a `request_id` immediately instead of blocking until
the transform finishes downloading — the right shape for an MCP tool call).

ServiceX's own auth model: a per-backend **refresh token** stored in a
`.servicex`/`servicex.yaml` file (`api_endpoints: [{endpoint, name, token}]`),
exchanged for short-lived access JWTs via `POST {url}/token/refresh`.
`ServiceXAdapter.token` is a plain instance attribute — no subclassing
needed to inject a pre-obtained access token directly (unlike rucio-mcp's
`TokenInjectedClient`).

## Architecture — both transports from the start

```
# stdio (local, single-user)
LLM <--MCP/stdio--> servicex-mcp serve <--HTTPS (ServiceXClient)--> ServiceX backend
                              |
                     built from .servicex/servicex.yaml (SERVICEX_CONFIG env, --backend NAME)

# http (hosted, multi-user, federated)
MCP client <--auth-code+PKCE--> servicex-mcp (OAuth 2.1 AS, CIMD only, no DCR) <--Bearer--> ServiceX backend
```

**Stdio mode:** one `ServiceXClient` built at startup from a local config
file (`--backend NAME` selects an `api_endpoint`, mirroring rucio-mcp's
`--site`). Single user, whatever refresh token is in that yaml.

**HTTP mode:** servicex-mcp is its own OAuth 2.1 Authorization Server. MCP
clients are identified via **CIMD** (`client_id` = an https URL the server
dereferences) — **DCR is disabled**, no `/register` endpoint, no per-client
registry, same as rucio-mcp. This is orthogonal to how the *ServiceX*
credential is obtained. A `BearerTokenClientFactory` extracts
`Authorization: Bearer <token>` from each request and injects it into a
`ServiceXAdapter` (`adapter.token = token` when it's already a short-lived
access token; otherwise treated as a refresh token and exchanged via
ServiceX's own `/token/refresh`). Two ways that token arrives, same
endpoint either way:

1. **Standalone**: a user points their MCP client directly at servicex-mcp.
   The `/authorize` step is a lightweight interstitial where they paste
   their personal ServiceX refresh token; servicex-mcp returns it verbatim
   as the MCP `access_token` (same trick rucio-mcp uses for the rucio
   session token).
2. **Behind af-mcp-platform**: the gateway/broker (eventually via a
   `servicex-token-service` custodian, not built here) redeems the user's
   PAT for a short-lived ServiceX access token and calls servicex-mcp with
   that as Bearer.

servicex-mcp never stores a refresh token to disk; adapters are cached
in-memory per session/token-hash with a fixed TTL, same discipline as
rucio-mcp's `SessionCache`.

## Tool surface (v1)

Read/discovery:
- `servicex_info` — server version + capabilities
- `servicex_list_code_generators`
- `servicex_list_transforms`, `servicex_get_transform_status`
- `servicex_list_datasets`, `servicex_get_dataset`

Manage (mutating, existing resources):
- `servicex_cancel_transform`, `servicex_delete_transform`, `servicex_delete_dataset`

Submit (the actual value-add):
- `servicex_submit_query(dataset, dataset_kind, query, codegen, title,
  result_format, num_files)` — builds a `DataSetIdentifier` (rucio DID /
  file list / xrootd pattern / CERN Open Data) + a query string against a
  named codegen, submits via the adapter, returns the `request_id`
  immediately (no blocking wait). The LLM polls with
  `servicex_get_transform_status`.

All list tools take `limit`/`offset` and are hard-capped server-side.
Errors go through a `classify_error()`-style helper that names the next
tool to call, never a raw traceback; MCP `isError` set on failure.

## Package layout

Mirrors rucio-mcp/ami-mcp: `src/servicex_mcp/{cli.py,server.py,resources.py,
auth/{factory.py,session_cache.py,cimd.py,bridge_provider.py,bridge_routes.py,
bridge_state.py,token_client.py},tools/{_helpers.py,info.py,transforms.py,
datasets.py,submit.py}}`, `tests/` mirroring each module plus
`tests/integration/test_live.py`, `charts/servicex-mcp/`,
`.github/workflows/{ci,cd,docs}.yml`, `pyproject.toml` + `pixi.toml`
(hatchling + hatch-vcs, pixi tasks for test/lint/build/docs/helm-lint).

## Deferred (explicitly out of scope for this build)

- `servicex-token-service` custodian (af-mcp-platform-side credential
  redemption) — a separate repo/service, not part of this MCP server.
- Prometheus metrics / Grafana dashboard wiring (rucio-mcp has this; add
  once the core surface is stable).
