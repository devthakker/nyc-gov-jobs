"""CUNY adapter using its official sitemap and public per-job JSON."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from app.adapters.base import CollectionResult, JobSourceAdapter
from app.adapters.public_web import PublicPageClient, html_to_text, optional_text
from app.domain import CanonicalJob


PUBLIC_ROOT = "https://cuny.jobs"
SITEMAP_URL = f"{PUBLIC_ROOT}/sitemaps/jobs_1.xml"
DATA_ROOT = "https://microsites.dejobs.org/cuny-jobs/data"
NY_TIMEZONE = ZoneInfo("America/New_York")


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def parse_sitemap(source: str) -> list[dict[str, Any]]:
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        raise RuntimeError("CUNY returned an invalid jobs sitemap") from exc
    records: list[dict[str, Any]] = []
    for node in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
        location = optional_text(node.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}loc"))
        modified = optional_text(node.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod"))
        if not location:
            continue
        parsed = urlparse(location)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc != "cuny.jobs" or len(parts) < 4 or parts[-1] != "job":
            raise RuntimeError(f"CUNY sitemap contained an unexpected job URL: {location}")
        guid = parts[-2].upper()
        if not re.fullmatch(r"[0-9A-F]{32}", guid):
            raise RuntimeError(f"CUNY sitemap contained an invalid job GUID: {location}")
        location_slug, title_slug = parts[-4], parts[-3]
        records.append(
            {
                "id": guid,
                "url": location,
                "title": title_slug.replace("-", " ").title(),
                "location": location_slug.replace("-", " ").title(),
                "last_modified": modified,
            }
        )
    if not records:
        raise RuntimeError("CUNY jobs sitemap contained no job URLs")
    unique = {record["id"]: record for record in records}
    if len(unique) != len(records):
        raise RuntimeError("CUNY jobs sitemap contained duplicate GUIDs")
    return list(unique.values())


def parse_iso_datetime(value: Any) -> datetime | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(NY_TIMEZONE) if parsed.tzinfo else parsed.replace(tzinfo=NY_TIMEZONE)


def section(text: str | None, heading: str, stops: tuple[str, ...]) -> str | None:
    if not text:
        return None
    stop_pattern = "|".join(re.escape(item) for item in stops)
    match = re.search(
        rf"(?:^|\n){re.escape(heading)}\s*\n(.+?)(?=\n(?:{stop_pattern})\s*\n|\Z)",
        text,
        flags=re.I | re.S,
    )
    return match.group(1).strip() if match else None


def parse_closing_date(text: str | None) -> date | None:
    if not text:
        return None
    match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(\d{4})\b",
        text,
        flags=re.I,
    )
    if not match:
        return None
    try:
        return datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%B %d %Y").date()
    except ValueError:
        return None


def parse_salary(text: str | None) -> tuple[Decimal | None, Decimal | None, str | None]:
    if not text:
        return None, None, None
    values: list[Decimal] = []
    for raw in re.findall(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)", text):
        try:
            values.append(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            continue
    if not values:
        return None, None, None
    minimum = min(values[:2])
    maximum = max(values[:2])
    lowered = text.casefold()
    period = "hour" if "hour" in lowered or maximum < Decimal("500") else "year"
    return minimum, maximum, period


class CUNYJobsAdapter(JobSourceAdapter):
    source_key = "cuny"
    adapter_version = "1.0.0"

    def __init__(
        self,
        *,
        delay: float = 0.25,
        timeout: float = 30,
        retries: int = 3,
        workers: int = 4,
        include_details: bool = True,
        client: PublicPageClient | None = None,
    ) -> None:
        self.workers = workers
        self.include_details = include_details
        self.client = client or PublicPageClient(timeout=timeout, retries=retries, delay=delay)

    def collect(self, *, limit: int | None = None) -> CollectionResult:
        all_records = parse_sitemap(self.client.get_text(SITEMAP_URL))
        reported_count = len(all_records)
        records = all_records[:limit] if limit is not None else all_records
        if self.include_details and records:
            with ThreadPoolExecutor(max_workers=min(self.workers, len(records))) as pool:
                records = list(pool.map(self._load_detail, records))
        else:
            records = [{**record, "_details_included": False} for record in records]
        return CollectionResult(
            records=records,
            metadata={
                "mode": "live",
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "site_reported_count": reported_count,
                "details_included": self.include_details,
                "collection_url": SITEMAP_URL,
                "collection_backend": "CUNY official job sitemap and public job JSON",
                "adapter_version": self.adapter_version,
            },
        )

    def _load_detail(self, listing: dict[str, Any]) -> dict[str, Any]:
        try:
            detail = self.client.get_json(f"{DATA_ROOT}/{listing['id']}.json")
            if optional_text(detail.get("guid")) != listing["id"]:
                raise RuntimeError("CUNY detail GUID did not match its sitemap URL")
            return {**listing, "detail": detail, "_details_included": True}
        except Exception as exc:
            return {**listing, "_details_included": False, "detail_error": str(exc)}

    def load_export(self, path: Path) -> CollectionResult:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RuntimeError(f"Export not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON export {path}: {exc}") from exc
        metadata: dict[str, Any] = {}
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = payload.get("jobs", payload.get("records", []))
            metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
        else:
            raise RuntimeError(f"Unsupported export shape in {path}")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise RuntimeError(f"Export does not contain a valid jobs/records list: {path}")
        prepared = [{**record, "_details_included": isinstance(record.get("detail"), dict)} for record in records]
        return CollectionResult(records=prepared, metadata={**metadata, "mode": "import", "import_path": str(path), "adapter_version": self.adapter_version})

    def normalize(self, record: dict[str, Any], observed_at: datetime) -> CanonicalJob:
        detail = record.get("detail") if isinstance(record.get("detail"), dict) else {}
        external_id = optional_text(record.get("id"))
        title = optional_text(detail.get("title_exact")) or optional_text(record.get("title"))
        canonical_url = optional_text(record.get("url"))
        if not external_id or not title or not canonical_url:
            raise ValueError("CUNY record requires a GUID, title, and canonical URL")

        description = html_to_text(detail.get("html_description"))
        headings = (
            "QUALIFICATIONS", "CUNY TITLE OVERVIEW", "CUNY TITLE", "FLSA",
            "COMPENSATION AND BENEFITS", "HOW TO APPLY", "CLOSING DATE",
            "JOB SEARCH CATEGORY", "EQUAL EMPLOYMENT OPPORTUNITY",
        )
        summary = section(description, "POSITION DETAILS", headings)
        qualifications = section(description, "QUALIFICATIONS", headings[1:])
        compensation = section(description, "COMPENSATION AND BENEFITS", headings[5:])
        closing_text = section(description, "CLOSING DATE", headings[7:])
        category_match = re.search(r"CUNY Job Posting:\s*([^\n]+)", description or "", flags=re.I)
        source_category = optional_text(category_match.group(1)) if category_match else None
        salary_min, salary_max, salary_period = parse_salary(compensation)
        posted_at = parse_iso_datetime(detail.get("date_new")) or parse_iso_datetime(detail.get("date_added"))
        state = optional_text(detail.get("state_short")) or "NY"

        return CanonicalJob(
            source_key=self.source_key,
            employer_name="City University of New York",
            external_id=external_id,
            title=title,
            normalized_title=normalize_title(title),
            summary=summary,
            description_text=description,
            requirements_text=qualifications,
            requirements=[{"type": "Qualifications", "text": qualifications}] if qualifications else [],
            canonical_url=canonical_url,
            apply_url=optional_text(detail.get("link")) or canonical_url,
            source_category=source_category,
            source_department=optional_text(detail.get("location_name")),
            source_agency="City University of New York",
            location_text=optional_text(detail.get("location_exact")) or optional_text(record.get("location")),
            city=optional_text(detail.get("city")),
            state=state.upper(),
            postal_code=optional_text(detail.get("zipcode")),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if salary_min is not None else None,
            salary_period=salary_period,
            salary_raw=compensation,
            employment_type=optional_text(detail.get("job_type")),
            work_mode="remote" if "remote" in title.casefold() else "on_site",
            posted_at=posted_at,
            closes_on=parse_closing_date(closing_text),
            status="active",
            observed_at=observed_at,
            raw_payload=record,
            source_metadata={
                "details_included": bool(record.get("_details_included")),
                "listing_only_preserve_fields": ["employer_name", "source_agency", "work_mode", "status"],
                "cuny_guid": external_id,
                "employer_job_id": optional_text(detail.get("reqid")),
                "campus": optional_text(detail.get("location_name")),
                "last_modified": optional_text(record.get("last_modified")),
                "collection_backend": "CUNY official job sitemap and public job JSON",
            },
        )
