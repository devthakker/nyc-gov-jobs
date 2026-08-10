"""Port Authority jobs adapter using its official public Jobvite board."""

from __future__ import annotations

import json
import re
from datetime import datetime, time as datetime_time
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.adapters.base import CollectionResult, JobSourceAdapter
from app.adapters.mta import (
    PublicPageClient,
    html_to_text,
    normalize_title,
    optional_text,
    parse_detail_html,
    parse_listing_html,
    parse_us_date,
    token_from_url,
)
from app.domain import CanonicalJob


BOARD_URL = "https://jobs.jobvite.com/panynj/jobs"
EMPLOYER_NAME = "The Port Authority of New York & New Jersey"
NY_TIMEZONE = ZoneInfo("America/New_York")


class JSONLDParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.documents: list[str] = []
        self._parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        script_type = next((value for name, value in attrs if name == "type"), None)
        if script_type == "application/ld+json":
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._parts is not None:
            self.documents.append("".join(self._parts))
            self._parts = None


def extract_job_posting(source: str) -> dict[str, Any]:
    parser = JSONLDParser()
    parser.feed(source)
    for document in parser.documents:
        try:
            payload = json.loads(document)
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate
    return {}


SECTION_HEADINGS = {
    "ABOUT THE ROLE",
    "RESPONSIBILITIES",
    "DUTIES AND RESPONSIBILITIES",
    "MINIMUM QUALIFICATIONS",
    "REQUIRED QUALIFICATIONS",
    "DESIRED QUALIFICATIONS",
    "REQUIREMENTS",
    "SELECTION PROCESS",
    "COMPENSATION, BENEFITS & ON-SITE COLLABORATION REQUIREMENTS",
    "COMPENSATION AND BENEFITS",
    "HOW TO APPLY",
    "ABOUT THE PORT AUTHORITY",
    "EQUAL OPPORTUNITY EMPLOYER",
}


