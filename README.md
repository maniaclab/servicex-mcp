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
