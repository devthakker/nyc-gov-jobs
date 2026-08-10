"""StateJobsNY adapter for the public Department of Civil Service vacancy site."""

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
from app.adapters.public_web import PublicPageClient, attribute, class_names, optional_text
from app.domain import CanonicalJob


PUBLIC_ROOT = "https://statejobs.ny.gov/public/"
VACANCY_TABLE_URL = f"{PUBLIC_ROOT}vacancyTable.cfm?searchResults=Yes"
NY_TIMEZONE = ZoneInfo("America/New_York")


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def parse_us_date(value: Any) -> date | None:
    text = optional_text(value)
    if not text:
        return None
    for pattern in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
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
    endpoints = amounts[:2]
    return min(endpoints), max(endpoints), period


class StateJobsListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict[str, Any]] = []
        self.table_found = False
        self.table_complete = False
        self._table_depth: int | None = None
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and attribute(attrs, "id") == "vacancyTable":
            self.table_found = True
            self._table_depth = 1
            return
        if self._table_depth is None:
            return
        if tag == "table":
            self._table_depth += 1
        elif tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = {"parts": []}
        elif tag == "a" and self._cell is not None:
            href = attribute(attrs, "href")
            if href and "vacancyDetailsView.cfm" in href:
                self._cell["url"] = urljoin(PUBLIC_ROOT, href)

    def handle_endtag(self, tag: str) -> None:
        if self._table_depth is None:
            return
        if tag == "td" and self._row is not None and self._cell is not None:
            self._cell["text"] = optional_text("".join(self._cell["parts"]))
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if len(self._row) >= 7:
                values = [cell.get("text") for cell in self._row]
                external_id = optional_text(values[0])
                url = self._row[1].get("url")
                if external_id and url and values[1]:
                    self.records.append(
                        {
                            "id": external_id,
                            "url": url,
                            "title": values[1],
                            "grade": values[2],
                            "posted": values[3],
                            "deadline": values[4],
                            "agency": values[5],
                            "county": values[6],
                        }
                    )
            self._row = None
            self._cell = None
        elif tag == "table":
            self._table_depth -= 1
            if self._table_depth == 0:
                self.table_complete = True
                self._table_depth = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["parts"].append(data)


class StateJobsDetailParser(HTMLParser):
    section_ids = {"information", "schedule", "location", "jobspecifics", "contact"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, str] = {}
        self._section = "overview"
        self._section_depth: int | None = None
        self._row = False
        self._side: str | None = None
        self._left_parts: list[str] = []
        self._right_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = attribute(attrs, "id")
        if tag == "div" and element_id in self.section_ids:
            self._section = str(element_id)
            self._section_depth = 1
            return
        if tag == "div" and self._section_depth is not None:
            self._section_depth += 1
        if tag == "p" and "row" in class_names(attrs):
            self._row = True
            self._side = None
            self._left_parts = []
            self._right_parts = []
        elif tag == "span" and self._row:
            classes = class_names(attrs)
            if "leftCol" in classes:
                self._side = "left"
            elif "rightCol" in classes:
                self._side = "right"
        elif tag == "br" and self._row and self._side == "right":
            self._right_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._row:
            self._side = None
        elif tag == "p" and self._row:
            label = optional_text("".join(self._left_parts))
            value = self._clean_multiline("".join(self._right_parts))
            if label and value:
                key = f"{self._section}.{label.casefold()}"
                self.fields.setdefault(key, value)
            self._row = False
            self._side = None
        if tag == "div" and self._section_depth is not None:
            self._section_depth -= 1
            if self._section_depth == 0:
                self._section = "overview"
                self._section_depth = None

    def handle_data(self, data: str) -> None:
        if self._row and self._side == "left":
            self._left_parts.append(data)
        elif self._row and self._side == "right":
            self._right_parts.append(data)

    @staticmethod
    def _clean_multiline(value: str) -> str | None:
        lines = [" ".join(line.split()) for line in value.splitlines()]
        cleaned: list[str] = []
        for line in lines:
            if line:
                cleaned.append(line)
            elif cleaned and cleaned[-1] != "":
                cleaned.append("")
        return "\n".join(cleaned).strip() or None


def parse_listing_html(source: str) -> list[dict[str, Any]]:
    parser = StateJobsListingParser()
    parser.feed(source)
    if not parser.table_found or not parser.table_complete:
        raise RuntimeError("StateJobsNY response omitted a complete vacancy table")
    return parser.records


def parse_detail_html(source: str) -> dict[str, str]:
    parser = StateJobsDetailParser()
    parser.feed(source)
    if not parser.fields.get("overview.vacancy id"):
        raise RuntimeError("StateJobsNY detail page omitted its Vacancy ID")
    return parser.fields


def field(fields: dict[str, str], section: str, label: str) -> str | None:
    return optional_text(fields.get(f"{section}.{label.casefold()}"))