def extract_sections(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = " ".join(line.rstrip(":").upper().split())
        if normalized in SECTION_HEADINGS:
            current = normalized
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return {
        heading: "\n".join(content).strip()
        for heading, content in sections.items()
        if content
    }


def parse_location(value: str | None) -> tuple[str | None, str | None]:
    text = optional_text(value)
    if not text:
        return None, None
    parts = [part.strip() for part in text.split(",") if part.strip()]
    city = parts[0] if parts else None
    state_name = parts[1].upper() if len(parts) > 1 else ""
    states = {
        "NY": "NY",
        "NEW YORK": "NY",
        "NJ": "NJ",
        "NEW JERSEY": "NJ",
    }
    return city, states.get(state_name)


def _amount(value: str) -> Decimal | None:
    cleaned = re.sub(r"[\s,]", "", value)
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_compensation(text: str | None) -> tuple[Decimal | None, Decimal | None, str | None]:
    if not text:
        return None, None, None
    minimum = re.search(
        r"Minimum:\s*\$\s*([0-9][0-9,\s]*?)(?=\s+(?:Midpoint|Maximum):)",
        text,
        flags=re.I,
    )
    maximum = re.search(
        r"Maximum:\s*\$\s*([0-9][0-9,\s]*)(?=$|\D[A-Za-z])",
        text,
        flags=re.I,
    )
    salary_min = _amount(minimum.group(1)) if minimum else None
    salary_max = _amount(maximum.group(1)) if maximum else None
    return salary_min, salary_max, "year" if salary_min or salary_max else None


def salary_excerpt(text: str | None) -> str | None:
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if "expected compensation range" in line.casefold():
            if "minimum:" in line.casefold() and "maximum:" in line.casefold():
                return optional_text(line)
            return optional_text(" ".join(lines[index : index + 2]))
    return None


class PortAuthorityJobsAdapter(JobSourceAdapter):
    source_key = "port_authority"
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
        from concurrent.futures import ThreadPoolExecutor

        listing_html = self.client.get_text(BOARD_URL)
        all_records = parse_listing_html(listing_html)
        if not all_records:
            raise RuntimeError("Port Authority Jobvite board returned no recognizable listings")

        seen: set[str] = set()
        records: list[dict[str, Any]] = []
        for record in all_records:
            token = token_from_url(record.get("url"))
            if not token or token in seen:
                continue
            seen.add(token)
            records.append({**record, "id": token})
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
                "scraped_at": datetime.now().astimezone().isoformat(),
                "site_reported_count": reported_count,
                "details_included": self.include_details,
                "collection_url": BOARD_URL,
                "collection_backend": "Port Authority public Jobvite board",
                "coverage_scope": "Openings published on the official Jobvite board",
                "adapter_version": self.adapter_version,
            },
        )

    def _load_detail(self, listing: dict[str, Any]) -> dict[str, Any]:
        try:
            source = self.client.get_text(str(listing["url"]))
            detail = parse_detail_html(source)
            detail["job_posting"] = extract_job_posting(source)
            if not detail.get("title"):
                raise RuntimeError("Detail page omitted its job title")
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
            if isinstance(payload.get("metadata"), dict):
                metadata = payload["metadata"]
        else:
            raise RuntimeError(f"Unsupported export shape in {path}")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise RuntimeError(f"Export does not contain a valid jobs/records list: {path}")
        records = [
            {**record, "_details_included": isinstance(record.get("detail"), dict)}
            for record in records
        ]
        return CollectionResult(
            records=records,
            metadata={
                **metadata,
                "mode": "import",
                "import_path": str(path),
                "adapter_version": self.adapter_version,
            },
        )

    def normalize(self, record: dict[str, Any], observed_at: datetime) -> CanonicalJob:
        detail = record.get("detail") if isinstance(record.get("detail"), dict) else {}
        posting = detail.get("job_posting") if isinstance(detail.get("job_posting"), dict) else {}
        title = optional_text(detail.get("title")) or optional_text(posting.get("title")) or optional_text(record.get("title"))
        canonical_url = optional_text(record.get("url"))
        external_id = optional_text(record.get("id")) or token_from_url(canonical_url)
        if not title or not canonical_url or not external_id:
            raise ValueError("Port Authority record requires a title, URL, and Jobvite token")

        description_html = detail.get("description_html") or posting.get("description")
        description = html_to_text(description_html)
        sections = extract_sections(description)
        requirements = [
            {"type": heading, "text": content}
            for heading, content in sections.items()
            if "QUALIFICATION" in heading
            or heading == "REQUIREMENTS"
            or heading.startswith("REQUIRED ")
        ]
        requirements_text = "\n\n".join(
            f"{item['type']}\n{item['text']}" for item in requirements
        ) or None
        summary = sections.get("ABOUT THE ROLE")

        location_text = optional_text(record.get("location"))
        city, state = parse_location(location_text)
        salary_raw = salary_excerpt(description)
        salary_min, salary_max, salary_period = parse_compensation(salary_raw)
        posted_on = parse_us_date(posting.get("datePosted"))
        posted_at = (
            datetime.combine(posted_on, datetime_time.min, NY_TIMEZONE)
            if posted_on
            else None
        )
        details_included = bool(record.get("_details_included"))
        public_job_id = optional_text(detail.get("mta_job_id"))
        apply_url = optional_text(detail.get("apply_url")) or f"{canonical_url}/apply"
        work_mode = "hybrid" if description and re.search(
            r"work remotely.{0,80}(?:day|week)", description, flags=re.I | re.S
        ) else None

        return CanonicalJob(
            source_key=self.source_key,
            employer_name=EMPLOYER_NAME,
            external_id=external_id,
            title=title,
            normalized_title=normalize_title(title),
            summary=summary,
            description_text=description,
            requirements_text=requirements_text,
            requirements=requirements,
            canonical_url=canonical_url,
            apply_url=apply_url,
            source_category=optional_text(record.get("category")) or optional_text(posting.get("industry")),
            source_department=None,
            source_agency=EMPLOYER_NAME,
            location_text=location_text,
            city=city,
            state=state,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if salary_min or salary_max else None,
            salary_period=salary_period,
            salary_raw=salary_raw,
            employment_type=optional_text(posting.get("employmentType")),
            work_mode=work_mode,
            posted_at=posted_at,
            status="active",
            observed_at=observed_at,
            raw_payload=record,
            source_metadata={
                "details_included": details_included,
                "port_authority_job_id": public_job_id,
                "jobvite_token": external_id,
                "jobvite_category": optional_text(record.get("category")),
                "collection_backend": "Port Authority public Jobvite board",
                "department_availability": "Not published by the Jobvite board",
            },
        )
