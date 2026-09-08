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
