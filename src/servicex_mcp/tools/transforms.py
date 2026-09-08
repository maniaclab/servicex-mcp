"""Tools for inspecting and managing ServiceX transforms."""

from __future__ import annotations

from typing import Any

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

_TRANSFORM_KEYS = [
    "request_id",
    "title",
    "status",
    "files",
    "files_completed",
    "files_failed",
    "files_remaining",
    "submit_time",
    "finish_time",
]


def _transform_to_dict(t: Any) -> dict[str, Any]:
    return {
        "request_id": t.request_id,
        "title": t.title,
        "status": t.status.value if hasattr(t.status, "value") else t.status,
        "files": t.files,
        "files_completed": t.files_completed,
        "files_failed": t.files_failed,
        "files_remaining": t.files_remaining,
        "submit_time": str(t.submit_time) if t.submit_time else None,
        "finish_time": str(t.finish_time) if t.finish_time else None,
        "log_url": t.log_url,
    }


def register(mcp: MCPServer) -> None:
    """Register servicex_list_transforms, servicex_get_transform_status,
    servicex_cancel_transform, and servicex_delete_transform."""

    @mcp.tool()
    async def servicex_list_transforms(
        limit: int = 50, offset: int = 0, *, ctx: Context[Any, Any]
    ) -> str:
        """List transforms you have submitted to this ServiceX instance.

        Shows status, file completion counts, and timing for each transform.
        Use `servicex_get_transform_status` for full detail on one transform.
        """
        try:
            client = get_servicex_client(ctx)
            transforms = await client.get_transforms_async()
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        if not transforms:
            return "No transforms found."
        rows, footer = paginate_iter(
            (_transform_to_dict(t) for t in transforms), limit, offset
        )
        hints = build_hints(
            ["Use `servicex_get_transform_status` with a request_id for full detail"]
        )
        return format_list(rows, include_keys=_TRANSFORM_KEYS) + footer + hints

    @mcp.tool()
    async def servicex_get_transform_status(
        transform_id: str, *, ctx: Context[Any, Any]
    ) -> str:
        """Get the full status of one transform by its request ID.

        Includes the object-store/minio location details needed to fetch
        results once the transform completes.
        """
        try:
            client = get_servicex_client(ctx)
            t = await client.get_transform_status_async(transform_id)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        hints = build_hints(
            [
                "Use `servicex_cancel_transform` to stop a running transform",
                "Use `servicex_delete_transform` to remove a finished one",
            ]
        )
        return format_dict(_transform_to_dict(t)) + hints

    @mcp.tool()
    async def servicex_cancel_transform(
        transform_id: str, *, ctx: Context[Any, Any]
    ) -> str:
        """Cancel a running transform by its request ID."""
        write_error = check_write_allowed(ctx.request_context.lifespan_context)
        if write_error:
            return write_error
        try:
            client = get_servicex_client(ctx)
            client.cancel_transform(transform_id)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        return f"Transform {transform_id} cancelled."

    @mcp.tool()
    async def servicex_delete_transform(
        transform_id: str, *, ctx: Context[Any, Any]
    ) -> str:
        """Delete a transform record (and its cache entry) by request ID."""
        write_error = check_write_allowed(ctx.request_context.lifespan_context)
        if write_error:
            return write_error
        try:
            client = get_servicex_client(ctx)
            client.delete_transform(transform_id)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        return f"Transform {transform_id} deleted."
