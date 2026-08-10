"""NYSDOL apprenticeship source adapter."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.adapters.base import CollectionResult, JobSourceAdapter
from app.adapters.nysdol_scraper import DEFAULT_URL, HTTPClient, scrape
from app.domain import CanonicalJob


NY_TIMEZONE = ZoneInfo("America/New_York")


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def parse_posted_at(value: Any) -> datetime | None:
    parsed = parse_date(value)
    return datetime.combine(parsed, time.min, NY_TIMEZONE) if parsed else None


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


class NYSDOLApprenticeshipAdapter(JobSourceAdapter):
    source_key = "nysdol_apprenticeships"
    adapter_version = "2.0.0"

    def __init__(
        self,
        *,
        delay: float = 0.25,
        timeout: float = 30,
        retries: int = 3,
        workers: int = 4,
        include_details: bool = True,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.workers = workers
        self.include_details = include_details

    def collect(self, *, limit: int | None = None) -> CollectionResult:
        client = HTTPClient(self.timeout, self.retries, self.delay)
        records, metadata = scrape(
            client=client,
            base_url=DEFAULT_URL,
            include_details=self.include_details,
            limit=limit,
            workers=self.workers,
        )
        metadata = {**metadata, "mode": "live", "adapter_version": self.adapter_version}
        for record in records:
            record["_details_included"] = self.include_details
        return CollectionResult(records=records, metadata=metadata)

    def load_export(self, path: Path) -> CollectionResult:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RuntimeError(f"Export not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON export {path}: {exc}") from exc

        if isinstance(payload, list):
            records, metadata = payload, {}
        elif isinstance(payload, dict):
            records = payload.get("jobs", [])
            metadata = payload.get("metadata", {})
        else:
            raise RuntimeError(f"Unsupported export shape in {path}")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise RuntimeError(f"Export does not contain a valid jobs list: {path}")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata = {
            **metadata,
            "mode": "import",
            "import_path": str(path),
            "adapter_version": self.adapter_version,
        }
        details_included = bool(metadata.get("details_included"))
        records = [{**record, "_details_included": details_included} for record in records]
        return CollectionResult(records=records, metadata=metadata)

    def normalize(self, record: dict[str, Any], observed_at: datetime) -> CanonicalJob:
        title = optional_text(record.get("title"))
        canonical_url = optional_text(record.get("url"))
        if not title or not canonical_url:
            raise ValueError("NYSDOL record requires title and URL")

        external_id = optional_text(record.get("id"))
        if not external_id:
            digest = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:24]
            external_id = f"url-{digest}"

        employer_name = re.sub(r"^CLOSED:\s*", "", title, flags=re.IGNORECASE).strip()
        regions = [
            optional_text(region)
            for region in record.get("regions", [])
            if optional_text(region)
        ]
        region = ", ".join(regions) or None
        location = optional_text(record.get("location")) or region
        requirements = [
            text
            for item in record.get("requirements", [])
            if (text := optional_text(item))
        ]
        opens_on = parse_date(record.get("opening_date"))
        closes_on = parse_date(record.get("closing_date"))
        status = "active"
        if title.upper().startswith("CLOSED:") or (closes_on and closes_on < date.today()):
            status = "expired"

        source_metadata = {
            "regions": regions,
            "posted_date_raw": optional_text(record.get("posted_date_raw")),
            "posted_time_raw": optional_text(record.get("posted_time")),
            "opening_date_raw": optional_text(record.get("opening_date_raw")),
            "closing_date_raw": optional_text(record.get("closing_date_raw")),
            "detail_title": optional_text(record.get("detail_title")),
            "details_included": bool(record.get("_details_included")),
        }

        return CanonicalJob(
            source_key=self.source_key,
            employer_name=employer_name,
            external_id=external_id,
            title=title,
            normalized_title=normalize_title(title),
            summary=optional_text(record.get("subtitle"))
            or optional_text(record.get("listing_summary")),
            description_text=optional_text(record.get("description")),
            requirements_text=(
                "\n".join(f"- {requirement}" for requirement in requirements)
                if requirements
                else None
            ),
            requirements=requirements,
            canonical_url=canonical_url,
            source_category="Apprenticeship",
            source_agency="New York State Department of Labor",
            location_text=location,
            region=region,
            state="NY",
            employment_type="Apprenticeship",
            posted_at=parse_posted_at(record.get("posted_date")),
            opens_on=opens_on,
            closes_on=closes_on,
            status=status,
            observed_at=observed_at,
            raw_payload=record,
            source_metadata=source_metadata,
        )
