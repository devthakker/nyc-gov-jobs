"""Runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str

    @classmethod
    def from_environment(cls) -> "Settings":
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is required. Run the command through the Docker worker "
                "or export a PostgreSQL connection URL."
            )
        return cls(database_url=database_url)
