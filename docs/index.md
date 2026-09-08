# servicex-mcp

MCP Server for [ServiceX](https://github.com/ssl-hep/ServiceX), the IRIS-HEP
on-demand data-delivery service for ATLAS/CMS. Wraps the
[`servicex`](https://pypi.org/project/servicex/) Python client as MCP tools.

**Docs are a work in progress.** This page is a minimal landing page listing the
tool surface. Full docs parity with rucio-mcp (a getting-started guide,
`.servicex`/HTTP-bridge configuration reference, and per-tool detail pages) is a
TODO -- see `docs/plans/` in the repository for the design and implementation
plan in the meantime.

## Transports

- **stdio** -- builds one `ServiceXClient` from a local
  `.servicex/servicex.yaml` file. Run with
  `servicex-mcp serve --backend <name>`.
- **HTTP** -- its own OAuth 2.1 authorization server (CIMD client
  identification, no dynamic client registration). Each user pastes their own
  ServiceX personal refresh token through a `/bridge` interstitial the first
  time they connect; no local `.servicex` file or server-side credential is
  needed. Run with
  `servicex-mcp serve --transport http --backend-url <url> --resource-url <url>`.

## Tools

| Tool                            | Description                                                                 |
| ------------------------------- | --------------------------------------------------------------------------- |
| `servicex_info`                 | Return the ServiceX server version and its advertised capabilities.         |
| `servicex_list_code_generators` | List the code generators deployed on this ServiceX instance.                |
| `servicex_submit_query`         | Submit a new transform (query) request against a dataset.                   |
| `servicex_list_transforms`      | List transforms you have submitted, with status and file completion counts. |
| `servicex_get_transform_status` | Get the full status of one transform by its request ID.                     |
| `servicex_cancel_transform`     | Cancel a running transform by its request ID.                               |
| `servicex_delete_transform`     | Delete a transform record (and its cache entry) by request ID.              |
| `servicex_list_datasets`        | List datasets cached on this ServiceX instance.                             |
| `servicex_get_dataset`          | Get the full detail of one cached dataset by its dataset ID.                |
| `servicex_delete_dataset`       | Delete a cached dataset record by its dataset ID.                           |

All write tools (`servicex_submit_query`, `servicex_cancel_transform`,
`servicex_delete_transform`, `servicex_delete_dataset`) are disabled when the
server is started with `--read-only`.
