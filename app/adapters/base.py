"""Shared source-adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.domain import CanonicalJob


@dataclass(frozen=True)
class CollectionResult:
    records: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


class JobSourceAdapter(ABC):
    source_key: str
    adapter_version: str

    @abstractmethod
    def collect(self, *, limit: int | None = None) -> CollectionResult:
        """Collect live source records without writing to the database."""

    @abstractmethod
    def load_export(self, path: Path) -> CollectionResult:
        """Load a previously collected export for a one-time import."""

    @abstractmethod
    def normalize(self, record: dict[str, Any], observed_at: datetime) -> CanonicalJob:
        """Convert one source record to the canonical contract."""
