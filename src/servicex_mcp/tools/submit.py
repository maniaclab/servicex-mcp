"""Tool for submitting a new ServiceX transform (query) request."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002
from servicex.dataset_identifier import (
    CERNOpenDataDatasetIdentifier,
    DataSetIdentifier,
    FileListDataset,
    RucioDatasetIdentifier,
    XRootDDatasetIdentifier,
)
from servicex.models import ResultFormat

from servicex_mcp.tools._helpers import (
    build_hints,
    check_write_allowed,
    classify_error,
    get_servicex_client,
)

DatasetKind = Literal["rucio", "file_list", "xrootd", "cernopendata"]


def _build_dataset_identifier(
    dataset: str, dataset_kind: str, num_files: int | None
) -> DataSetIdentifier:
    if dataset_kind == "rucio":
        return RucioDatasetIdentifier(dataset, num_files=num_files)
    if dataset_kind == "file_list":
        return FileListDataset(dataset.split(","))
    if dataset_kind == "xrootd":
        return XRootDDatasetIdentifier(dataset, num_files=num_files)
    if dataset_kind == "cernopendata":
        return CERNOpenDataDatasetIdentifier(int(dataset), num_files=num_files)
    msg = (
        f"Unknown dataset_kind {dataset_kind!r}; "
        "must be one of: rucio, file_list, xrootd, cernopendata"
    )
    raise ValueError(msg)


def register(mcp: MCPServer) -> None:
    """Register the query-submission tool with the MCP server."""

    @mcp.tool()
    async def servicex_submit_query(
        dataset: str,
        dataset_kind: DatasetKind,
        query: str,
        codegen: str,
        title: str = "ServiceX MCP Query",
        result_format: str = "parquet",
        num_files: int | None = None,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Submit a new transform request against a dataset.

        `dataset_kind` selects how `dataset` is interpreted:
        - "rucio": a Rucio DID, e.g. "mc20_13TeV:mc20_13TeV.700320.deriv.DAOD_PHYS"
        - "file_list": a comma-separated list of XRootD file URIs
        - "xrootd": an XRootD wildcard pattern
        - "cernopendata": a CERN Open Data numeric dataset ID

        `query` is the raw query string for the chosen `codegen` (e.g. a
        func_adl selection string, or a JSON uproot-raw spec). Use
        `servicex_list_code_generators` to see valid codegen names first.

        Returns the transform's request_id immediately — submission does
        not wait for the transform to finish. Poll progress with
        `servicex_get_transform_status`.
        """
        write_error = check_write_allowed(ctx.request_context.lifespan_context)
        if write_error:
            return write_error

        try:
            dsid = _build_dataset_identifier(dataset, dataset_kind, num_files)
            fmt = ResultFormat(result_format)
        except ValueError as exc:
            return f"Error: {exc}"

        try:
            client = get_servicex_client(ctx)
            # generic_query only builds a Query object (no I/O) — it is a
            # plain sync method, not a facade over asyncio.run(...), so it
            # is safe to call directly here.
            q = client.generic_query(
                dataset_identifier=dsid,
                query=query,
                codegen=codegen,
                title=title,
                result_format=fmt,
            )
            # submit_transform is a genuinely async method on ServiceXAdapter
            # (it awaits an httpx call internally) — await it directly rather
            # than wrapping in asyncio.to_thread.
            request_id = await q.servicex.submit_transform(q.transform_request)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [
                (
                    f"Use `servicex_get_transform_status` with "
                    f"request_id={request_id!r} to check progress"
                )
            ]
        )
        return f"Submitted transform. **request_id:** {request_id}" + hints
