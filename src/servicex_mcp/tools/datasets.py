"""Tools for inspecting and managing ServiceX cached datasets."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Any

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from servicex_mcp.tools._helpers import (
    build_hints,
    check_write_allowed,
    classify_error,
    format_dict,
    format_list,
    get_servicex_client,
    paginate_iter,
)

if TYPE_CHECKING:
    from servicex.models import CachedDataset

_DATASET_KEYS = [
    "id",
    "name",
    "did_finder",
    "n_files",
    "size",
    "events",
    "lookup_status",
    "is_stale",
    "last_used",
    "last_updated",
]

_BYTE_KEYS = frozenset({"size"})


def _dataset_to_dict(d: CachedDataset) -> dict[str, Any]:
    # CachedDataset.files (the per-file record list) is deliberately omitted:
    # n_files already gives the count, and per-file records would bloat this
    # summary view with no dedicated tool to drill into them yet.
    return {
        "id": d.id,
        "name": d.name,
        "did_finder": d.did_finder,
        "n_files": d.n_files,
        "size": d.size,
        "events": d.events,
        "lookup_status": d.lookup_status,
        "is_stale": d.is_stale,
        "last_used": str(d.last_used) if d.last_used else None,
        "last_updated": str(d.last_updated) if d.last_updated else None,
    }


class DatasetInfo(BaseModel):
    """Structured detail of one cached dataset, matching ``_dataset_to_dict``."""

    id: int
    name: str
    did_finder: str | None
    n_files: int | None
    size: int | None
    events: int | None
    lookup_status: str | None
    is_stale: bool | None
    last_used: str | None
    last_updated: str | None


class ServicexListDatasetsResult(BaseModel):
    """Structured result of ``servicex_list_datasets``."""

    datasets: list[DatasetInfo]
    offset: int
    limit: int
    truncated: bool


class ServicexDeleteDatasetResult(BaseModel):
    """Structured result of ``servicex_delete_dataset``."""

    dataset_id: int
    stale: bool


def register(mcp: MCPServer) -> None:
    """Register the dataset-related MCP tools.

    Registers servicex_list_datasets, servicex_get_dataset, and
    servicex_delete_dataset.
    """

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List datasets",
            read_only_hint=True,
            open_world_hint=True,
        )
    )
    async def servicex_list_datasets(
        did_finder: str | None = None,
        show_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, ServicexListDatasetsResult]:
        """List datasets cached on this ServiceX instance.

        Shows file/event counts and cache status for each dataset. Use
        `servicex_get_dataset` for full detail on one dataset.
        """
        try:
            client = get_servicex_client(ctx)
            # get_datasets is a sync facade that internally calls
            # asyncio.run(...); calling it directly here would raise
            # "asyncio.run() cannot be called from a running event loop"
            # since this tool already runs on the server's event loop.
            datasets = await asyncio.to_thread(
                client.get_datasets, did_finder, show_deleted
            )
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        if not datasets:
            payload = ServicexListDatasetsResult(
                datasets=[], offset=offset, limit=limit, truncated=False
            )
            return CallToolResult(
                content=[TextContent(type="text", text="No datasets found.")],
                structured_content=payload.model_dump(mode="json"),
            )
        rows, footer = paginate_iter(
            (_dataset_to_dict(d) for d in datasets), limit, offset
        )
        hints = build_hints(
            ["Use `servicex_get_dataset` with a dataset_id for full detail"]
        )
        text = (
            format_list(rows, include_keys=_DATASET_KEYS, byte_keys=_BYTE_KEYS)
            + footer
            + hints
        )
        payload = ServicexListDatasetsResult(
            datasets=[DatasetInfo(**row) for row in rows],
            offset=offset,
            limit=limit,
            truncated=bool(footer),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get dataset",
            read_only_hint=True,
            open_world_hint=True,
        )
    )
    async def servicex_get_dataset(
        dataset_id: int, *, ctx: Context[Any, Any]
    ) -> Annotated[CallToolResult, DatasetInfo]:
        """Get the full detail of one cached dataset by its dataset ID."""
        try:
            client = get_servicex_client(ctx)
            # See servicex_list_datasets: get_dataset is a sync facade over
            # asyncio.run(...) and must not be called directly here.
            d = await asyncio.to_thread(client.get_dataset, dataset_id)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        hints = build_hints(
            ["Use `servicex_delete_dataset` to remove this dataset from the cache"]
        )
        text = format_dict(_dataset_to_dict(d), byte_keys=_BYTE_KEYS) + hints
        payload = DatasetInfo(**_dataset_to_dict(d))
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Delete dataset",
            read_only_hint=False,
            destructive_hint=True,
        )
    )
    async def servicex_delete_dataset(
        dataset_id: int, *, ctx: Context[Any, Any]
    ) -> Annotated[CallToolResult, ServicexDeleteDatasetResult]:
        """Delete a cached dataset record by its dataset ID."""
        write_error = check_write_allowed(ctx.request_context.lifespan_context)
        if write_error:
            return write_error
        try:
            client = get_servicex_client(ctx)
            # See servicex_list_datasets: delete_dataset is a sync facade over
            # asyncio.run(...) and must not be called directly here.
            stale = await asyncio.to_thread(client.delete_dataset, dataset_id)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        # delete_dataset returns the server's "stale" flag for this dataset
        # record (servicex.servicex_adapter.ServiceXAdapter.delete_dataset),
        # not an unconditional success/failure signal — surface it rather
        # than assuming the delete always succeeded.
        text = f"Dataset {dataset_id} deleted (stale={stale})."
        payload = ServicexDeleteDatasetResult(dataset_id=dataset_id, stale=stale)
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )
