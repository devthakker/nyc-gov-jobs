"""Internal newsletter records kept separate from the public API contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class Subscriber:
    id: UUID | None
    email: str
    name: str | None
    all_tracks: bool
    track_slugs: tuple[str, ...] = ()


@dataclass(frozen=True)
class DigestJob:
    id: UUID
    title: str
    canonical_url: str
    apply_url: str | None
    employer_name: str
    source_name: str
    location_text: str | None
    city: str | None
    state: str | None
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    salary_period: str | None
    salary_raw: str | None
    summary: str | None
    posted_at: datetime | None
    closes_on: date | None
    track_slug: str | None
    track_name: str | None

