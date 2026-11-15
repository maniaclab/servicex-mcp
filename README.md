# servicex-mcp

MCP Server for [ServiceX](https://github.com/ssl-hep/ServiceX), the IRIS-HEP
on-demand data-delivery service for ATLAS/CMS. Wraps the
[`servicex`](https://pypi.org/project/servicex/) Python client as MCP tools.

## Install

```bash
pip install servicex-mcp
```

## Usage (stdio)

```bash
servicex-mcp serve --backend <name-from-your-.servicex-file>
```

See `docs/plans/` for the design and implementation plan.

## Logging (HTTP transport)

`serve --transport http` writes one JSON object per line to stdout, including
uvicorn's own lines. The AF MCP broker's `X-Request-ID` is logged as
`request_id` on every line of the request (one is generated if absent), and each
tool invocation writes a `tool.call` line with `tool`, `duration_ms` and
`outcome` (`success` or `error`). The stdio transport keeps plain-text logs on
stderr, because stdout carries the protocol.

## Health probe (HTTP transport)

`GET /healthz` answers `200 {"status": "ok"}` without authentication and is what
the chart's liveness and readiness probes call. It reports this process only,
not the ServiceX backend, so a ServiceX outage does not take the server out of
rotation. A successful probe writes no access-log line; a failing one does.

## Available tools

| Tool                            | Does                                                                  | Read/write  |
| ------------------------------- | --------------------------------------------------------------------- | ----------- |
| `servicex_list_datasets`        | List datasets cached on this ServiceX instance                        | read-only   |
| `servicex_get_dataset`          | Get the full detail of one cached dataset by its dataset ID           | read-only   |
| `servicex_info`                 | Return the ServiceX server version and its advertised capabilities    | read-only   |
| `servicex_list_code_generators` | List the code generators deployed on this ServiceX instance           | read-only   |
| `servicex_list_transforms`      | List transforms you have submitted, with status and completion counts | read-only   |
| `servicex_get_transform_status` | Get the full status of one transform by its request ID                | read-only   |
| `servicex_submit_query`         | Submit a new transform (query) request against a dataset              | write       |
| `servicex_cancel_transform`     | Cancel a running transform by its request ID                          | destructive |
| `servicex_delete_transform`     | Delete a transform record (and its cache entry) by request ID         | destructive |
| `servicex_delete_dataset`       | Delete a cached dataset record by its dataset ID                      | destructive |

The six read-only tools query the external ServiceX server
(`read_only_hint=true`, `open_world_hint=true` in their MCP tool annotations).
`servicex_submit_query` mutates ServiceX state but never deletes anything
(`read_only_hint=false`). The three destructive tools
(`servicex_cancel_transform`, `servicex_delete_transform`,
`servicex_delete_dataset`) act on real running/finished transforms and cached
dataset records and cannot be undone (`read_only_hint=false`,
`destructive_hint=true`). All four write/destructive tools are disabled when the
server is started with `--read-only`.
