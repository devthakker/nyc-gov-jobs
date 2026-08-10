"""NewYork-Presbyterian adapter for its public TalentBrew careers site."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from app.adapters.base import CollectionResult, JobSourceAdapter
from app.adapters.public_web import (
    PublicPageClient,
    attribute,
    class_names,
    html_to_text,
    optional_text,
)
from app.domain import CanonicalJob


PUBLIC_ROOT = "https://careers.nyp.org"
SEARCH_URL = f"{PUBLIC_ROOT}/search-jobs?orgIds=19715"
NY_TIMEZONE = ZoneInfo("America/New_York")


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def parse_date(value: Any) -> date | None:
    text = optional_text(value)
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%b. %d, %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse_salary(value: str | None) -> tuple[Decimal | None, Decimal | None, str | None]:
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
        "day" if "day" in lowered else
        "week" if "week" in lowered else
        "month" if "month" in lowered else
        "year"
    )
    return amounts[0], amounts[1] if len(amounts) > 1 else amounts[0], period


def parse_location(value: str | None) -> tuple[str | None, str | None]:
    text = optional_text(value)
    if not text:
        return None, None
    parts = [part.strip() for part in text.split(",") if part.strip()]
    city = parts[0] if parts else None
    state = None
    if len(parts) > 1:
        state_part = parts[-1].upper()
        state = "NY" if state_part in {"NY", "NEW YORK"} else state_part if len(state_part) == 2 else None
    return city, state


class NYPListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict[str, Any]] = []
        self.total_results: int | None = None
        self.total_pages: int | None = None
        self.current_page: int | None = None
        self.records_per_page: int | None = None
        self._record: dict[str, Any] | None = None
        self._field: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "section" and attribute(attrs, "id") == "search-results":
            for attr_name, field_name in (
                ("data-total-job-results", "total_results"),
                ("data-total-pages", "total_pages"),
                ("data-current-page", "current_page"),
                ("data-records-per-page", "records_per_page"),
            ):
                raw = attribute(attrs, attr_name)
                try:
                    setattr(self, field_name, int(raw))
                except (TypeError, ValueError):
                    pass
        if tag == "a" and attribute(attrs, "data-job-id"):
            self._record = {
                "id": attribute(attrs, "data-job-id"),
                "url": urljoin(PUBLIC_ROOT, attribute(attrs, "href") or ""),
            }
        elif self._record is not None and tag == "h2":
            self._field = "title"
            self._parts = []
        elif self._record is not None and tag == "span" and "job-location" in class_names(attrs):
            self._field = "location"
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._record is not None and self._field and tag in {"h2", "span"}:
            self._record[self._field] = optional_text("".join(self._parts))
            self._field = None
            self._parts = []
        elif self._record is not None and tag == "a":
            if self._record.get("id") and self._record.get("url") and self._record.get("title"):
                self.records.append(self._record)
            self._record = None
            self._field = None

    def handle_data(self, data: str) -> None:
        if self._field:
            self._parts.append(data)


class NYPDetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.job_posting: dict[str, Any] = {}
        self.fields: dict[str, str] = {}
        self.apply_url: str | None = None
        self._script = False
        self._script_parts: list[str] = []
        self._field: str | None = None
        self._field_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and (attribute(attrs, "type") or "").casefold() == "application/ld+json":
            self._script = True
            self._script_parts = []
            return
        classes = class_names(attrs)
        for class_name, field_name in (
            ("job-id", "job_id"),
            ("job-location", "location"),
            ("job-facility", "facility"),
            ("job-date", "date_posted"),
            ("job-category", "category"),
        ):
            if tag == "span" and class_name in classes:
                self._field = field_name
                self._field_parts = []
                break
        if tag == "a" and "job-apply" in classes and self.apply_url is None:
            self.apply_url = attribute(attrs, "data-apply-url") or attribute(attrs, "href")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script:
            self._script = False
            try:
                payload = json.loads("".join(self._script_parts))
            except json.JSONDecodeError:
                return
            candidates = payload if isinstance(payload, list) else [payload]
            for item in candidates:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    self.job_posting = item
                    break
        elif tag == "span" and self._field:
            value = optional_text("".join(self._field_parts))
            labels = {
                "job_id": "Job ID", "location": "Location", "facility": "Location",
                "date_posted": "Date posted", "category": "Category",
            }
            if value:
                value = re.sub(rf"^{re.escape(labels[self._field])}\s*", "", value, flags=re.I)
                self.fields[self._field] = value.strip()
            self._field = None
            self._field_parts = []

    def handle_data(self, data: str) -> None:
        if self._script:
            self._script_parts.append(data)
        elif self._field:
            self._field_parts.append(data)


def parse_listing_html(source: str) -> tuple[list[dict[str, Any]], dict[str, int | None]]:
    parser = NYPListingParser()
    parser.feed(source)
    return parser.records, {
        "total_results": parser.total_results,
        "total_pages": parser.total_pages,
        "current_page": parser.current_page,
        "records_per_page": parser.records_per_page,
    }


def parse_detail_html(source: str) -> dict[str, Any]:
    parser = NYPDetailParser()
    parser.feed(source)
    if not parser.job_posting:
        raise RuntimeError("NYP detail page omitted JobPosting structured data")
    return {"job_posting": parser.job_posting, "fields": parser.fields, "apply_url": parser.apply_url}


def required_criteria(description: str | None) -> str | None:
    if not description:
        return None
    match = re.search(
        r"(?:^|\n)(?:Required Criteria|Minimum Qualifications|Required Qualifications)\s*\n(.+?)(?=\n(?:Preferred Criteria|Preferred Qualifications|Join a healthcare system|NewYork-Presbyterian Hospital|Salary Range)\b|\Z)",
        description,
        flags=re.I | re.S,
    )
    return match.group(1).strip() if match else None


class NewYorkPresbyterianAdapter(JobSourceAdapter):
    source_key = "newyork_presbyterian"
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
        first_html = self.client.get_text(SEARCH_URL)
        first_records, page = parse_listing_html(first_html)
        total = page["total_results"]
        total_pages = page["total_pages"]
        page_size = page["records_per_page"]
        if not first_records or total is None or total_pages is None or page_size is None:
            raise RuntimeError("NYP search page omitted valid listings or pagination metadata")

        records = list(first_records)
        pages_needed = total_pages if limit is None else min(total_pages, (limit + page_size - 1) // page_size)
        for page_number in range(2, pages_needed + 1):
            page_html = self.client.get_text(f"{SEARCH_URL}&p={page_number}")
            page_records, metadata = parse_listing_html(page_html)
            if metadata["current_page"] != page_number or metadata["total_results"] != total:
                raise RuntimeError(f"NYP pagination metadata changed while loading page {page_number}")
            if not page_records:
                raise RuntimeError(f"NYP pagination returned no listings on page {page_number}")
            records.extend(page_records)

        deduped = list({str(record["id"]): record for record in records}.values())
        if limit is None and len(deduped) != total:
            raise RuntimeError(f"NYP pagination yielded {len(deduped)} unique jobs; site reported {total}")
        records = deduped[:limit] if limit is not None else deduped

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
                "site_reported_count": total,
                "site_reported_pages": total_pages,
                "records_per_page": page_size,
                "details_included": self.include_details,
                "collection_url": SEARCH_URL,
                "collection_backend": "NYP public TalentBrew careers site",
                "adapter_version": self.adapter_version,
            },
        )

    def _load_detail(self, listing: dict[str, Any]) -> dict[str, Any]:
        try:
            detail = parse_detail_html(self.client.get_text(str(listing["url"])))
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
        posting = detail.get("job_posting") if isinstance(detail.get("job_posting"), dict) else {}
        fields = detail.get("fields") if isinstance(detail.get("fields"), dict) else {}
        title = optional_text(posting.get("title")) or optional_text(record.get("title"))
        external_id = optional_text(record.get("id"))
        canonical_url = optional_text(posting.get("url")) or optional_text(record.get("url"))
        if not title or not external_id or not canonical_url:
            raise ValueError("NYP record requires a title, public job ID, and canonical URL")

        description_html = posting.get("description")
        description = html_to_text(description_html)
        requirements_text = required_criteria(description)
        requirements = [{"type": "Required Criteria", "text": requirements_text}] if requirements_text else []
        salary_raw_match = re.search(
            r"\$\s*[0-9][0-9,.]*(?:\s*[-–]\s*\$?\s*[0-9][0-9,.]*)?\s*/?\s*(?:Hourly|Annually|Yearly|Daily|Weekly|Monthly)",
            str(description_html or ""),
            flags=re.I,
        )
        salary_raw = optional_text(salary_raw_match.group(0)) if salary_raw_match else None
        salary_min, salary_max, salary_period = parse_salary(salary_raw)

        location_text = optional_text(fields.get("location")) or optional_text(record.get("location"))
        city, state = parse_location(location_text)
        locations = posting.get("jobLocation") if isinstance(posting.get("jobLocation"), list) else []
        address = {}
        if locations and isinstance(locations[0], dict) and isinstance(locations[0].get("address"), dict):
            address = locations[0]["address"]
        posted_date = parse_date(fields.get("date_posted")) or parse_date(posting.get("datePosted"))
        posted_at = datetime.combine(posted_date, datetime_time.min, NY_TIMEZONE) if posted_date else None
        organization = posting.get("hiringOrganization") if isinstance(posting.get("hiringOrganization"), dict) else {}
        details_included = bool(record.get("_details_included"))

        return CanonicalJob(
            source_key=self.source_key,
            employer_name=optional_text(organization.get("name")) or "NewYork-Presbyterian",
            external_id=external_id,
            title=title,
            normalized_title=normalize_title(title),
            description_text=description,
            requirements_text=requirements_text,
            requirements=requirements,
            canonical_url=canonical_url,
            apply_url=optional_text(detail.get("apply_url")) or canonical_url,
            source_category=optional_text(fields.get("category")),
            source_department=optional_text(fields.get("facility")) or optional_text(posting.get("industry")),
            source_agency="NewYork-Presbyterian",
            location_text=location_text,
            city=city,
            state=state or "NY",
            postal_code=optional_text(address.get("postalCode")),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if salary_min is not None else None,
            salary_period=salary_period,
            salary_raw=salary_raw,
            employment_type=optional_text(posting.get("employmentType")),
            work_mode="on_site",
            posted_at=posted_at,
            status="active",
            observed_at=observed_at,
            raw_payload=record,
            source_metadata={
                "details_included": details_included,
                "listing_only_preserve_fields": ["employer_name", "source_agency", "work_mode", "status"],
                "talentbrew_job_id": external_id,
                "employer_job_id": optional_text(fields.get("job_id")) or optional_text(posting.get("identifier")),
                "facility": optional_text(fields.get("facility")),
                "collection_backend": "NYP public TalentBrew careers site",
            },
        )
