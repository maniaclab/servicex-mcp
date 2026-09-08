"""Tools for inspecting and managing ServiceX cached datasets."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002

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


def register(mcp: MCPServer) -> None:
    """Register servicex_list_datasets, servicex_get_dataset, and
    servicex_delete_dataset."""

    @mcp.tool()
    async def servicex_list_datasets(
        did_finder: str | None = None,
        show_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
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
            return "No datasets found."
        rows, footer = paginate_iter(
            (_dataset_to_dict(d) for d in datasets), limit, offset
        )
        hints = build_hints(
            ["Use `servicex_get_dataset` with a dataset_id for full detail"]
        )
        return (
            format_list(rows, include_keys=_DATASET_KEYS, byte_keys=_BYTE_KEYS)
            + footer
            + hints
        )

    @mcp.tool()
    async def servicex_get_dataset(dataset_id: int, *, ctx: Context[Any, Any]) -> str:
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
        return format_dict(_dataset_to_dict(d), byte_keys=_BYTE_KEYS) + hints

    @mcp.tool()
    async def servicex_delete_dataset(
        dataset_id: int, *, ctx: Context[Any, Any]
    ) -> str:
        """Delete a cached dataset record by its dataset ID."""
        write_error = check_write_allowed(ctx.request_context.lifespan_context)
        if write_error:
            return write_error
        try:
            client = get_servicex_client(ctx)
            # See servicex_list_datasets: delete_dataset is a sync facade over
            # asyncio.run(...) and must not be called directly here.
            await asyncio.to_thread(client.delete_dataset, dataset_id)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        return f"Dataset {dataset_id} deleted."
