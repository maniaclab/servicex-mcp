# servicex-mcp Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (or superpowers:subagent-driven-development if executing in this session).

**Goal:** Build servicex-mcp — an MCP server wrapping the `servicex` PyPI package (`ServiceXClient`/`ServiceXAdapter`) — with both stdio and HTTP (CIMD OAuth, no DCR) transports, following the design in `docs/plans/2026-09-08-servicex-mcp-design.md`.

**Architecture:** Mirrors rucio-mcp/ami-mcp's package shape (`src/servicex_mcp/{cli,server,auth/*,tools/*}`, hatchling+hatch-vcs, pixi, pytest). Stdio builds one `ServiceXClient` from a local `.servicex`/`servicex.yaml`. HTTP mode is its own OAuth 2.1 AS (CIMD client identification, DCR disabled) whose `/bridge` interstitial is a synchronous "paste your ServiceX personal refresh token" form (no external IdP redirect/polling needed, unlike rucio) — the pasted refresh token is validated once, then returned verbatim as the MCP `access_token`, exactly as rucio-mcp passes through its rucio session token. Every tool gets its client via a `ServiceXClientFactory` ABC (`EnvBasedClientFactory` for stdio, `BearerTokenClientFactory` for HTTP), following the "Explicit inheritance over duck typing" rule in `~/.claude/CLAUDE.md`.

**Tech Stack:** Python ≥3.10, `mcp` SDK (`mcp.server.mcpserver.MCPServer`/`Context`), `servicex` PyPI package, `starlette`/`uvicorn` for HTTP, `httpx2` for CIMD fetches, `pytest`/`pytest-asyncio`, `hatchling`+`hatch-vcs`, `pixi`, `ruff`/`mypy`/`pylint` via pre-commit.

**Key reference files** (read-only, for copying patterns — never import from these):
- `/Users/kratsg/rucio-mcp/` — full reference implementation (OAuth bridge, CIMD, session cache, tool/test patterns)
- `/private/tmp/svx_check/extracted/servicex/` — unzipped `servicex` 3.3.1 wheel (the actual backend library: `servicex_client.py`, `servicex_adapter.py`, `configuration.py`, `models.py`, `dataset_identifier.py`)

---

