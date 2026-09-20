"""Abstract base classes for all domain data sources."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from ..models.domain import Domain


class DomainSource(ABC):
    """All fetch sources must implement fetch() and is_available()."""

    name: str = "base"

    @abstractmethod
    def fetch(self) -> Iterator[Domain]:
        """Yield :class:`Domain` objects from this source."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the source is reachable and configured."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


class FQDNSource(ABC):
    """
    Base class for sources that yield plain FQDNs (strings), not Domain objects.

    Used by filter/purge sources such as NRD feeds that identify
    newly-registered domains for removal from the DDig database.
    """

    name: str = "fqdn_base"

    @abstractmethod
    def fetch(self) -> Iterator[str]:
        """Yield fully-qualified domain name strings."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the source is reachable."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"