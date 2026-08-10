"""NYC City Jobs adapter backed by the public SmartRecruiters Posting API."""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.adapters.base import CollectionResult, JobSourceAdapter
from app.domain import CanonicalJob


API_ROOT = "https://api.smartrecruiters.com/v1/companies/CityOfNewYork/postings"
PUBLIC_POSTING_ROOT = "https://jobs.smartrecruiters.com/CityOfNewYork"
NY_TIMEZONE = ZoneInfo("America/New_York")
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def parse_date(value: Any) -> date | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_datetime(value: Any) -> datetime | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_money(value: Any) -> Decimal | None:
    text = optional_text(value)
    if not text:
        return None
    numeric = re.sub(r"[^0-9.\-]", "", text)
    if not numeric:
        return None
    try:
        return Decimal(numeric)
    except InvalidOperation:
        return None


def salary_period(value: Any) -> str | None:
    normalized = (optional_text(value) or "").casefold()
    return {
        "annual": "year",
        "yearly": "year",
        "hourly": "hour",
        "daily": "day",
        "weekly": "week",
        "monthly": "month",
    }.get(normalized, "other" if normalized else None)


def custom_fields(record: dict[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for item in record.get("customField") or []:
        if not isinstance(item, dict):
            continue
        label = optional_text(item.get("fieldLabel"))
        value = optional_text(item.get("valueLabel"))
        if label and value and label not in fields:
            fields[label] = value
    return fields


class _ReadableHTMLParser(HTMLParser):
    block_tags = {
        "address",
        "article",
        "blockquote",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.parts.append("\n")
        elif tag in self.block_tags:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(value: Any) -> str | None:
    source = str(value or "")
    if not source:
        return None
    parser = _ReadableHTMLParser()
    parser.feed(source)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if line:
            cleaned.append(line)
        elif cleaned and cleaned[-1] != "":
            cleaned.append("")
    return "\n".join(cleaned).strip() or None


def public_posting_url(record: dict[str, Any]) -> str | None:
    direct = optional_text(record.get("postingUrl"))
    if direct:
        return direct
    posting_id = optional_text(record.get("id"))
    if not posting_id:
        return None
    title = optional_text(record.get("name")) or "job"
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.casefold()).strip("-") or "job"
    return f"{PUBLIC_POSTING_ROOT}/{posting_id}-{slug}"


class SmartRecruitersClient:
    """Small rate-limited JSON client with bounded retries."""

    def __init__(self, *, timeout: float, retries: int, delay: float) -> None:
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self._rate_lock = threading.Lock()
        self._next_request_at = 0.0

    def _wait_for_slot(self) -> None:
        with self._rate_lock:
            now = time.monotonic()
            request_at = max(now, self._next_request_at)
            self._next_request_at = request_at + self.delay
        wait = request_at - now
        if wait > 0:
            time.sleep(wait)

    def get_json(self, url: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_for_slot()
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "jobtracks-pilot/0.1 (public job data ingestion)",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise RuntimeError(f"Expected a JSON object from {url}")
                return payload
            except HTTPError as exc:
                last_error = exc
                if exc.code not in RETRYABLE_STATUS_CODES or attempt >= self.retries:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"Request failed for {url}: {last_error}") from last_error


class NYCCityJobsAdapter(JobSourceAdapter):
    source_key = "nyc_jobs"
    adapter_version = "1.0.0"

    def __init__(
        self,
        *,
        delay: float = 0.25,
        timeout: float = 30,
        retries: int = 3,
        workers: int = 4,
        include_details: bool = True,
        client: SmartRecruitersClient | None = None,
    ) -> None:
        self.workers = workers
        self.include_details = include_details
        self.client = client or SmartRecruitersClient(
            timeout=timeout,
            retries=retries,
            delay=delay,
        )

    def collect(self, *, limit: int | None = None) -> CollectionResult:
        records: list[dict[str, Any]] = []
        offset = 0
        total_found: int | None = None

        while total_found is None or offset < total_found:
            remaining = None if limit is None else limit - len(records)
            if remaining is not None and remaining <= 0:
                break
            page_size = min(100, remaining) if remaining is not None else 100
            query = urlencode({"limit": page_size, "offset": offset, "destination": "PUBLIC"})
            payload = self.client.get_json(f"{API_ROOT}?{query}")
            if total_found is None:
                try:
                    total_found = int(payload["totalFound"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise RuntimeError("NYC Jobs response omitted a valid totalFound") from exc
            content = payload.get("content")
            if not isinstance(content, list) or not all(isinstance(item, dict) for item in content):
                raise RuntimeError("NYC Jobs response omitted a valid content list")
            if not content:
                if offset < total_found:
                    raise RuntimeError(
                        f"NYC Jobs pagination ended at {offset} of {total_found} records"
                    )
                break
            records.extend(content)
            offset += len(content)

        if limit is not None:
            records = records[:limit]

        if self.include_details and records:
            with ThreadPoolExecutor(max_workers=min(self.workers, len(records))) as pool:
                records = list(pool.map(self._load_detail, records))
        else:
            records = [{**record, "_details_included": False} for record in records]

        observed_at = datetime.now(timezone.utc)
        return CollectionResult(
            records=records,
            metadata={
                "mode": "live",
                "scraped_at": observed_at.isoformat(),
                "site_reported_count": total_found,
                "details_included": self.include_details,
                "api_endpoint": API_ROOT,
                "api_page_size": 100,
                "adapter_version": self.adapter_version,
            },
        )

    def _load_detail(self, listing: dict[str, Any]) -> dict[str, Any]:
        posting_id = optional_text(listing.get("id"))
        if not posting_id:
            return {
                **listing,
                "_details_included": False,
                "detail_error": "Listing omitted its posting ID",
            }
        try:
            detail = self.client.get_json(f"{API_ROOT}/{posting_id}")
        except Exception as exc:
            return {
                **listing,
                "_details_included": False,
                "detail_error": str(exc),
            }
        return {**listing, **detail, "_details_included": True}

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
            records = payload.get("jobs", payload.get("content", []))
            candidate_metadata = payload.get("metadata", {})
            if isinstance(candidate_metadata, dict):
                metadata = candidate_metadata
            if "totalFound" in payload:
                metadata["site_reported_count"] = payload["totalFound"]
        else:
            raise RuntimeError(f"Unsupported export shape in {path}")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise RuntimeError(f"Export does not contain a valid jobs/content list: {path}")

        prepared = [
            {**record, "_details_included": isinstance(record.get("jobAd"), dict)}
            for record in records
        ]
        return CollectionResult(
            records=prepared,
            metadata={
                **metadata,
                "mode": "import",
                "import_path": str(path),
                "adapter_version": self.adapter_version,
            },
        )

    def normalize(self, record: dict[str, Any], observed_at: datetime) -> CanonicalJob:
        fields = custom_fields(record)
        title = optional_text(record.get("name")) or fields.get("Business Title")
        external_id = optional_text(record.get("refNumber"))
        canonical_url = public_posting_url(record)
        if not title or not external_id or not canonical_url:
            raise ValueError("NYC Jobs record requires a title, Job ID, and posting ID/URL")

        company = record.get("company") if isinstance(record.get("company"), dict) else {}
        agency = fields.get("Agency")
        employer_name = agency or optional_text(company.get("name")) or "City of New York"
        location = record.get("location") if isinstance(record.get("location"), dict) else {}
        job_ad = record.get("jobAd") if isinstance(record.get("jobAd"), dict) else {}
        sections = job_ad.get("sections") if isinstance(job_ad.get("sections"), dict) else {}
        description_section = (
            sections.get("jobDescription")
            if isinstance(sections.get("jobDescription"), dict)
            else {}
        )
        qualifications_section = (
            sections.get("qualifications")
            if isinstance(sections.get("qualifications"), dict)
            else {}
        )
        description = html_to_text(description_section.get("text"))
        qualifications = html_to_text(qualifications_section.get("text"))
        preferred_skills = optional_text(fields.get("Preferred Skills"))
        requirement_sections = [
            ("Minimum Qualifications", qualifications),
            ("Preferred Skills", preferred_skills),
        ]
        requirements = [
            {"type": heading, "text": text}
            for heading, text in requirement_sections
            if text
        ]
        requirements_text = "\n\n".join(
            f"{heading}\n{text}" for heading, text in requirement_sections if text
        ) or None

        compensation = (
            job_ad.get("compensation")
            if isinstance(job_ad.get("compensation"), dict)
            else {}
        )
        salary_min_raw = fields.get("Salary Min")
        salary_max_raw = fields.get("Salary Max")
        salary_min = parse_money(compensation.get("min")) or parse_money(salary_min_raw)
        salary_max = parse_money(compensation.get("max")) or parse_money(salary_max_raw)
        salary_raw = None
        if salary_min_raw and salary_max_raw:
            salary_raw = f"{salary_min_raw} – {salary_max_raw}"
        elif salary_min_raw or salary_max_raw:
            salary_raw = salary_min_raw or salary_max_raw

        posted_date = parse_date(fields.get("Posted On Date"))
        posted_at = (
            datetime.combine(posted_date, datetime_time.min, NY_TIMEZONE)
            if posted_date
            else parse_datetime(record.get("releasedDate"))
        )
        closes_on = parse_date(fields.get("Expire Date"))
        active = record.get("active")
        status = "removed" if active is False else "active"
        observed_date = observed_at.astimezone(NY_TIMEZONE).date()
        if closes_on and closes_on < observed_date:
            status = "expired"

        remote = location.get("remote") is True
        hybrid = location.get("hybrid") is True
        work_mode = "remote" if remote else "hybrid" if hybrid else "on_site"
        employment = fields.get("Job Type")
        if not employment:
            type_of_employment = record.get("typeOfEmployment")
            if isinstance(type_of_employment, dict):
                employment = optional_text(type_of_employment.get("label"))
        experience = fields.get("Experience")
        if not experience:
            experience_level = record.get("experienceLevel")
            if isinstance(experience_level, dict):
                experience = optional_text(experience_level.get("label"))

        category = fields.get("Job Category")
        function = record.get("function") if isinstance(record.get("function"), dict) else {}
        department = (
            record.get("department") if isinstance(record.get("department"), dict) else {}
        )
        source_department = fields.get("Division / Work Unit") or optional_text(
            department.get("label") or department.get("name")
        )
        apply_url = optional_text(record.get("applyUrl")) or f"{canonical_url}?oga=true"
        details_included = bool(record.get("_details_included"))

        source_metadata = {
            "details_included": details_included,
            "posting_id": optional_text(record.get("id")),
            "posting_uuid": optional_text(record.get("uuid")),
            "job_id": optional_text(record.get("jobId")),
            "job_ad_id": optional_text(record.get("jobAdId")),
            "title_code": fields.get("Title Code"),
            "civil_service_title": fields.get("Civil Service Title Description"),
            "title_classification": fields.get("Title Classification"),
            "job_level": fields.get("Job Level"),
            "number_of_positions": fields.get("Number of Position")
            or fields.get("Target Openings"),
            "applicant_type": fields.get("Applicant Type"),
            "salary_type_raw": fields.get("Salary Type"),
            "released_date_raw": optional_text(record.get("releasedDate")),
            "posted_on_date_raw": fields.get("Posted On Date"),
            "expire_date_raw": fields.get("Expire Date"),
            "source_function": optional_text(function.get("label")),
            "custom_fields": fields,
        }

        return CanonicalJob(
            source_key=self.source_key,
            employer_name=employer_name,
            external_id=external_id,
            title=title,
            normalized_title=normalize_title(title),
            summary=None,
            description_text=description,
            requirements_text=requirements_text,
            requirements=requirements,
            canonical_url=canonical_url,
            apply_url=apply_url,
            source_category=category or optional_text(function.get("label")),
            source_department=source_department,
            source_agency=agency,
            location_text=fields.get("Work Location")
            or optional_text(location.get("fullLocation")),
            city=optional_text(location.get("city")),
            borough=fields.get("Borough"),
            region=fields.get("Borough"),
            state=(optional_text(location.get("region")) or "NY").upper(),
            postal_code=optional_text(location.get("postalCode")),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=optional_text(compensation.get("currency")) or "USD",
            salary_period=salary_period(fields.get("Salary Type")),
            salary_raw=salary_raw,
            employment_type=employment,
            work_mode=work_mode,
            experience_level=experience,
            posted_at=posted_at,
            closes_on=closes_on,
            status=status,
            observed_at=observed_at,
            raw_payload=record,
            source_metadata=source_metadata,
        )
