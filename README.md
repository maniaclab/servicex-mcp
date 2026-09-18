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
