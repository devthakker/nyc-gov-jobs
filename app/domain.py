"""Canonical job domain model and deterministic content hashing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


MATERIAL_FIELDS = (
    "employer_name",
    "title",
    "normalized_title",
    "summary",
    "description_text",
    "requirements_text",
    "requirements",
    "canonical_url",
    "apply_url",
    "source_category",
    "source_department",
    "source_agency",
    "location_text",
    "city",
    "borough",
    "region",
    "state",
    "postal_code",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "salary_raw",
    "employment_type",
    "schedule",
    "work_mode",
    "experience_level",
    "experience_years_min",
    "education_level",
    "licenses",
    "posted_at",
    "opens_on",
    "closes_on",
    "status",
)


def json_ready(value: Any) -> Any:
    if isinstance(value, str):
        # PostgreSQL text/JSONB cannot represent the NUL byte. A few public ATS
        # feeds include it in copied rich text, so remove only that invalid
        # control byte while preserving the source's remaining text verbatim.
        return value.replace("\x00", "")
    if isinstance(value, datetime):
        # PostgreSQL may return the same timestamptz in the database session's
        # timezone. Hash the instant in UTC so equivalent offsets stay equal.
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        # PostgreSQL numeric columns return their declared scale (for example,
        # 131330.00) even when a source supplied 131330. Canonicalize equivalent
        # decimal values so database round-trips cannot create false versions.
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


@dataclass(frozen=True)
class CanonicalJob:
    source_key: str
    employer_name: str
    external_id: str
    title: str
    canonical_url: str
    observed_at: datetime
    normalized_title: str | None = None
    summary: str | None = None
    description_text: str | None = None
    requirements_text: str | None = None
    requirements: list[Any] = field(default_factory=list)
    apply_url: str | None = None
    source_category: str | None = None
    source_department: str | None = None
    source_agency: str | None = None
    location_text: str | None = None
    city: str | None = None
    borough: str | None = None
    region: str | None = None
    state: str | None = None
    postal_code: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_raw: str | None = None
    employment_type: str | None = None
    schedule: str | None = None
    work_mode: str | None = None
    experience_level: str | None = None
    experience_years_min: Decimal | None = None
    education_level: str | None = None
    licenses: list[Any] = field(default_factory=list)
    posted_at: datetime | None = None
    opens_on: date | None = None
    closes_on: date | None = None
    status: str = "active"
    raw_payload: dict[str, Any] = field(default_factory=dict)
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def material_snapshot(self) -> dict[str, Any]:
        return {name: json_ready(getattr(self, name)) for name in MATERIAL_FIELDS}

    def version_snapshot(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "external_id": self.external_id,
            **self.material_snapshot(),
        }

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(
            self.material_snapshot(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
