"""Shared helpers for MCP tool implementations."""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from servicex.servicex_client import ServiceXClient


def human_bytes(n: float | None) -> str:
    """Convert a byte count to a human-readable string.

    Uses binary units (1024-based): B, KB, MB, GB, TB, PB.

    Examples:
        >>> human_bytes(0)
        '0 B'
        >>> human_bytes(50000000000000)
        '45.47 TB'
        >>> human_bytes(None)
        'N/A'
    """
    if n is None:
        return "N/A"
    n = int(n)
    if n == 0:
        return "0 B"
    negative = n < 0
    n = abs(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            result = f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
            return f"-{result}" if negative else result
        n /= 1024
    return f"{n:.2f} PB"  # unreachable but satisfies type checker


def paginate_iter(
    it: Any,
    limit: int,
    offset: int = 0,
) -> tuple[list[Any], str]:
    """Consume an iterator up to ``offset + limit + 1`` items for pagination.

    More efficient than materializing the full iterator.

    Args:
        it: An iterable to consume.
        limit: Maximum items to return per page.
        offset: Number of items to skip before collecting results.

    Returns:
        A tuple of ``(page_items, footer_text)``.
    """
    # consume offset items first, then up to limit+1 to detect "more"
    consumed = list(itertools.islice(it, offset + limit + 1))
    window = consumed[offset : offset + limit + 1]
    if len(window) <= limit:
        return window, ""
    page = window[:limit]
    shown = offset + limit
    footer = (
        f"\n\n---\nShowing {limit} results (offset={offset}). "
        f"Pass `offset={shown}` to see more."
    )
    return page, footer


def build_hints(hints: list[str]) -> str:
    """Build a 'Next steps' footer from a list of hint strings.

    Args:
        hints: List of hint strings. Empty list returns empty string.

    Returns:
        A formatted markdown block, or empty string if no hints.
    """
    if not hints:
        return ""
    lines = "\n".join(f"- {h}" for h in hints)
    return f"\n\n**Next steps:**\n{lines}"


def classify_error(exc: Exception) -> str:
    """Return an actionable error message with recovery guidance.

    Pattern-matches on exception type name and message text to provide
    specific recovery steps rather than a bare traceback string.
    """
    exc_type = type(exc).__name__
    # A bare exception (e.g. a ProxyClient redeem call raising a timeout with
    # no message) has an empty str(exc) -- fall back to the type name so the
    # caller sees *something* happened instead of a blank "Error: " message.
    exc_msg = str(exc) or exc_type
    msg_lower = exc_msg.lower()
    type_lower = exc_type.lower()

    if "proxynotavailableerror" in type_lower:
        # Broker-mode only (BrokerServiceXClientFactory / _BrokerServiceXAdapter):
        # raised when the AF MCP broker has no linked ServiceX refresh token
        # for this caller (maniaclab/af-mcp-platform#295). Checked before the
        # generic authorizationerror/"not authorized" branch below since its
        # guidance ("re-paste a refresh token into this server's own bridge")
        # would be actively wrong here -- the caller never has ServiceX
        # credentials of its own in broker mode at all.
        guidance = (
            "No ServiceX credential is linked for you at the Analysis "
            "Facility broker. Link your ServiceX personal refresh token via "
            "the broker portal, then retry."
        )
    elif "proxyredeemerror" in type_lower:
        # Broker-mode only: the broker or servicex-token-service call itself
        # failed for an infra reason (distinct from "nothing is linked" above).
        guidance = (
            "The Analysis Facility broker failed to redeem your ServiceX "
            "credential -- this may be transient. Use `servicex_info` to "
            "check connectivity and try again, or contact your Analysis "
            "Facility operator if it persists."
        )
    elif "authorizationerror" in type_lower or "not authorized" in msg_lower:
        guidance = (
            "Not authorized to access this ServiceX instance. "
            "Use `servicex_info` to check connectivity, and confirm your "
            "refresh token is valid and not expired."
        )
    elif "not found" in msg_lower:
        guidance = (
            "The requested resource does not exist. "
            "Use `servicex_list_transforms` or `servicex_list_datasets` "
            "to find valid IDs."
        )
    elif "invalid transform request" in msg_lower:
        guidance = (
            "The transform request was rejected as malformed. "
            "Use `servicex_list_code_generators` to confirm the codegen name, "
            "and check the query string syntax for that codegen."
        )
    elif (
        "connectionerror" in type_lower
        or "connection" in msg_lower
        or "timeout" in type_lower
        or "timeout" in msg_lower
    ):
        guidance = (
            "Network or server error — this may be transient. "
            "Use `servicex_info` to check server connectivity and try again."
        )
    else:
        return f"Error: {exc_msg}"

    return f"Error: {exc_msg}\n\n**Recovery:** {guidance}"


_READ_ONLY_ERROR = (
    "Error: server is running in read-only mode (--read-only flag). "
    "This operation modifies ServiceX state and is not permitted."
)


def check_write_allowed(lifespan_context: dict[str, Any]) -> str | None:
    """Return an error string if write operations are disabled, else None."""
    if lifespan_context.get("read_only"):
        return _READ_ONLY_ERROR
    return None


# Fields whose values should be treated as byte counts for humanization.
_DEFAULT_BYTE_KEYS: frozenset[str] = frozenset(
    {
        "size",
        "file_size",
        "total_bytes",
    }
)


def format_dict(
    data: dict[str, Any],
    include_keys: list[str] | None = None,
    byte_keys: frozenset[str] | None = None,
) -> str:
    """Format a dict as a markdown key-value bullet list.

    Args:
        data: The dict to format.
        include_keys: If provided, only render these keys in this order.
            Keys absent from ``data`` are silently skipped.
            If ``None``, all non-None values are rendered (original behavior).
        byte_keys: Set of key names whose values should be humanized via
            ``human_bytes()``. Defaults to ``_DEFAULT_BYTE_KEYS``.
    """
    if byte_keys is None:
        byte_keys = _DEFAULT_BYTE_KEYS

    if include_keys is not None:
        pairs = [(k, data[k]) for k in include_keys if k in data]
    else:
        pairs = [(k, v) for k, v in data.items() if v is not None]

    lines = []
    for k, v in pairs:
        if v is None:
            continue
        display = (
            human_bytes(v) if k in byte_keys and isinstance(v, (int, float)) else v
        )
        lines.append(f"- **{k}:** {display}")
    return "\n".join(lines)


def _format_markdown_table(
    items: list[dict[str, Any]],
    keys: list[str],
    byte_keys: frozenset[str] | None = None,
) -> str:
    """Render a list of dicts as a markdown table."""
    if byte_keys is None:
        byte_keys = _DEFAULT_BYTE_KEYS

    def _cell(item: dict[str, Any], k: str) -> str:
        v = item.get(k, "")
        if k in byte_keys and isinstance(v, (int, float)):
            return human_bytes(v)
        return str(v) if v is not None else ""

    header = "| " + " | ".join(str(k) for k in keys) + " |"
    separator = "| " + " | ".join("---" for _ in keys) + " |"
    rows = ["| " + " | ".join(_cell(item, k) for k in keys) + " |" for item in items]
    return "\n".join([header, separator, *rows])


def format_list(
    items: list[Any],
    include_keys: list[str] | None = None,
    byte_keys: frozenset[str] | None = None,
) -> str:
    """Format a list of items as markdown.

    If all items are dicts with the same keys, renders as a markdown table.
    Otherwise renders as a bulleted list.

    Args:
        items: List of items to format.
        include_keys: If provided, only render these columns (in this order).
            Applied only when rendering as a table. For bullet-list fallback,
            also filters to these keys.
        byte_keys: Set of key names to humanize as byte counts.
            Defaults to ``_DEFAULT_BYTE_KEYS``.
    """
    if byte_keys is None:
        byte_keys = _DEFAULT_BYTE_KEYS

    if not items:
        return ""

    if all(isinstance(item, dict) for item in items):
        all_keys = list(items[0].keys())
        if all(list(item.keys()) == all_keys for item in items):
            keys = include_keys if include_keys is not None else all_keys
            # filter to only keys that actually exist in the data
            keys = [k for k in keys if k in all_keys]
            return _format_markdown_table(items, keys, byte_keys=byte_keys)

    lines = []
    for item in items:
        if isinstance(item, dict):
            if include_keys is not None:
                pairs = [(k, item[k]) for k in include_keys if k in item]
            else:
                pairs = list(item.items())
            parts = []
            for k, v in pairs:
                if v is None:
                    continue
                display = (
                    human_bytes(v)
                    if k in byte_keys and isinstance(v, (int, float))
                    else v
                )
                parts.append(f"**{k}:** {display}")
            lines.append("- " + ", ".join(parts))
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)


def get_servicex_client(ctx: Any) -> ServiceXClient:
    """Return the ServiceXClient for the current request via the lifespan factory."""
    factory = ctx.request_context.lifespan_context["client_factory"]
    client: ServiceXClient = factory.get_client(ctx)
    return client
