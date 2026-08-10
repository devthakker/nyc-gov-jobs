"""Northwell Health adapter backed by its public careers search API."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.adapters.base import CollectionResult, JobSourceAdapter
from app.adapters.public_web import PublicPageClient, html_to_text, optional_text
from app.domain import CanonicalJob


API_URL = "https://jobsapi-google.m-cloud.io/api/job/search"
ORGANIZATION = "companies/12c4c7c9-29cb-4cff-a16c-4ae0d974c00a"
BRAND_FILTER = '(brand="Northwell Health" OR brand="Northwell" OR brand="Flexstaff")'
NY_TIMEZONE = ZoneInfo("America/New_York")


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def parse_iso_date(value: Any) -> date | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_salary(value: Any) -> tuple[Decimal | None, Decimal | None, str | None]:
    text = optional_text(value)
    if not text:
        return None, None, None
    amounts: list[Decimal] = []
    for raw in re.findall(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)", text):
        try:
            amounts.append(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            continue
    if not amounts:
        return None, None, None
    lowered = text.casefold()
    period = (
        "hour" if "hour" in lowered else
        "day" if "/day" in lowered or "daily" in lowered else
        "week" if "week" in lowered else
        "month" if "month" in lowered else
        "year" if "year" in lowered or "annual" in lowered else
        "other"
    )
    return amounts[0], amounts[1] if len(amounts) > 1 else amounts[0], period


def extract_qualification(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(
        r"(?:^|\n)Job Qualifications?\s*\n(.+?)(?=\n(?:\*?Additional Salary Detail|Salary Range|Benefits)\b|\Z)",
        text,
        flags=re.I | re.S,
    )
    return match.group(1).strip() if match else None


def search_url(*, offset: int, page_size: int) -> str:
    query = urlencode(
        {
            "companyName": ORGANIZATION,
            "pageSize": page_size,
            "offset": offset,
            "orderBy": "posting_publish_time desc",
            "customAttributeFilter": BRAND_FILTER,
        }
    )
    return f"{API_URL}?{query}"


class NorthwellHealthAdapter(JobSourceAdapter):
    source_key = "northwell"
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
        # The public search response already contains detail-level fields, so
        # workers/include_details are accepted for the shared CLI but require no
        # additional requests.
        self.workers = workers
        self.include_details = include_details
        self.client = client or PublicPageClient(timeout=timeout, retries=retries, delay=delay)

    def collect(self, *, limit: int | None = None) -> CollectionResult:
        page_size = min(100, limit) if limit is not None else 100
        last_error: RuntimeError | None = None
        for attempt in range(2):
            try:
                records, reported_count = self._collect_snapshot(page_size=page_size, limit=limit)
                break
            except RuntimeError as exc:
                last_error = exc
                if limit is not None or attempt == 1:
                    raise
        else:  # pragma: no cover - the loop either succeeds or raises
            raise last_error or RuntimeError("Northwell collection failed")

        return CollectionResult(
            records=records,
            metadata={
                "mode": "live",
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "site_reported_count": reported_count,
                "api_page_size": page_size,
                "details_included": True,
                "detail_requests_required": False,
                "collection_url": API_URL,
                "collection_backend": "Northwell public careers search API",
                "adapter_version": self.adapter_version,
            },
        )

    def _collect_snapshot(self, *, page_size: int, limit: int | None) -> tuple[list[dict[str, Any]], int]:
        records: list[dict[str, Any]] = []
        offset = 0
        reported_count: int | None = None
        while reported_count is None or offset < reported_count:
            remaining = None if limit is None else limit - len(records)
            if remaining is not None and remaining <= 0:
                break
            request_size = min(page_size, remaining) if remaining is not None else page_size
            payload = self.client.get_json(search_url(offset=offset, page_size=request_size))
            try:
                page_total = int(payload["totalHits"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("Northwell response omitted a valid totalHits") from exc
            if reported_count is None:
                reported_count = page_total
            elif page_total != reported_count:
                raise RuntimeError(
                    f"Northwell result count changed during collection ({reported_count} to {page_total})"
                )
            results = payload.get("searchResults")
            if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
                raise RuntimeError("Northwell response omitted a valid searchResults list")
            if not results:
                if offset < reported_count:
                    raise RuntimeError(
                        f"Northwell pagination ended at {offset} of {reported_count} records"
                    )
                break
            for result in results:
                job = result.get("job")
                if not isinstance(job, dict):
                    raise RuntimeError("Northwell search result omitted its job object")
                summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
                records.append({**job, "_search_summary": summary, "_details_included": True})
            offset += len(results)

        assert reported_count is not None
        if limit is None:
            unique = {str(record.get("id")): record for record in records}
            if None in {record.get("id") for record in records} or len(unique) != reported_count:
                raise RuntimeError(
                    f"Northwell pagination yielded {len(unique)} unique jobs; API reported {reported_count}"
                )
            records = list(unique.values())
        return records[:limit] if limit is not None else records, reported_count

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
            raw_records = payload.get("jobs", payload.get("records", payload.get("searchResults", [])))
            metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
            records = []
            for item in raw_records if isinstance(raw_records, list) else []:
                if isinstance(item, dict) and isinstance(item.get("job"), dict):
                    records.append({**item["job"], "_search_summary": item.get("summary", {})})
                else:
                    records.append(item)
        else:
            raise RuntimeError(f"Unsupported export shape in {path}")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise RuntimeError(f"Export does not contain a valid jobs/records/searchResults list: {path}")
        prepared = [{**record, "_details_included": True} for record in records]
        return CollectionResult(
            records=prepared,
            metadata={**metadata, "mode": "import", "import_path": str(path), "adapter_version": self.adapter_version},
        )

    def normalize(self, record: dict[str, Any], observed_at: datetime) -> CanonicalJob:
        external_id = optional_text(record.get("id"))
        title = optional_text(record.get("title"))
        canonical_url = optional_text(record.get("url"))
        if not external_id or not title or not canonical_url:
            raise ValueError("Northwell record requires an ID, title, and public URL")

        description = html_to_text(record.get("description"))
        qualifications = extract_qualification(description)
        requirements = [{"type": "Job Qualification", "text": qualifications}] if qualifications else []
        summary_data = record.get("_search_summary") if isinstance(record.get("_search_summary"), dict) else {}
        summary = optional_text(summary_data.get("job_summary"))
        salary_raw = optional_text(record.get("salary"))
        salary_min, salary_max, salary_period = parse_salary(salary_raw)
        posted = parse_iso_date(record.get("open_date"))
        posted_at = datetime.combine(posted, datetime_time.min, NY_TIMEZONE) if posted else None
        close_date = parse_iso_date(record.get("close_date"))
        # Northwell commonly publishes a ten-year placeholder close date.
        closes_on = close_date if close_date and posted and (close_date - posted).days <= 730 else None

        location_type = optional_text(record.get("location_type"))
        level = optional_text(record.get("level"))
        mode_text = " ".join(part for part in (location_type, level, title) if part).casefold()
        work_mode = "remote" if "remote" in mode_text else "hybrid" if "hybrid" in mode_text else "on_site"
        shift = optional_text(record.get("shift"))
        schedule_raw = optional_text(record.get("schedule"))
        schedule = " · ".join(part for part in (shift, schedule_raw) if part) or None
        city = optional_text(record.get("primary_city"))
        state = (optional_text(record.get("primary_state")) or "NY").upper()
        postal_code = optional_text(record.get("primary_zip"))
        address = optional_text(record.get("primary_address"))
        location_text = ", ".join(part for part in (address, city, state, postal_code) if part)

        return CanonicalJob(
            source_key=self.source_key,
            employer_name="Northwell Health",
            external_id=external_id,
            title=title,
            normalized_title=normalize_title(title),
            summary=summary,
            description_text=description,
            requirements_text=qualifications,
            requirements=requirements,
            canonical_url=canonical_url,
            apply_url=optional_text(record.get("seo_url")) or canonical_url,
            source_category=optional_text(record.get("primary_category")),
            source_department=optional_text(record.get("business_unit")),
            source_agency="Northwell Health",
            location_text=location_text or None,
            city=city,
            state=state,
            postal_code=postal_code,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if salary_min is not None else None,
            salary_period=salary_period,
            salary_raw=salary_raw,
            employment_type=optional_text(record.get("employment_type")),
            schedule=schedule,
            work_mode=work_mode,
            posted_at=posted_at,
            closes_on=closes_on,
            status="active",
            observed_at=observed_at,
            raw_payload=record,
            source_metadata={
                "details_included": True,
                "detail_requests_required": False,
                "northwell_job_id": external_id,
                "employer_job_id": optional_text(record.get("ref")),
                "ats_portal": optional_text(record.get("ats_portalid")),
                "brand": optional_text(record.get("brand")),
                "parent_category": optional_text(record.get("parent_category")),
                "sub_category": optional_text(record.get("sub_category")),
                "internal_category": optional_text(record.get("is_internal")),
                "education_field": optional_text(record.get("education")),
                "department": optional_text(record.get("department")),
                "location_type": location_type,
                "close_date_raw": optional_text(record.get("close_date")),
                "collection_backend": "Northwell public careers search API",
            },
        )