## Task 0: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `pixi.toml`, `LICENSE`, `.gitignore`, `README.md`, `.pre-commit-config.yaml`
- Create: `src/servicex_mcp/__init__.py`, `src/servicex_mcp/py.typed`
- Create: `tests/__init__.py` (empty, if needed by pytest config — check rucio-mcp doesn't have one; skip if so)

**Step 1: Copy and adapt `.gitignore`**

Copy `/Users/kratsg/rucio-mcp/.gitignore` verbatim to `/Users/kratsg/servicex-mcp/.gitignore` (it's project-agnostic).

**Step 2: Write `LICENSE`**

Copy `/Users/kratsg/rucio-mcp/LICENSE` verbatim (same author/copyright holder, same Apache-2.0 license — confirm year is current, `2026`).

**Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.26", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "servicex-mcp"
authors = [
  { name = "Giordon Stark", email = "kratsg@gmail.com" },
]
description = "MCP Server for ServiceX"
readme = "README.md"
license = "Apache-2.0"
license-files = ["LICENSE"]
requires-python = ">=3.10"
classifiers = [
  "Development Status :: 1 - Planning",
  "Intended Audience :: Science/Research",
  "Intended Audience :: Developers",
  "Operating System :: OS Independent",
  "Programming Language :: Python",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3 :: Only",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Programming Language :: Python :: 3.14",
  "Topic :: Scientific/Engineering",
  "Typing :: Typed",
]
dynamic = ["version"]
dependencies = [
  "servicex>=3.3.0",
  "mcp>=2.0.0,<3",
  "httpx2>=2.0.0",
  "starlette>=0.27",
  "uvicorn>=0.31.1",
]

[project.scripts]
servicex-mcp = "servicex_mcp.cli:main"

[project.urls]
Documentation = "https://servicex-mcp.readthedocs.io/"
Homepage = "https://github.com/kratsg/servicex-mcp"
"Bug Tracker" = "https://github.com/kratsg/servicex-mcp/issues"
Discussions = "https://github.com/kratsg/servicex-mcp/discussions"
Changelog = "https://github.com/kratsg/servicex-mcp/releases"

[dependency-groups]
test = [
  "pytest >=9",
  "pytest-cov >=7",
  "pytest-asyncio >=0.24",
  "httpx >=0.27",
]
dev = [
  { include-group = "test" },
]
docs = [
  "zensical>=0.0.20",
]

[tool.uv]
exclude-newer = "7 days"

[tool.hatch]
version.source = "vcs"
build.hooks.vcs.version-file = "src/servicex_mcp/_version.py"

[tool.hatch.build.targets.wheel]
packages = ["src/servicex_mcp"]

[tool.pytest]
minversion = "9.0"
addopts = ["-ra", "--showlocals", "--strict-markers", "--strict-config"]
strict = true
filterwarnings = ["error"]
log_level = "INFO"
testpaths = ["tests"]
markers = [
    "slow: marks tests as slow (skipped by default, use --runslow to run)",
]
asyncio_mode = "auto"

[tool.coverage]
run.source = ["servicex_mcp"]
report.exclude_also = [
  '\.\.\.',
  'if typing.TYPE_CHECKING:',
]

[tool.mypy]
files = ["src", "tests"]
python_version = "3.10"
warn_unused_configs = true
strict = true
enable_error_code = ["ignore-without-code", "redundant-expr", "truthy-bool"]
warn_unreachable = true
disallow_untyped_defs = false
disallow_incomplete_defs = false

[[tool.mypy.overrides]]
module = "servicex_mcp.*"
disallow_untyped_defs = true
disallow_incomplete_defs = true

[[tool.mypy.overrides]]
module = ["servicex.*"]
ignore_missing_imports = true

[tool.ruff]
show-fixes = true

[tool.ruff.lint]
extend-select = [
  "ARG", "B", "BLE", "C4", "DTZ", "EM", "EXE", "FA", "FLY", "FURB", "G",
  "I", "ICN", "ISC", "LOG", "NPY", "PD", "PERF", "PGH", "PIE", "PL",
  "PT", "PTH", "PYI", "Q", "RET", "RSE", "RUF", "SIM", "SLOT", "T10",
  "T20", "TC", "TRY", "UP", "YTT",
]
ignore = ["PLR09", "PLR2004"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["T20"]

[tool.pylint]
py-version = "3.10"
ignore-paths = [".*/_version.py"]
reports.output-format = "colorized"
similarities.ignore-imports = "yes"
messages_control.disable = [
  "broad-exception-caught", "design", "duplicate-code", "fixme",
  "line-too-long", "missing-module-docstring", "missing-function-docstring",
  "wrong-import-order", "ungrouped-imports", "wrong-import-position",
]
```

**Step 4: Write `pixi.toml`**

Copy `/Users/kratsg/rucio-mcp/pixi.toml` and adapt:
- `name = "servicex-mcp"` everywhere (workspace name, `[package]` name)
- `[dependencies]` → `servicex-mcp = { path = "./" }` (drop the `af-credentials` line — no broker mode yet)
- `[exclude-newer]` block → remove (was only for af-credentials)
- `[package.run-dependencies]` → `servicex = ">=3.3.0"`, `mcp = ">=2.0.0,<3"`, `httpx2 = ">=2.0.0"` (drop `rich`, `rucio-clients`, `prometheus_client`, `ca-policy-lcg`, `voms`, `voms-lsc` — no VOMS/grid-cert dependency for ServiceX)
- Drop the `[feature.helm]` `helm-lint`/`helm-template` `--set auth.mode=broker` args (no broker mode yet) — keep a plain `helm template s charts/servicex-mcp --set ingress.host=servicex-mcp.example.com`
- Keep `[feature.test]`, `[feature.docs]`, `[feature.dev]`, `[environments]`, `[tasks]` sections structurally identical (same task names: `test`, `test-cov`, `test-slow`, `test-all`, `lint`, `check`, `build`, etc.)

**Step 5: Write `.pre-commit-config.yaml`**

Copy `/Users/kratsg/rucio-mcp/.pre-commit-config.yaml` verbatim — it is project-agnostic (same hook repos/revs).

**Step 6: Write `src/servicex_mcp/__init__.py`**

```python
"""Copyright (c) 2026 Giordon Stark. All rights reserved.

servicex-mcp: MCP Server for ServiceX
"""

from __future__ import annotations

from servicex_mcp._version import version as __version__

__all__ = ["__version__"]
```

**Step 7: Create empty `src/servicex_mcp/py.typed`**

**Step 8: Write a minimal `README.md`**

```markdown
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
```

**Step 9: Commit**

```bash
git add pyproject.toml pixi.toml LICENSE .gitignore .pre-commit-config.yaml README.md src/servicex_mcp/__init__.py src/servicex_mcp/py.typed
git commit -m "chore: scaffold servicex-mcp package"
```

Do **not** run `pixi install` / `git add` on `pixi.lock` yet — that happens naturally once dependencies resolve in Task 1's test run.

---

## Task 1: `auth/factory.py` — client factory ABC + stdio factory

**Files:**
- Create: `src/servicex_mcp/auth/__init__.py` (empty)
- Create: `src/servicex_mcp/auth/factory.py`
- Test: `tests/auth/__init__.py` (empty)
- Test: `tests/auth/test_factory.py`

**Step 1: Write the failing test**

```python
"""Tests for EnvBasedClientFactory."""

from __future__ import annotations

from unittest.mock import MagicMock

from servicex_mcp.auth.factory import EnvBasedClientFactory


class TestEnvBasedClientFactory:
    def test_get_client_returns_stored_client(self) -> None:
        client = MagicMock()
        factory = EnvBasedClientFactory(client=client)
        assert factory.get_client(MagicMock()) is client

    def test_get_client_ignores_ctx(self) -> None:
        client = MagicMock()
        factory = EnvBasedClientFactory(client=client)
        assert factory.get_client(None) is client

    def test_close_is_noop(self) -> None:
        factory = EnvBasedClientFactory(client=MagicMock())
        factory.close()  # must not raise
```

**Step 2: Run test to verify it fails**

Run: `pixi run -e py312 pytest tests/auth/test_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'servicex_mcp.auth'`

**Step 3: Write minimal implementation**

```python
"""ServiceX client factory: abstracts how the ServiceXClient is obtained per-request."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from servicex import ServiceXClient


class ServiceXClientFactory(ABC):
    """Returns the ServiceXClient appropriate for the current request/session."""

    @abstractmethod
    def get_client(self, ctx: Any) -> ServiceXClient:
        """Return the ServiceXClient for the given request context."""

    @abstractmethod
    def close(self) -> None:
        """Release any cached clients or resources."""


class EnvBasedClientFactory(ServiceXClientFactory):
    """Stdio-mode factory: wraps a single ServiceXClient built at startup."""

    def __init__(self, client: ServiceXClient) -> None:
        """Store the pre-built client."""
        self._client = client

    def get_client(self, _ctx: Any) -> ServiceXClient:
        """Return the single shared client regardless of context."""
        return self._client

    def close(self) -> None:
        """No-op: stdio client holds no per-request resources to release."""
```

**Step 4: Run test to verify it passes**

Run: `pixi run -e py312 pytest tests/auth/test_factory.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/servicex_mcp/auth/__init__.py src/servicex_mcp/auth/factory.py tests/auth/__init__.py tests/auth/test_factory.py
git commit -m "feat: add ServiceXClientFactory ABC and stdio EnvBasedClientFactory"
```

---

## Task 2: `tools/_helpers.py` — shared tool helpers

**Files:**
- Create: `src/servicex_mcp/tools/__init__.py` (empty)
- Create: `src/servicex_mcp/tools/_helpers.py`
- Test: `tests/test_helpers.py`

Port `human_bytes`, `paginate_iter`, `build_hints`, `format_dict`, `format_list`, `_format_markdown_table` from `/Users/kratsg/rucio-mcp/src/rucio_mcp/tools/_helpers.py` **verbatim** (they are domain-agnostic — no rucio-specific logic). Replace `get_rucio_client` with `get_servicex_client` (below). Skip `parse_did` (rucio-specific, not needed). Skip `RULE_LIST_KEYS` (rucio-specific).

**Step 1: Write the failing test** — port the equivalent assertions from `/Users/kratsg/rucio-mcp/tests/test_helpers.py` (read that file first for the exact test cases: `human_bytes` edge cases including `None`/negative/zero, `paginate_iter` under/over limit, `build_hints` empty/non-empty, `format_dict`/`format_list` table vs bullet fallback, byte-key humanization), plus:

```python
def test_get_servicex_client_reads_lifespan_context() -> None:
    from unittest.mock import MagicMock

    from servicex_mcp.auth.factory import EnvBasedClientFactory
    from servicex_mcp.tools._helpers import get_servicex_client

    client = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "client_factory": EnvBasedClientFactory(client=client),
        "read_only": False,
    }
    assert get_servicex_client(ctx) is client
```

**Step 2: Run test to verify it fails** — `ModuleNotFoundError`.

**Step 3: Write minimal implementation**

Copy `_helpers.py` from rucio-mcp, remove the `parse_did`/rucio-exception imports and `RULE_LIST_KEYS`, remove the `TOOL_ERRORS`/`current_tool_labels` metrics import (no Prometheus metrics module in v1 — plain `classify_error` without the `.inc()` calls; see below), and add:

```python
def get_servicex_client(ctx: Any) -> ServiceXClient:
    """Return the ServiceXClient for the current request via the lifespan factory."""
    factory = ctx.request_context.lifespan_context["client_factory"]
    client: ServiceXClient = factory.get_client(ctx)
    return client
```

(add `from servicex import ServiceXClient` under a `TYPE_CHECKING` guard at the top of the module — every future tool calls this, so it should carry a real return type rather than `Any` for mypy strict to catch mistakes on the resulting client's method calls.)

Rewrite `classify_error` for ServiceX exception types (no metrics call — v1 has no Prometheus wiring):

```python
def classify_error(exc: Exception) -> str:
    """Return an actionable error message with recovery guidance.

    Pattern-matches on exception type name and message text to provide
    specific recovery steps rather than a bare traceback string.
    """
    exc_type = type(exc).__name__
    exc_msg = str(exc)
    msg_lower = exc_msg.lower()
    type_lower = exc_type.lower()

    if "authorizationerror" in type_lower or "not authorized" in msg_lower:
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
```

Keep the `_DEFAULT_BYTE_KEYS` set but scope it to ServiceX's actual byte-valued fields: `frozenset({"size", "file_size", "total_bytes"})`.

**Step 4: Run test to verify it passes.**

**Step 5: Commit**

```bash
git add src/servicex_mcp/tools/__init__.py src/servicex_mcp/tools/_helpers.py tests/test_helpers.py
git commit -m "feat: add shared tool helpers (formatting, pagination, error classification)"
```

---

## Task 3: `tools/info.py` — server info + code generators

**Files:**
- Create: `src/servicex_mcp/tools/info.py`
- Test: `tests/test_tools_info.py`
- Modify: `tests/conftest.py` (create if not yet present — see Task 3a below, do this **first** if not already done)

### Task 3a (prerequisite): `tests/conftest.py`

**Step 1:** Write `tests/conftest.py`:

```python
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from servicex_mcp.auth.factory import EnvBasedClientFactory


@pytest.fixture
def mock_servicex_client() -> MagicMock:
    """Return a MagicMock that mimics servicex.ServiceXClient."""
    return MagicMock()


@pytest.fixture
def mock_ctx(mock_servicex_client: MagicMock) -> MagicMock:
    """Return a mock MCP Context with a factory-wrapped ServiceXClient."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.lifespan_context = {
        "client_factory": EnvBasedClientFactory(client=mock_servicex_client),
        "read_only": False,
    }
    return ctx


@pytest.fixture
def mock_ctx_readonly(mock_servicex_client: MagicMock) -> MagicMock:
    """Return a mock MCP Context with read_only=True."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.lifespan_context = {
        "client_factory": EnvBasedClientFactory(client=mock_servicex_client),
        "read_only": True,
    }
    return ctx


def pytest_addoption(parser: Any) -> None:
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )


def pytest_collection_modifyitems(config: Any, items: Any) -> None:
    if not config.getoption("--runslow"):
        skip_slow = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
```

No `RUCIO_CONFIG`-equivalent env fixture is needed — `ServiceXClient` methods on the mock never touch real config.

**Step 2:** Commit alongside Task 3's first commit (conftest has no tests of its own to fail/pass against).

### Task 3: `tools/info.py`

Note the real `ServiceXClient` has no single "info" method — `get_code_generators()` is the only info-ish call on the client itself (`get_servicex_info`/capabilities live on the lower-level adapter, `client.servicex.get_servicex_info()`). Expose both.

**Step 1: Write the failing test**

```python
"""Tests for servicex_info and servicex_list_code_generators tools."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from servicex_mcp.tools.info import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestServicexInfo:
    async def test_returns_capabilities(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        info = MagicMock(app_version="3.1.0", capabilities=["poll_local_transformation_results"])
        mock_servicex_client.servicex.get_servicex_info = MagicMock(
            return_value=_async_return(info)
        )
        fn = registered_tools["servicex_info"]
        result = await fn(ctx=mock_ctx)
        assert "3.1.0" in result

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        async def _raise() -> None:
            raise ConnectionError("unreachable")

        mock_servicex_client.servicex.get_servicex_info = MagicMock(
            side_effect=lambda: _raise()
        )
        fn = registered_tools["servicex_info"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")


class TestServicexListCodeGenerators:
    async def test_returns_generators(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.get_code_generators.return_value = {
            "uproot-raw": "sslhep/servicex_func_adl_uproot_codegen:v1",
            "python": "sslhep/servicex_generic_codegen:v1",
        }
        fn = registered_tools["servicex_list_code_generators"]
        result = await fn(ctx=mock_ctx)
        assert "uproot-raw" in result

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_servicex_client.get_code_generators.side_effect = RuntimeError("boom")
        fn = registered_tools["servicex_list_code_generators"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")


def _async_return(value: object) -> object:
    async def _coro() -> object:
        return value

    return _coro()
```

**Step 2: Run to verify it fails** — `ModuleNotFoundError: No module named 'servicex_mcp.tools.info'`.

**Step 3: Write minimal implementation**

```python
"""Tools for ServiceX server connectivity and code generator discovery."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002

from servicex_mcp.tools._helpers import (
    build_hints,
    classify_error,
    format_dict,
    get_servicex_client,
)


def register(mcp: MCPServer) -> None:
    """Register servicex_info and servicex_list_code_generators with the MCP server."""

    @mcp.tool()
    async def servicex_info(*, ctx: Context[Any, Any]) -> str:
        """Return the ServiceX server version and its advertised capabilities.

        Use this tool to verify the ServiceX backend is reachable and to see
        which optional server capabilities are available (e.g. whether
        long sample titles or local-transform polling are supported).
        """
        try:
            client = get_servicex_client(ctx)
            info = await client.servicex.get_servicex_info()
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        lines = [
            f"- **app_version:** {info.app_version}",
            f"- **capabilities:** {', '.join(info.capabilities) or '(none)'}",
        ]
        hints = build_hints(["Use `servicex_list_code_generators` to see available codegens"])
        return "\n".join(lines) + hints

    @mcp.tool()
    async def servicex_list_code_generators(*, ctx: Context[Any, Any]) -> str:
        """List the code generators deployed on this ServiceX instance.

        Each code generator (e.g. `func_adl_uproot`, `python`, `uproot-raw`)
        maps to a query language you can use with `servicex_submit_query`.
        """
        try:
            client = get_servicex_client(ctx)
            generators = client.get_code_generators()
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        if not generators:
            return "No code generators are registered on this ServiceX instance."
        hints = build_hints(
            ["Use `servicex_submit_query` with one of these codegen names"]
        )
        return format_dict(generators) + hints
```

(This is what was actually implemented and committed for Task 3 — corrected here to match, after code review moved client acquisition inside the `try` and switched to `format_dict` for the plain-dict codegen output.)

**Step 4: Run test to verify it passes.**

**Step 5: Commit**

```bash
git add src/servicex_mcp/tools/info.py tests/test_tools_info.py tests/conftest.py
git commit -m "feat: add servicex_info and servicex_list_code_generators tools"
```

---

## Task 4: `tools/transforms.py` — list/get/cancel/delete transforms

**Files:**
- Create: `src/servicex_mcp/tools/transforms.py`
- Test: `tests/test_tools_transforms.py`

Client methods used (all on `ServiceXClient`, async, wrapped by `make_sync` on the real client but our tool code calls the `_async` variants directly since MCP tools are already async): `get_transforms_async() -> list[TransformStatus]`, `get_transform_status_async(transform_id) -> TransformStatus`, `cancel_transform(transform_id)` (sync-wrapped via `_async_execute_and_wait`, no async variant exposed — call as a blocking call inside the async tool function is acceptable here since it's a lightweight HTTP round-trip; if this proves an issue in review, wrap with `asyncio.to_thread`), `delete_transform(transform_id)`.

`TransformStatus` fields to surface (see `servicex/models.py`): `request_id`, `title`, `status` (enum, use `.value`), `files`, `files_completed`, `files_failed`, `files_remaining`, `submit_time`, `finish_time`, `result_format` (enum `.value`), `log_url`.

**Step 1: Write the failing test** (follow the `ping.py`/`test_tools_ping.py` pattern from rucio-mcp: one `registered_tools` fixture building `MCPServer("test")` + `register(mcp)`, one test class per tool, a happy-path test asserting key fields appear in the output, and an error-path test asserting `result.startswith("Error:")`). Cover:
- `servicex_list_transforms`: returns a table when `get_transforms_async` returns a list of `TransformStatus`-shaped mocks (use `MagicMock(request_id=..., title=..., status=MagicMock(value="Complete"), ...)` or build real `servicex.models.TransformStatus` instances — prefer real model instances so field-name typos are caught); empty list → "No transforms found." message; pagination via `limit`/`offset`.
- `servicex_get_transform_status`: happy path + "not found" (`ValueError` from the adapter) → error path.
- `servicex_cancel_transform`: happy path; **read-only mode blocks it** (assert `check_write_allowed` gate — use `mock_ctx_readonly`, assert result equals the read-only error string).
- `servicex_delete_transform`: same read-only gating test.

**Step 2: Run to verify it fails.**

**Step 3: Write minimal implementation**

```python
"""Tools for inspecting and managing ServiceX transforms."""

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
    from servicex.models import TransformStatus

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


def _transform_to_dict(t: TransformStatus) -> dict[str, Any]:
    return {
        "request_id": t.request_id,
        "title": t.title,
        "status": t.status.value,
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

        Includes a log_url for debugging once the transform completes.
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
            # cancel_transform is a sync facade that internally calls
            # asyncio.run(...); calling it directly here would raise
            # "asyncio.run() cannot be called from a running event loop"
            # since this tool already runs on the server's event loop.
            await asyncio.to_thread(client.cancel_transform, transform_id)
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
            # See servicex_cancel_transform: delete_transform is a sync facade
            # over asyncio.run(...) and must not be called directly here.
            await asyncio.to_thread(client.delete_transform, transform_id)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        return f"Transform {transform_id} deleted."
```

Note: `client = get_servicex_client(ctx)` is deliberately called **inside** the `try` block in every tool (not before it) — once `BearerTokenClientFactory` (Task 13) lands, `get_client` can raise on a missing/malformed bearer token, and that failure should route through `classify_error` like any other client-side error, not propagate as an unhandled exception. Apply this ordering in every tool module from here on (Tasks 5, 6, and onward), even though the current `EnvBasedClientFactory.get_client` is a plain dict lookup that can't raise. Likewise, prefer `format_dict`/`format_list` over hand-rolled `f"- **{k}:** {v}"` loops wherever the data is already a plain dict — `info.py` (Task 3) was corrected to follow both of these after code review; don't reintroduce either pattern.

**Step 4: Run test to verify it passes.**

**Step 5: Commit**

```bash
git add src/servicex_mcp/tools/transforms.py tests/test_tools_transforms.py
git commit -m "feat: add transform inspection and management tools"
```

---

## Task 5: `tools/datasets.py` — list/get/delete cached datasets

**Files:**
- Create: `src/servicex_mcp/tools/datasets.py`
- Test: `tests/test_tools_datasets.py`

Same pattern as Task 4. Client methods: `get_datasets(did_finder=None, show_deleted=False) -> list[CachedDataset]`, `get_dataset(dataset_id) -> CachedDataset`, `delete_dataset(dataset_id) -> bool` — **all three are sync facades that internally call `_async_execute_and_wait(coro) = asyncio.run(coro)`**, not `_async`-suffixed async methods. Task 4's code-quality review caught this exact pattern on `cancel_transform`/`delete_transform`: calling a sync-over-`asyncio.run` method directly from inside an already-running async MCP tool raises `RuntimeError: asyncio.run() cannot be called from a running event loop` (verified empirically). Every call to `get_datasets`, `get_dataset`, and `delete_dataset` in this task's tools MUST be wrapped in `await asyncio.to_thread(client.get_datasets, did_finder, show_deleted)` (etc.) — never called directly. Write a test for each tool that reproduces this failure mode if the wrapping is removed (see `tests/test_tools_transforms.py`'s `_sync_facade_over_asyncio_run()` helper for the pattern: a mock `side_effect` that itself calls `asyncio.run(...)` on a trivial coroutine, so a regression is a failing test, not a silently-green suite with a MagicMock that never touches real asyncio machinery).

`CachedDataset` fields (`servicex/models.py`): `id`, `name`, `did_finder`, `n_files`, `size` (byte-key!), `events`, `last_used`, `last_updated`, `lookup_status`, `is_stale`.

**Step 1–5:** Same TDD cycle as Task 4. Tool signatures:

```python
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
            stale = await asyncio.to_thread(client.delete_dataset, dataset_id)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        # delete_dataset returns the server's "stale" flag for this dataset
        # record (servicex.servicex_adapter.ServiceXAdapter.delete_dataset),
        # not an unconditional success/failure signal — surface it rather
        # than assuming the delete always succeeded.
        return f"Dataset {dataset_id} deleted (stale={stale})."
```

Pass `byte_keys=frozenset({"size"})` to `format_list`/`format_dict` calls for datasets so `size` renders humanized (e.g. "45.47 TB") while `n_files`/`events` stay raw counts.

Include a `did_not_found`-style branch check: `get_dataset`/`delete_dataset` raise `ValueError(f"Dataset {dataset_id} not found")` on 404 — verify `classify_error` routes this through the "not found" branch from Task 2 (add a dataset-specific hint there if the generic "not found" guidance doesn't read naturally — reword to "Use `servicex_list_datasets` to find valid dataset IDs" if the test wants dataset-specific wording; a `resource_hint` parameter on `classify_error` is over-engineering for this — just keep the generic wording, it already names two list tools).

Commit: `feat: add cached dataset inspection and management tools`

---

## Task 6: `tools/submit.py` — submit a query (the core value-add)

**Files:**
- Create: `src/servicex_mcp/tools/submit.py`
- Test: `tests/test_tools_submit.py`

This is the tool that actually runs a query. Read `/private/tmp/svx_check/extracted/servicex/dataset_identifier.py` and the `generic_query`/`Query.transform_request` code in `/private/tmp/svx_check/extracted/servicex/servicex_client.py` (lines ~468-525) and `/private/tmp/svx_check/extracted/servicex/query_core.py` (lines ~129-150) before writing this — you already have them open in context from the design phase; re-read if not.

Key design point: **do not** use `Query.submit_and_download` / `as_files_async` (they block until the transform completes and download results — wrong shape for an MCP tool call). Instead:
1. Build a `DataSetIdentifier` from `dataset` + `dataset_kind`.
2. Call `client.generic_query(dataset_identifier=..., query=query, codegen=codegen, title=title, result_format=result_format)` — this returns a `Query` object **without submitting anything**.
3. Call `await query.servicex.submit_transform(query.transform_request)` directly on the adapter — this submits and returns the `request_id` immediately, no polling/downloading.

**Step 1: Write the failing test**

```python
"""Tests for servicex_submit_query."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.mcpserver import MCPServer
from servicex.dataset_identifier import (
    CERNOpenDataDatasetIdentifier,
    FileListDataset,
    RucioDatasetIdentifier,
    XRootDDatasetIdentifier,
)

from servicex_mcp.tools.submit import _build_dataset_identifier, register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class TestBuildDatasetIdentifier:
    def test_rucio(self) -> None:
        dsid = _build_dataset_identifier(
            "mc20_13TeV:mc20_13TeV.700320.deriv.DAOD_PHYS", "rucio", None
        )
        assert isinstance(dsid, RucioDatasetIdentifier)
        assert dsid.dataset == "mc20_13TeV:mc20_13TeV.700320.deriv.DAOD_PHYS"

    def test_rucio_passes_num_files(self) -> None:
        dsid = _build_dataset_identifier("ns:name", "rucio", 5)
        assert isinstance(dsid, RucioDatasetIdentifier)
        assert dsid.num_files == 5

    def test_file_list_splits_on_comma(self) -> None:
        dsid = _build_dataset_identifier(
            "root://a.root,root://b.root", "file_list", None
        )
        assert isinstance(dsid, FileListDataset)
        assert dsid.files == ["root://a.root", "root://b.root"]

    def test_file_list_strips_whitespace_around_entries(self) -> None:
        # A natural "a, b" list (comma + space) must not bake a leading
        # space into the second URI — that would silently fail only that
        # one file at transform time instead of raising here.
        dsid = _build_dataset_identifier(
            "root://a.root, root://b.root", "file_list", None
        )
        assert isinstance(dsid, FileListDataset)
        assert dsid.files == ["root://a.root", "root://b.root"]

    def test_xrootd(self) -> None:
        dsid = _build_dataset_identifier("root://*/data*.root", "xrootd", 10)
        assert isinstance(dsid, XRootDDatasetIdentifier)
        assert dsid.dataset == "root://*/data*.root"
        assert dsid.num_files == 10

    def test_cernopendata(self) -> None:
        dsid = _build_dataset_identifier("12345", "cernopendata", None)
        assert isinstance(dsid, CERNOpenDataDatasetIdentifier)
        assert dsid.dataset == "12345"

    def test_unknown_kind_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown dataset_kind"):
            _build_dataset_identifier("x", "not-a-kind", None)


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestServicexSubmitQuery:
    async def test_submits_rucio_dataset_and_returns_request_id(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_query = MagicMock()
        mock_query.servicex.submit_transform = AsyncMock(return_value="req-123")
        mock_servicex_client.generic_query.return_value = mock_query

        fn = registered_tools["servicex_submit_query"]
        result = await fn(
            dataset="mc20_13TeV:mc20_13TeV.700320.deriv.DAOD_PHYS",
            dataset_kind="rucio",
            query="(call ResultTTree ...)",
            codegen="atlasr22",
            ctx=mock_ctx,
        )
        assert "req-123" in result
        mock_servicex_client.generic_query.assert_called_once()
        call_kwargs = mock_servicex_client.generic_query.call_args.kwargs
        assert call_kwargs["codegen"] == "atlasr22"

    async def test_rejects_unknown_dataset_kind(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["servicex_submit_query"]
        result = await fn(
            dataset="x", dataset_kind="not-a-kind", query="q", codegen="c", ctx=mock_ctx
        )
        assert result.startswith("Error:")

    async def test_rejects_unknown_result_format(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["servicex_submit_query"]
        result = await fn(
            dataset="ns:name",
            dataset_kind="rucio",
            query="q",
            codegen="c",
            result_format="xml",
            ctx=mock_ctx,
        )
        assert result.startswith("Error:")

    async def test_read_only_mode_blocks_submission(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
    ) -> None:
        fn = registered_tools["servicex_submit_query"]
        result = await fn(
            dataset="x",
            dataset_kind="rucio",
            query="q",
            codegen="c",
            ctx=mock_ctx_readonly,
        )
        assert "read-only" in result.lower()

    async def test_returns_error_on_submit_failure(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_servicex_client: MagicMock,
    ) -> None:
        mock_query = MagicMock()
        mock_query.servicex.submit_transform = AsyncMock(
            side_effect=ValueError("Invalid transform request: bad codegen")
        )
        mock_servicex_client.generic_query.return_value = mock_query
        fn = registered_tools["servicex_submit_query"]
        result = await fn(
            dataset="x", dataset_kind="rucio", query="q", codegen="c", ctx=mock_ctx
        )
        assert result.startswith("Error:")
```

**Step 2: Run to verify it fails.**

**Step 3: Write minimal implementation**

```python
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
ResultFormatName = Literal["parquet", "root-file", "root-rntuple"]


def _build_dataset_identifier(
    dataset: str, dataset_kind: str, num_files: int | None
) -> DataSetIdentifier:
    if dataset_kind == "rucio":
        return RucioDatasetIdentifier(dataset, num_files=num_files)
    if dataset_kind == "file_list":
        # Strip whitespace around each URI: an LLM naturally formats a list
        # as "a, b" (comma + space); an un-stripped leading space becomes
        # part of the file URI and silently fails only that one file at
        # transform time (files_failed), not at submission.
        return FileListDataset([f.strip() for f in dataset.split(",")])
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
        result_format: ResultFormatName = "parquet",
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

        `result_format` is one of "parquet" (default), "root-file", or
        "root-rntuple".

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
```

**Step 4: Run test to verify it passes.**

**Step 5: Commit**

```bash
git add src/servicex_mcp/tools/submit.py tests/test_tools_submit.py
git commit -m "feat: add servicex_submit_query tool"
```

---

## Task 7: `server.py` (stdio) + `cli.py` (stdio `serve`)

**Files:**
- Create: `src/servicex_mcp/server.py`
- Create: `src/servicex_mcp/cli.py`
- Test: `tests/test_server.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test** (`tests/test_server.py`)

```python
"""Tests for _make_stdio_mcp."""

from __future__ import annotations

from unittest.mock import patch

from servicex_mcp.server import _make_stdio_mcp


class TestMakeStdioMcp:
    def test_registers_expected_tools(self) -> None:
        with patch("servicex_mcp.server.ServiceXClient"):
            mcp = _make_stdio_mcp(backend="test-backend")
        names = {tool.name for tool in mcp._tool_manager.list_tools()}
        assert "servicex_info" in names
        assert "servicex_list_transforms" in names
        assert "servicex_submit_query" in names

    def test_read_only_flag_propagates_to_lifespan(self) -> None:
        with patch("servicex_mcp.server.ServiceXClient"):
            mcp = _make_stdio_mcp(backend="test-backend", read_only=True)
        assert mcp is not None  # lifespan_context is only populated once entered;
        # a fuller assertion requires an async lifespan test — see below.
```

Add an async test that actually enters the lifespan context manager to assert `read_only` is threaded through (follow rucio-mcp's `tests/test_server.py` for the exact pattern of entering `mcp._lifespan` via `AsyncExitStack` if that's how it tests it — read that file first for the idiom used there before writing this test).

**Step 2: Run to verify it fails.**

**Step 3: Write minimal implementation** (`src/servicex_mcp/server.py`)

```python
"""FastMCP server setup for servicex-mcp (stdio transport)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer
from servicex import ServiceXClient

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from servicex_mcp.auth.factory import EnvBasedClientFactory
from servicex_mcp.tools import datasets, info, submit, transforms

_STDIO_PREAMBLE = (
    "MCP server for ServiceX data delivery. "
    "Provides tools to discover code generators, submit transform (query) "
    "requests against a dataset, and inspect/manage transforms and cached "
    "datasets. Authentication is configured via a local .servicex/servicex.yaml "
    "file (selected with --backend) before starting the server."
)


def _make_stdio_mcp(
    *, backend: str | None = None, config_path: str | None = None, read_only: bool = False
) -> MCPServer:
    """Build and return a configured MCPServer instance for stdio transport."""

    @asynccontextmanager
    async def _lifespan(_server: MCPServer) -> AsyncGenerator[dict[str, Any], None]:
        client = ServiceXClient(backend=backend, config_path=config_path)
        factory = EnvBasedClientFactory(client=client)
        try:
            yield {"client_factory": factory, "read_only": read_only}
        finally:
            factory.close()

    mcp = MCPServer("servicex-mcp", lifespan=_lifespan, instructions=_STDIO_PREAMBLE)

    for _module in [info, transforms, datasets, submit]:
        _module.register(mcp)

    return mcp


def serve(*, backend: str | None, config_path: str | None, read_only: bool) -> None:
    """Entry point used by the CLI's `serve` subcommand (stdio only, for now)."""
    mcp = _make_stdio_mcp(backend=backend, config_path=config_path, read_only=read_only)
    mcp.run(transport="stdio")
```

Note: `_make_stdio_mcp` builds the real `ServiceXClient(backend=..., config_path=...)` eagerly inside the lifespan (not at module import time) so tests can `patch("servicex_mcp.server.ServiceXClient")` without a real `.servicex` file existing — mirror rucio-mcp's approach of constructing `Client()` inside `_lifespan`, not outside it.

**Step 4: Run test to verify it passes.**

**Step 5: Write `cli.py`**

```python
"""Command-line interface for servicex-mcp."""

from __future__ import annotations

import argparse
import logging
import sys

from servicex_mcp.server import serve


def main() -> None:
    """Entry point for the servicex-mcp command."""
    parser = argparse.ArgumentParser(
        prog="servicex-mcp",
        description="MCP Server for ServiceX",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    serve_parser = subparsers.add_parser("serve", help="Start the MCP server")
    serve_parser.add_argument(
        "--read-only",
        action="store_true",
        default=False,
        help="Disable all write operations (submit/cancel/delete).",
    )
    serve_parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="Transport to use (default: stdio).",
    )
    serve_parser.add_argument(
        "--backend",
        default=None,
        metavar="NAME",
        help="Name of the ServiceX backend to use, as configured in your "
        ".servicex/servicex.yaml file (defaults to that file's default-endpoint).",
    )
    serve_parser.add_argument(
        "--config-path",
        default=None,
        metavar="PATH",
        help="Path to a .servicex/servicex.yaml file (default: search cwd upward, then $HOME).",
    )
    serve_parser.add_argument(
        "--log-level",
        default="info",
        choices=("debug", "info", "warning", "error"),
        help="Logging verbosity (default: info).",
    )

    args = parser.parse_args()

    if args.command == "serve":
        logging.basicConfig(
            level=getattr(logging, args.log_level.upper()),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        if args.transport == "stdio":
            serve(backend=args.backend, config_path=args.config_path, read_only=args.read_only)
        else:
            # HTTP transport is wired in Task 13 (cli http args) — placeholder
            # error until that task lands, so `--transport http` fails loudly
            # rather than silently starting stdio.
            print("HTTP transport is not yet implemented.", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(0)
```

(Task 13 replaces the `else` branch with the real HTTP wiring — leaving a loud placeholder here keeps this task's tests honest: don't assert HTTP behavior yet.)

**Step 6: Write `tests/test_cli.py`** — mirror `/Users/kratsg/rucio-mcp/tests/test_cli.py` structure: test argparse defaults, test `serve` subcommand dispatches to `servicex_mcp.server.serve` with the right kwargs (patch it), test `--help` doesn't crash. Read that file for the exact assertions/idioms used (e.g. `capsys`, `monkeypatch.setattr`).

**Step 7: Run all tests, verify pass.**

**Step 8: Commit**

```bash
git add src/servicex_mcp/server.py src/servicex_mcp/cli.py tests/test_server.py tests/test_cli.py
git commit -m "feat: add stdio server and CLI serve command"
```

At this point `servicex-mcp serve` works end-to-end in stdio mode. This is a natural checkpoint — consider running `pixi run test` for the full suite before continuing to HTTP mode.

---

## Task 8: `auth/session_cache.py` (HTTP mode — generic, reusable)

**Files:**
- Create: `src/servicex_mcp/auth/session_cache.py`
- Test: `tests/auth/test_session_cache.py`

Copy `/Users/kratsg/rucio-mcp/src/rucio_mcp/auth/session_cache.py` **verbatim** except: rename the `Client` type import/hint from `rucio.client` to `servicex.ServiceXClient` (under `TYPE_CHECKING`), and drop the rucio-specific docstring wording ("rucio Clients" → "ServiceXClient instances"). Logic is unchanged (thread-safe TTL dict, `get`/`put`/`size`/`close`).

Copy `/Users/kratsg/rucio-mcp/tests/auth/test_session_cache.py` verbatim (it only exercises TTL/threading behavior generically — check it doesn't reference `rucio.client.Client` directly; if it does, swap the mock type).

TDD steps: write test (ported), run to confirm fail, write implementation (ported+renamed), run to confirm pass, commit:

```bash
git add src/servicex_mcp/auth/session_cache.py tests/auth/test_session_cache.py
git commit -m "feat: add SessionCache for HTTP-mode client caching"
```

---

## Task 9: `auth/cimd.py` (HTTP mode — generic, reusable almost verbatim)

**Files:**
- Create: `src/servicex_mcp/auth/cimd.py`
- Test: `tests/auth/test_cimd.py`

This module has **zero rucio-specific logic** (confirmed by reading it during design) — it's pure CIMD/OAuth client-metadata resolution. Copy `/Users/kratsg/rucio-mcp/src/rucio_mcp/auth/cimd.py` verbatim, only editing the module docstring's two mentions of "rucio-mcp" → "servicex-mcp" and the GitHub issue URL reference (drop the specific issue link, replace with a generic comment: `# Same rationale as rucio-mcp: https://github.com/kratsg/rucio-mcp/issues/33`).

Copy `/Users/kratsg/rucio-mcp/tests/auth/test_cimd.py` verbatim (it's also generic — exercises `is_cimd_client_id`, `redirect_uri_matches`, `assert_safe_url` SSRF guard, `fetch_client_document`, `build_client_from_document`, `resolve_cimd_client` against a fake resolver/httpx mock transport, none of it rucio-specific).

TDD: write (ported) test file, confirm fail (`ModuleNotFoundError`), write (ported) implementation, confirm pass, commit:

```bash
git add src/servicex_mcp/auth/cimd.py tests/auth/test_cimd.py
git commit -m "feat: add CIMD client-metadata resolution for HTTP OAuth (no DCR)"
```

---

## Task 10: `auth/bridge_state.py` — adapted for synchronous PAT validation

**Files:**
- Create: `src/servicex_mcp/auth/bridge_state.py`
- Test: `tests/auth/test_bridge_state.py`

Adapt `/Users/kratsg/rucio-mcp/src/rucio_mcp/auth/bridge_state.py`. Differences from rucio's version:
- No `polling_url` field (there's no external IdP redirect to poll — the `/bridge` page itself is the paste-a-token form).
- Rename `rucio_token` → `servicex_token` on `BridgeSession` and in `mark_done`'s signature/kwarg.
- Everything else (TTL eviction, `_by_session`/`_by_code` indices, `pop_by_auth_code` single-use semantics, `mark_error`, `session_counts`) is unchanged — copy verbatim otherwise.

**Step 1: Write the failing test** — port `/Users/kratsg/rucio-mcp/tests/auth/test_bridge_state.py` verbatim, renaming `rucio_token`→`servicex_token` and dropping any `polling_url` references/assertions.

**Step 2: Run to verify it fails.**

**Step 3: Write implementation:**

```python
"""In-memory state store for in-flight OAuth bridge sessions.

Each bridge session tracks the lifecycle of one user's authentication:
  pending  →  (pasted ServiceX refresh token validated)  →  done
  pending  →  (invalid token / error)                    →  error

Unlike rucio-mcp's bridge (which polls an external IdP redirect), validation
here is synchronous: the /bridge form POST validates the token against
ServiceX's own /token/refresh in the same request, so sessions move from
pending to done/error within a single request-response cycle — there is no
background polling task.

Sessions are evicted after 5 minutes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class BridgeSession:
    """State for one in-flight bridge session."""

    session_id: str
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    client_id: str
    scopes: list[str]
    resource: str | None
    state: str | None
    expires_at: float
    status: str = "pending"  # "pending" | "done" | "error"
    servicex_token: str | None = None
    auth_code: str | None = None
    error_message: str | None = None


class BridgeStateStore:
    """Thread-safe in-memory store for :class:`BridgeSession` objects."""

    _TTL: float = 300.0

    def __init__(self) -> None:
        """Initialize thread-safe in-memory store."""
        self._lock = threading.Lock()
        self._by_session: dict[str, BridgeSession] = {}
        self._by_code: dict[str, str] = {}

    def put(self, session: BridgeSession) -> None:
        """Store *session*, replacing any existing entry with the same ID."""
        with self._lock:
            self._evict_locked()
            self._by_session[session.session_id] = session

    def get_by_session_id(self, session_id: str) -> BridgeSession | None:
        """Return the session or ``None`` if it does not exist or has expired."""
        with self._lock:
            self._evict_locked()
            return self._by_session.get(session_id)

    def get_by_auth_code(self, auth_code: str) -> BridgeSession | None:
        """Return the session associated with *auth_code*, or ``None`` if expired."""
        with self._lock:
            session_id = self._by_code.get(auth_code)
            if session_id is None:
                return None
            session = self._by_session.get(session_id)
            if session is not None and session.expires_at <= time.time():
                self._by_session.pop(session_id, None)
                self._by_code.pop(auth_code, None)
                return None
            return session

    def pop_by_auth_code(self, auth_code: str) -> BridgeSession | None:
        """Atomically remove and return the session for *auth_code* (single-use)."""
        with self._lock:
            session_id = self._by_code.pop(auth_code, None)
            if session_id is None:
                return None
            return self._by_session.pop(session_id, None)

    def mark_done(self, session_id: str, *, servicex_token: str, auth_code: str) -> None:
        """Transition *session_id* to ``done`` and register the auth code index."""
        with self._lock:
            s = self._by_session.get(session_id)
            if s is None:
                return
            s.status = "done"
            s.servicex_token = servicex_token
            s.auth_code = auth_code
            self._by_code[auth_code] = session_id

    def mark_error(self, session_id: str, message: str) -> None:
        """Transition *session_id* to ``error`` with a human-readable *message*."""
        with self._lock:
            s = self._by_session.get(session_id)
            if s is None:
                return
            s.status = "error"
            s.error_message = message

    def session_counts(self) -> dict[str, int]:
        """Return a count of live sessions keyed by status."""
        with self._lock:
            self._evict_locked()
            counts: dict[str, int] = {}
            for s in self._by_session.values():
                counts[s.status] = counts.get(s.status, 0) + 1
            return counts

    def _evict_locked(self) -> None:
        now = time.time()
        expired = [sid for sid, s in self._by_session.items() if s.expires_at <= now]
        for sid in expired:
            s = self._by_session.pop(sid)
            if s.auth_code:
                self._by_code.pop(s.auth_code, None)
```

**Step 4: Run test to verify it passes.**

**Step 5: Commit**

```bash
git add src/servicex_mcp/auth/bridge_state.py tests/auth/test_bridge_state.py
git commit -m "feat: add BridgeStateStore for synchronous PAT-paste bridge sessions"
```

---

## Task 11: `auth/bridge_provider.py` — `ServiceXBridgeProvider`

**Files:**
- Create: `src/servicex_mcp/auth/bridge_provider.py`
- Test: `tests/auth/test_bridge_provider.py`

Adapt `/Users/kratsg/rucio-mcp/src/rucio_mcp/auth/bridge_provider.py`. This is the biggest structural change from rucio-mcp:

- **No `BridgePoller` protocol, no `_bg_poll`, no background `asyncio.create_task`.** There is no external IdP to poll — validation of the pasted refresh token happens synchronously inside a new method, `submit_token(session_id, token) -> None`, called by the `/bridge` POST handler (Task 12).
- `authorize()` creates the pending `BridgeSession` (no `polling_url`) and returns the `/bridge?session=...` interstitial URL directly — no poller call, no background task.
- New method `async def submit_token(self, session_id: str, token: str) -> None`: looks up the session; if missing/expired, raise `ValueError`. Otherwise validates `token` by constructing a throwaway `ServiceXAdapter(url=self._backend_url, refresh_token=token)` and calling `await adapter._get_authorization(force_reauth=True)` inside a `try/except` — a raised `AuthorizationError` (or any exception) means invalid token → `store.mark_error(session_id, str(exc))` and re-raise (or return a bool; pick one and match the test — recommend: catch, call `store.mark_error`, then `raise` so the route handler can render "invalid token" without duplicating error text). On success: mint `auth_code = secrets.token_urlsafe(32)`, call `store.mark_done(session_id, servicex_token=token, auth_code=auth_code)`.
  - **Why reach into `adapter._get_authorization`** (single-underscore, not name-mangled): `ServiceXAdapter` has no public "validate this token" method; `_get_authorization(force_reauth=True)` is the smallest call that actually exercises the `/token/refresh` exchange. Leave a comment explaining this — it's calling an internal method of a third-party library deliberately, which needs to be flagged in case a future `servicex` release renames it (pin `servicex>=3.3.0,<4` if this proves fragile — flag to Giordon in the PR description, don't silently add the pin yourself without asking, per the "ask before backward-compat workarounds" rule).
- `get_client()`/`_resolve_cimd()`/`_cache_get`/`_cache_put`/`register_client()` (raises `NotImplementedError`, DCR disabled) — copy verbatim from rucio-mcp, unchanged (this part is generic OAuth/CIMD logic, not rucio-specific).
- `load_authorization_code()` / `exchange_authorization_code()` — copy structurally, rename `session.rucio_token` → `session.servicex_token`, `_jwt_expires_in(session.servicex_token)` unchanged (still decodes the JWT's `exp` claim — ServiceX refresh tokens are JWTs too).
- `load_access_token()` — same passthrough pattern, rename `client_id="rucio-bridge"` → `client_id="servicex-bridge"`.
- `load_refresh_token()` / `exchange_refresh_token()` / `revoke_token()` — copy verbatim (not-supported stubs).
- Constructor: drop `poller: BridgePoller` and `poll_timeout` params; add `backend_url: str` (the ServiceX deployment URL to validate pasted tokens against). Keep `resource_url` (the servicex-mcp public URL, used for `/bridge?session=` construction) and `site_name` (drop if you don't add a metrics module in this build — no `BRIDGE_AUTH.labels(...)` calls, since there's no Prometheus module in v1; just omit those two `.inc()` lines that existed in rucio's version).

**Step 1: Write the failing test** — port `/Users/kratsg/rucio-mcp/tests/auth/test_bridge_provider.py`, adapting:
- Replace the mocked `BridgePoller` fixture with nothing (delete it) — instead, patch `servicex_mcp.auth.bridge_provider.ServiceXAdapter` (or whatever the module-level import name is) so `submit_token` can be tested without real network:
  ```python
  async def test_submit_token_success_marks_session_done(monkeypatch, provider):
      session = _put_pending_session(provider)
      fake_adapter = MagicMock()
      fake_adapter._get_authorization = AsyncMock(return_value={"Authorization": "Bearer x"})
      monkeypatch.setattr(
          "servicex_mcp.auth.bridge_provider.ServiceXAdapter",
          lambda *a, **k: fake_adapter,
      )
      await provider.submit_token(session.session_id, "pasted-refresh-token")
      updated = provider.store.get_by_session_id(session.session_id)
      assert updated.status == "done"
      assert updated.servicex_token == "pasted-refresh-token"

  async def test_submit_token_invalid_marks_session_error(monkeypatch, provider):
      session = _put_pending_session(provider)
      fake_adapter = MagicMock()
      fake_adapter._get_authorization = AsyncMock(side_effect=AuthorizationError("nope"))
      monkeypatch.setattr(
          "servicex_mcp.auth.bridge_provider.ServiceXAdapter",
          lambda *a, **k: fake_adapter,
      )
      with pytest.raises(AuthorizationError):
          await provider.submit_token(session.session_id, "bad-token")
      updated = provider.store.get_by_session_id(session.session_id)
      assert updated.status == "error"
  ```
- Keep the CIMD-resolution tests (`get_client` hit/miss/cache), `register_client` raising `NotImplementedError`, `load_authorization_code`/`exchange_authorization_code`/`load_access_token` tests — port these structurally unchanged (just field renames).

**Step 2: Run to verify it fails.**

**Step 3: Write the implementation** following the bullet list above — write the full module now (this is the most novel piece of the whole plan; take care with imports: `from servicex.servicex_adapter import ServiceXAdapter, AuthorizationError`).

**Step 4: Run test to verify it passes.**

**Step 5: Commit**

```bash
git add src/servicex_mcp/auth/bridge_provider.py tests/auth/test_bridge_provider.py
git commit -m "feat: add ServiceXBridgeProvider (CIMD + synchronous PAT-paste auth)"
```

---

## Task 12: `auth/bridge_routes.py` — paste-a-token interstitial

**Files:**
- Create: `src/servicex_mcp/auth/bridge_routes.py`
- Test: `tests/auth/test_bridge_routes.py`

Adapt `/Users/kratsg/rucio-mcp/src/rucio_mcp/auth/bridge_routes.py`. Structural change: **one route, two methods** instead of two routes (`/bridge` GET renders the form; `/bridge` POST validates and redirects) — drop `/bridge/status` and the JS polling loop entirely (nothing to poll: validation is synchronous).

```python
"""Starlette route handlers for the OAuth bridge interstitial page.

The "bridge" lets a user complete the MCP OAuth flow by pasting their own
ServiceX personal refresh token (obtained from the ServiceX deployment's web
UI) rather than an external IdP redirect. Validation happens synchronously
in the POST handler — there is no polling step.

GET  /bridge?session=<sid>   — render the paste-token form
POST /bridge?session=<sid>   — validate the pasted token; on success, 302
                                redirect to redirect_uri?code=...&state=...;
                                on failure, re-render the form with an error
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.server.mcpserver import MCPServer
    from starlette.requests import Request

    from servicex_mcp.auth.bridge_provider import ServiceXBridgeProvider


def make_bridge_handlers(
    provider: ServiceXBridgeProvider,
) -> tuple[Callable[..., object], Callable[..., object]]:
    """Return (bridge_get_handler, bridge_post_handler) closures over *provider*."""

    async def bridge_get(request: Request) -> Response:
        session_id = request.query_params.get("session")
        if not session_id:
            return JSONResponse({"error": "missing session parameter"}, status_code=400)
        session = provider.store.get_by_session_id(session_id)
        if session is None:
            return Response("Session not found or expired", status_code=404)
        return HTMLResponse(_build_form_html(session_id=session_id))

    async def bridge_post(request: Request) -> Response:
        session_id = request.query_params.get("session")
        if not session_id:
            return JSONResponse({"error": "missing session parameter"}, status_code=400)
        session = provider.store.get_by_session_id(session_id)
        if session is None:
            return Response("Session not found or expired", status_code=404)
        form = await request.form()
        token = str(form.get("token", "")).strip()
        if not token:
            return HTMLResponse(
                _build_form_html(session_id=session_id, error="Token is required"),
                status_code=400,
            )
        try:
            await provider.submit_token(session_id, token)
        except Exception as exc:  # noqa: BLE001
            return HTMLResponse(
                _build_form_html(session_id=session_id, error=f"Invalid token: {exc}"),
                status_code=400,
            )
        done_session = provider.store.get_by_session_id(session_id)
        # session was popped only on /token exchange, not here — still present
        assert done_session is not None  # noqa: S101 — invariant just established above
        params = {"code": done_session.auth_code}
        if done_session.state:
            params["state"] = done_session.state
        return RedirectResponse(f"{done_session.redirect_uri}?{urlencode(params)}")

    return bridge_get, bridge_post


def register_bridge_routes(mcp: MCPServer, provider: ServiceXBridgeProvider) -> None:
    """Register the /bridge GET+POST routes using the provider's session store."""
    bridge_get, bridge_post = make_bridge_handlers(provider)
    mcp.custom_route("/bridge", methods=["GET"])(bridge_get)
    mcp.custom_route("/bridge", methods=["POST"])(bridge_post)


def _build_form_html(*, session_id: str, error: str | None = None) -> str:
    error_html = f'<p style="color:#c00">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Connect ServiceX</title>
  <style>
    body {{ font-family: sans-serif; max-width: 600px; margin: 4rem auto; padding: 0 1rem; }}
    input[type=password] {{ width: 100%; padding: .5rem; font-family: monospace; }}
    button {{ margin-top: 1rem; padding: .6rem 1.2rem; background: #0070f3;
              color: #fff; border: none; border-radius: 4px; cursor: pointer; }}
  </style>
</head>
<body>
  <h1>Connect your ServiceX account</h1>
  <p>Paste your ServiceX personal refresh token below (from your ServiceX
  deployment's web UI).</p>
  {error_html}
  <form method="post" action="?session={session_id}">
    <input type="password" name="token" placeholder="ServiceX refresh token" required>
    <button type="submit">Connect</button>
  </form>
</body>
</html>"""
```

**Step 1: Write the failing test** — port `/Users/kratsg/rucio-mcp/tests/auth/test_bridge_routes.py` structurally: use Starlette's `TestClient` against a minimal app mounting these two routes over a real `ServiceXBridgeProvider` with `submit_token` patched (or a fully in-memory fake `ServiceXAdapter`, per Task 11's test pattern), asserting:
- GET with no `session` param → 400
- GET with unknown session → 404
- GET with valid pending session → 200, form HTML contains `session_id`
- POST with valid token → 302 redirect to `redirect_uri?code=...`
- POST with invalid token (patched `submit_token` raises) → 400, form re-rendered with error text

**Step 2–5:** standard TDD cycle + commit:

```bash
git add src/servicex_mcp/auth/bridge_routes.py tests/auth/test_bridge_routes.py
git commit -m "feat: add /bridge paste-token interstitial routes"
```

---

## Task 13: `auth/factory.py` — `BearerTokenClientFactory` + HTTP client builder

**Files:**
- Modify: `src/servicex_mcp/auth/factory.py`
- Test: `tests/auth/test_factory.py` (extend)

**The subtlety to handle:** `ServiceXClient.__init__` unconditionally calls `Configuration.read(config_path)`, which raises `NameError` if no `.servicex`/`servicex.yaml` file exists anywhere up the directory tree or in `$HOME` — see `/private/tmp/svx_check/extracted/servicex/configuration.py` lines 91-116 and `/private/tmp/svx_check/extracted/servicex/servicex_client.py` lines 343-391 (read both again if not already in context). HTTP mode must not require a config file to exist on the server just to build a per-request client from a URL + bearer token. So HTTP mode builds a `ServiceXClient` via `object.__new__` + manual attribute assignment instead of `ServiceXClient(url=..., ...)`, bypassing `Configuration.read()`.

**Step 1: Write the failing test**

```python
def test_build_http_servicex_client_does_not_require_config_file(tmp_path, monkeypatch):
    # No .servicex file anywhere near tmp_path or $HOME in this test env.
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    from servicex_mcp.auth.factory import build_http_servicex_client

    client = build_http_servicex_client(
        url="https://servicex.example.com", refresh_token="tok", cache_dir=str(tmp_path)
    )
    assert client.servicex.url == "https://servicex.example.com"
    assert client.servicex.refresh_token == "tok"


class TestBearerTokenClientFactory:
    def test_extracts_bearer_and_builds_client(self, monkeypatch) -> None:
        # patch build_http_servicex_client to avoid hitting the config-bypass path
        ...

    def test_caches_by_session_and_bearer_hash(self) -> None:
        ...

    def test_missing_bearer_raises_permission_error(self) -> None:
        ...
```

Write the full set following rucio-mcp's `tests/auth/test_factory.py` `BearerTokenClientFactory` tests structurally (same cache-hit/miss/session-id-absent/bearer-mismatch cases), swapping `TokenInjectedClient`/`rucio.client.Client` mocks for `build_http_servicex_client`/`ServiceXClient` mocks. Read `/Users/kratsg/rucio-mcp/tests/auth/test_factory.py` for the exact cases before writing this.

**Step 2: Run to verify it fails.**

**Step 3: Extend `factory.py`**

```python
# add to src/servicex_mcp/auth/factory.py

import hashlib
import time
from servicex import ServiceXClient
from servicex.query_cache import QueryCache
from servicex.servicex_adapter import ServiceXAdapter

if TYPE_CHECKING:
    from servicex_mcp.auth.session_cache import SessionCache


def build_http_servicex_client(
    *, url: str, refresh_token: str, cache_dir: str
) -> ServiceXClient:
    """Build a ServiceXClient from a URL + bearer token, no config file required.

    ServiceXClient.__init__ unconditionally calls Configuration.read(), which
    raises if no .servicex/servicex.yaml exists on disk. HTTP mode serves
    many callers with different tokens against one known backend URL and
    must not depend on a server-side config file, so this constructs the
    Configuration object directly instead of reading one from disk.
    """
    from servicex.configuration import Configuration

    client = object.__new__(ServiceXClient)
    config = Configuration(api_endpoints=[], cache_path=cache_dir)
    client.config = config
    client.endpoints = {}
    client.servicex = ServiceXAdapter(url, refresh_token=refresh_token)
    client.query_cache = QueryCache(config)
    client._code_generators = None
    return client


def _extract_request_auth(ctx: Any) -> tuple[str, str]:
    """Extract (session_id, bearer_token) from the request."""
    req = ctx.request_context.request
    session_id: str = req.headers.get("mcp-session-id", "")
    auth: str = req.headers.get("authorization", "") or ""
    if not auth.lower().startswith("bearer "):
        msg = "Missing Bearer token in Authorization header"
        raise PermissionError(msg)
    bearer = auth[7:].strip()
    return session_id, bearer


def _cache_key(session_id: str, bearer: str) -> str:
    bearer_hash = hashlib.sha256(bearer.encode()).hexdigest()[:16]
    return f"{session_id}:{bearer_hash}"


class BearerTokenClientFactory(ServiceXClientFactory):
    """HTTP-mode factory: builds and caches one ServiceXClient per MCP session.

    Backend-URL-bound: one factory per ServiceX deployment. The bearer token
    (the caller's ServiceX personal refresh token) is extracted per-request
    and used to build a client whose adapter exchanges it for a short-lived
    access token via ServiceX's own /token/refresh, lazily on first use.
    """

    def __init__(self, *, cache: SessionCache, backend_url: str, cache_dir: str) -> None:
        """Store the session cache, backend URL, and download cache directory."""
        self._cache = cache
        self._backend_url = backend_url
        self._cache_dir = cache_dir

    def get_client(self, ctx: Any) -> ServiceXClient:
        """Return a cached or newly built ServiceXClient for this session."""
        session_id, bearer = _extract_request_auth(ctx)
        cache_key = _cache_key(session_id, bearer) if session_id else None
        cached = self._cache.get(cache_key) if cache_key else None
        if cached is not None:
            return cached
        client = build_http_servicex_client(
            url=self._backend_url, refresh_token=bearer, cache_dir=self._cache_dir
        )
        if cache_key:
            self._cache.put(cache_key, client, time.time() + 300)
        return client

    def close(self) -> None:
        """Evict all cached clients."""
        self._cache.close()
```

**Step 4: Run test to verify it passes.**

**Step 5: Commit**

```bash
git add src/servicex_mcp/auth/factory.py tests/auth/test_factory.py
git commit -m "feat: add BearerTokenClientFactory and config-free HTTP client builder"
```

---

## Task 14: `server.py` (HTTP) + `cli.py` (HTTP `serve` args)

**Files:**
- Modify: `src/servicex_mcp/server.py`
- Modify: `src/servicex_mcp/cli.py`
- Test: `tests/test_http_transport.py`

**Step 1: Write the failing test** — follow `/Users/kratsg/rucio-mcp/tests/test_http_transport.py` structurally: use Starlette's `TestClient` against the app from `_make_http_app`/`_make_http_mcp`, asserting:
- `GET /.well-known/oauth-authorization-server` (or wherever the SDK exposes AS metadata) returns 200 with `client_id_metadata_document_supported: true` (if the SDK doesn't set this automatically, check how rucio-mcp's `AuthSettings` triggers it, or whether it's asserted via a custom well-known route — read that test file first)
- A tool call with no `Authorization` header → 401
- `GET /bridge?session=<valid>` → 200 (reuse Task 12's fixtures)

**Step 2: Run to verify it fails.**

**Step 3: Add to `server.py`**

```python
# add imports
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from pydantic import AnyHttpUrl

from servicex_mcp.auth.bridge_provider import ServiceXBridgeProvider
from servicex_mcp.auth.bridge_routes import register_bridge_routes
from servicex_mcp.auth.factory import BearerTokenClientFactory
from servicex_mcp.auth.session_cache import SessionCache

_HTTP_PREAMBLE = (
    "MCP server for ServiceX data delivery. "
    "Provides tools to discover code generators, submit transform (query) "
    "requests, and inspect/manage transforms and cached datasets. "
    "Authentication uses your personal ServiceX refresh token via the OAuth "
    "2.1 bridge — no local .servicex file is required."
)


def _make_http_mcp(
    *, backend_url: str, resource_url: str, read_only: bool, cache_dir: str
) -> tuple[MCPServer, ServiceXBridgeProvider]:
    """Build the FastMCP instance for HTTP transport."""
    provider = ServiceXBridgeProvider(backend_url=backend_url, resource_url=resource_url)
    cache = SessionCache()

    @asynccontextmanager
    async def _http_lifespan(_server: MCPServer) -> AsyncGenerator[dict[str, Any], None]:
        factory = BearerTokenClientFactory(
            cache=cache, backend_url=backend_url, cache_dir=cache_dir
        )
        try:
            yield {"client_factory": factory, "read_only": read_only}
        finally:
            factory.close()

    mcp = MCPServer(
        "servicex-mcp",
        instructions=_HTTP_PREAMBLE,
        lifespan=_http_lifespan,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(resource_url),
            resource_server_url=AnyHttpUrl(resource_url),
            # DCR disabled: clients are identified via CIMD only.
            client_registration_options=ClientRegistrationOptions(enabled=False),
            required_scopes=[],
        ),
    )

    register_bridge_routes(mcp, provider)
    for _module in [info, transforms, datasets, submit]:
        _module.register(mcp)

    return mcp, provider


def serve_http(
    *, backend_url: str, resource_url: str, host: str, port: int, read_only: bool, cache_dir: str
) -> None:
    """Entry point used by the CLI's `serve --transport http` path."""
    import uvicorn

    mcp, _provider = _make_http_mcp(
        backend_url=backend_url, resource_url=resource_url, read_only=read_only, cache_dir=cache_dir
    )
    uvicorn.run(mcp.streamable_http_app(), host=host, port=port)
```

Check the exact ASGI-app accessor name (`mcp.streamable_http_app()` vs another method) against how rucio-mcp's `_make_http_app` wires uvicorn — read `/Users/kratsg/rucio-mcp/src/rucio_mcp/server.py` lines 850-1054 (the `_make_http_app` function) if the above doesn't match the installed `mcp` SDK version's API.

**Step 4: Run test to verify it passes.**

**Step 5: Update `cli.py`** — replace the placeholder `else` branch from Task 7 with:

```python
    serve_parser.add_argument(
        "--backend-url",
        default=None,
        metavar="URL",
        help="Base URL of the ServiceX deployment (required for --transport http).",
    )
    serve_parser.add_argument(
        "--resource-url",
        default=None,
        metavar="URL",
        help="Public URL of this MCP server (required for --transport http).",
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument(
        "--cache-dir", default="/tmp/servicex_mcp_cache", metavar="PATH"
    )
```

and in `main()`:

```python
        if args.transport == "stdio":
            serve(backend=args.backend, config_path=args.config_path, read_only=args.read_only)
        else:
            if not args.backend_url or not args.resource_url:
                parser.error("--transport http requires --backend-url and --resource-url")
            from servicex_mcp.server import serve_http

            serve_http(
                backend_url=args.backend_url,
                resource_url=args.resource_url,
                host=args.host,
                port=args.port,
                read_only=args.read_only,
                cache_dir=args.cache_dir,
            )
```

**Step 6: Extend `tests/test_cli.py`** for the new args/dispatch path.

**Step 7: Run full suite:** `pixi run test` (or `pytest -m 'not slow'` if pixi isn't set up yet in the sandbox) — verify everything passes together, not just per-file.

**Step 8: Commit**

```bash
git add src/servicex_mcp/server.py src/servicex_mcp/cli.py tests/test_http_transport.py tests/test_cli.py
git commit -m "feat: add HTTP transport wiring (CIMD OAuth AS, bridge routes)"
```

---

## Task 15: Integration test stub

**Files:**
- Create: `tests/integration/__init__.py` (empty)
- Create: `tests/integration/test_live.py`

Write one `@pytest.mark.slow` test class, skipped by default (needs `--runslow` per `conftest.py`), documenting how to run it against a real ServiceX instance:

```python
"""Integration tests against a real ServiceX instance.

Requires a valid .servicex/servicex.yaml with a working backend and a
refresh token that hasn't expired. Run with:

    pytest tests/integration/ --runslow -v
"""

from __future__ import annotations

import pytest

from servicex_mcp.server import _make_stdio_mcp

pytestmark = pytest.mark.slow


class TestLiveServiceX:
    async def test_servicex_info_reaches_real_backend(self) -> None:
        mcp = _make_stdio_mcp()
        tools = {t.name: t.fn for t in mcp._tool_manager.list_tools()}
        # Enter the lifespan manually (see test_server.py's async lifespan test
        # for the exact AsyncExitStack idiom) to get a real ctx, then:
        # result = await tools["servicex_info"](ctx=ctx)
        # assert "app_version" in result
        pytest.skip("Wire up a real lifespan-entered ctx before enabling this test")
```

Commit:

```bash
git add tests/integration/__init__.py tests/integration/test_live.py
git commit -m "test: add integration test scaffold for a live ServiceX instance"
```

---

## Task 16: Packaging polish (charts, CI/CD, docs)

Do this last, once `pixi run check` (lint + test) is green on Task 14. These are mechanical adaptations of rucio-mcp's infra — no new design decisions.

**16a. Helm chart**

```bash
cp -r /Users/kratsg/rucio-mcp/charts/rucio-mcp /Users/kratsg/servicex-mcp/charts/servicex-mcp
cd /Users/kratsg/servicex-mcp/charts/servicex-mcp
grep -rl 'rucio-mcp\|rucio_mcp\|RUCIO_MCP\|Rucio' . | xargs sed -i '' \
  -e 's/rucio-mcp/servicex-mcp/g' \
  -e 's/rucio_mcp/servicex_mcp/g' \
  -e 's/RUCIO_MCP/SERVICEX_MCP/g' \
  -e 's/Rucio/ServiceX/g'
```
Then hand-review `values.yaml`, `templates/deployment.yaml`, `templates/configmap.yaml`, and `templates/secret.yaml` — rucio-mcp's chart has `auth.mode` (oidc/x509/shared-secret/broker) and site-list values that don't map 1:1 onto servicex-mcp's two modes (stdio doesn't apply to a chart at all; HTTP mode here only has the bridge mode, no shared-secret/broker yet). Simplify `values.yaml` to just `auth: { backendUrl: "", resourceUrl: "" }` and drop the `auth.mode`/`auth.sites`/`auth.broker.*` keys and any broker-specific template blocks (`templates/secret.yaml`'s broker JWKS bits, if present). Drop `dashboards/rucio-mcp.json` and `templates/grafana-dashboard.yaml` (no Prometheus metrics module in this build — re-add once one exists). Run `helm lint charts/servicex-mcp --set ingress.host=servicex-mcp.example.com` (needs the `helm` pixi feature from Task 0) and fix anything it flags.

**16b. GitHub Actions**

```bash
mkdir -p /Users/kratsg/servicex-mcp/.github/workflows
cp /Users/kratsg/rucio-mcp/.github/workflows/{ci,cd,docs}.yml /Users/kratsg/servicex-mcp/.github/workflows/
cp /Users/kratsg/rucio-mcp/.github/{dependabot.yml,release.yml} /Users/kratsg/servicex-mcp/.github/
grep -rl 'rucio-mcp\|rucio_mcp' /Users/kratsg/servicex-mcp/.github | xargs sed -i '' \
  -e 's/rucio-mcp/servicex-mcp/g' -e 's/rucio_mcp/servicex_mcp/g'
```
Hand-review `ci.yml` for any rucio-specific test matrix steps (e.g. installing VOMS/grid certs for integration tests) — remove those; servicex-mcp's integration tests need `.servicex` config secrets instead, which don't exist yet (leave the integration-test CI job commented out or `if: false` until Giordon sets up real ServiceX test credentials — ask him before wiring live-credential CI, per the "ask before adding CI secrets/pipeline changes" spirit of the version-control rules).

**16c. Docs**

```bash
cp /Users/kratsg/rucio-mcp/zensical.toml /Users/kratsg/servicex-mcp/zensical.toml
mkdir -p /Users/kratsg/servicex-mcp/docs
```
Adapt `zensical.toml`'s site name/nav. Write a minimal `docs/index.md` (or whatever the rucio-mcp nav's landing page is called) summarizing the tool list from this plan. Full docs parity with rucio-mcp (auth flow diagrams, per-tool reference pages) is follow-up work — flag as a TODO in the PR description rather than blocking on it here.

**16d. Commit**

```bash
git add charts/ .github/ zensical.toml docs/
git commit -m "chore: add Helm chart, CI/CD workflows, and docs scaffold"
```

---

## Task 17: Full verification pass

**Step 1:** `pixi install` (resolves and locks all deps — first time this generates `pixi.lock`)

**Step 2:** `pixi run check` (lint + test) — fix anything red.

**Step 3:** `pixi run build && pixi run build-check` — confirm the package actually builds.

**Step 4:** Review `git log --oneline` against this plan's task list — confirm nothing was skipped.

**Step 5:** Report to Giordon: what's done (stdio + HTTP both working, full tool surface, tests passing), what's explicitly deferred (per the design doc: `servicex-token-service`/broker mode, Prometheus metrics, full docs parity, live-credential CI), and ask whether to open a PR now or keep building on this branch.