class StateJobsNYAdapter(JobSourceAdapter):
    source_key = "statejobsny"
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
        records = parse_listing_html(self.client.get_text(VACANCY_TABLE_URL))
        if not records:
            raise RuntimeError("StateJobsNY vacancy table returned no recognizable listings")
        deduped = list({str(record["id"]): record for record in records}.values())
        if len(deduped) != len(records):
            raise RuntimeError("StateJobsNY vacancy table returned duplicate Vacancy IDs")
        reported_count = len(records)
        if limit is not None:
            records = records[:limit]

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
                "collection_url": VACANCY_TABLE_URL,
                "collection_backend": "StateJobsNY public vacancy table",
                "adapter_version": self.adapter_version,
            },
        )

    def _load_detail(self, listing: dict[str, Any]) -> dict[str, Any]:
        try:
            detail = parse_detail_html(self.client.get_text(str(listing["url"])))
            if detail.get("overview.vacancy id") != str(listing["id"]):
                raise RuntimeError("Detail Vacancy ID did not match its listing")
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
        external_id = optional_text(detail.get("overview.vacancy id")) or optional_text(record.get("id"))
        title = field(detail, "information", "Title") or optional_text(record.get("title"))
        canonical_url = optional_text(record.get("url"))
        if not external_id or not title or not canonical_url:
            raise ValueError("StateJobsNY record requires a Vacancy ID, title, and canonical URL")

        agency = field(detail, "information", "Agency") or optional_text(record.get("agency"))
        category = field(detail, "information", "Occupational Category")
        description = field(detail, "jobspecifics", "Duties Description")
        qualifications = field(detail, "jobspecifics", "Minimum Qualifications")
        additional = field(detail, "jobspecifics", "Additional Comments")
        requirements_sections = [
            ("Minimum Qualifications", qualifications),
            ("Additional Comments", additional),
        ]
        requirements = [{"type": heading, "text": text} for heading, text in requirements_sections if text]
        requirements_text = "\n\n".join(f"{heading}\n{text}" for heading, text in requirements_sections if text) or None

        salary_raw = field(detail, "information", "Salary Range")
        salary_min, salary_max, salary_period = parse_salary(salary_raw)
        posted = parse_us_date(field(detail, "overview", "Date Posted") or record.get("posted"))
        closes_on = parse_us_date(field(detail, "overview", "Applications Due") or record.get("deadline"))
        posted_at = datetime.combine(posted, datetime_time.min, NY_TIMEZONE) if posted else None
        observed_date = observed_at.astimezone(NY_TIMEZONE).date()
        status = "expired" if closes_on and closes_on < observed_date else "active"

        city = field(detail, "location", "City")
        state = field(detail, "location", "State") or "NY"
        city_state_match = re.fullmatch(r"(.+?),\s*([A-Za-z]{2})", city or "")
        if city_state_match:
            city = optional_text(city_state_match.group(1))
            state = city_state_match.group(2)
        county = field(detail, "location", "County") or optional_text(record.get("county"))
        street = field(detail, "location", "Street Address")
        postal_code = field(detail, "location", "Zip Code")
        location_parts = [part for part in (street, city, state, postal_code) if part]
        location_text = ", ".join(location_parts) if location_parts else county
        schedule_parts = [
            field(detail, "schedule", "Workweek"),
            field(detail, "schedule", "Hours Per Week"),
            field(detail, "schedule", "From"),
            field(detail, "schedule", "To"),
        ]
        schedule = " · ".join(part for part in schedule_parts if part) or None
        telecommuting = field(detail, "schedule", "Telecommuting allowed?")
        work_mode = "hybrid" if telecommuting and telecommuting.casefold() == "yes" else "on_site"
        details_included = bool(record.get("_details_included"))

        return CanonicalJob(
            source_key=self.source_key,
            employer_name=agency or "New York State",
            external_id=external_id,
            title=title,
            normalized_title=normalize_title(title),
            description_text=description,
            requirements_text=requirements_text,
            requirements=requirements,
            canonical_url=canonical_url,
            apply_url=canonical_url,
            source_category=category,
            source_department=None,
            source_agency=agency,
            location_text=location_text,
            city=city,
            region=county,
            state=state.upper(),
            postal_code=postal_code,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if salary_min is not None else None,
            salary_period=salary_period,
            salary_raw=salary_raw,
            employment_type=field(detail, "information", "Employment Type"),
            schedule=schedule,
            work_mode=work_mode,
            posted_at=posted_at,
            closes_on=closes_on,
            status=status,
            observed_at=observed_at,
            raw_payload=record,
            source_metadata={
                "details_included": details_included,
                "listing_only_preserve_fields": ["employer_name", "source_agency", "work_mode", "status"],
                "vacancy_id": external_id,
                "salary_grade": field(detail, "information", "Salary Grade") or optional_text(record.get("grade")),
                "ny_helps": field(detail, "information", "NY HELP"),
                "appointment_type": field(detail, "information", "Appointment Type"),
                "jurisdictional_class": field(detail, "information", "Jurisdictional Class"),
                "bargaining_unit": field(detail, "information", "Bargaining Unit"),
                "travel_percentage": field(detail, "information", "Travel Percentage"),
                "telecommuting_allowed": telecommuting,
                "notes_on_applying": field(detail, "contact", "Notes on Applying"),
                "collection_backend": "StateJobsNY public vacancy table",
            },
        )
