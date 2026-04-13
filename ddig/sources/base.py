"""Abstract base class for all domain data sources."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from ..models.domain import Domain


class DomainSource(ABC):
    """All sources must implement fetch() and is_available()."""

    #: Human-readable source identifier stored on each Domain record
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