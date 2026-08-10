"""MTA careers adapter using MTA's public Jobvite-hosted job board."""

from __future__ import annotations

import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as datetime_time
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.adapters.base import CollectionResult, JobSourceAdapter
from app.domain import CanonicalJob


BOARD_URL = "https://jobs.jobvite.com/metropolitantransportationauthority/jobs"
PUBLIC_ROOT = "https://jobs.jobvite.com"
NY_TIMEZONE = ZoneInfo("America/New_York")
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def class_names(attrs: list[tuple[str, str | None]]) -> set[str]:
    value = next((value or "" for name, value in attrs if name == "class"), "")
    return set(value.split())


def attribute(attrs: list[tuple[str, str | None]], name: str) -> str | None:
    return next((value for key, value in attrs if key == name), None)


class PublicPageClient:
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

    def get_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_for_slot()
            request = Request(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "jobtracks-pilot/0.1 (public job data ingestion)",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.read().decode(charset, errors="replace")
            except HTTPError as exc:
                last_error = exc
                if exc.code not in RETRYABLE_STATUS_CODES or attempt >= self.retries:
                    break
            except (URLError, TimeoutError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"Request failed for {url}: {last_error}") from last_error


class MTAListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict[str, Any]] = []
        self.current_category: str | None = None
        self._category_parts: list[str] | None = None
        self._row: dict[str, Any] | None = None
        self._field: str | None = None
        self._field_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = class_names(attrs)
        if tag == "h3" and "h2" in classes:
            self._category_parts = []
        elif tag == "tr":
            self._row = {}
        elif tag == "td" and self._row is not None:
            if "jv-job-list-name" in classes:
                self._field = "title"
                self._field_parts = []
            elif "jv-job-list-location" in classes:
                self._field = "location"
                self._field_parts = []
        elif tag == "a" and self._row is not None and self._field == "title":
            href = attribute(attrs, "href")
            if href:
                self._row["url"] = urljoin(PUBLIC_ROOT, href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._category_parts is not None:
            self.current_category = optional_text("".join(self._category_parts))
            self._category_parts = None
        elif tag == "td" and self._row is not None and self._field:
            self._row[self._field] = optional_text("".join(self._field_parts))
            self._field = None
            self._field_parts = []
        elif tag == "tr" and self._row is not None:
            if self._row.get("url") and self._row.get("title"):
                self._row["category"] = self.current_category
                self.records.append(self._row)
            self._row = None
            self._field = None

    def handle_data(self, data: str) -> None:
        if self._category_parts is not None:
            self._category_parts.append(data)
        if self._row is not None and self._field:
            self._field_parts.append(data)


class MTADetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.position_parts: list[str] = []
        self.script_parts: list[str] = []
        self.description_parts: list[str] = []
        self.apply_url: str | None = None
        self._capture_title = False
        self._capture_position = False
        self._capture_script = False
        self._description_depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = class_names(attrs)
        if self._description_depth is None and tag == "div" and "jv-job-detail-description" in classes:
            self._description_depth = 1
            return
        if self._description_depth is not None:
            self.description_parts.append(self.get_starttag_text() or f"<{tag}>")
            if tag not in VOID_TAGS:
                self._description_depth += 1
            if tag == "em":
                self._capture_position = True
            return
        if tag == "h2" and "jv-header" in classes:
            self._capture_title = True
        elif tag == "a" and "jv-button-apply" in classes and self.apply_url is None:
            href = attribute(attrs, "href")
            if href:
                self.apply_url = urljoin(PUBLIC_ROOT, href)
        elif tag == "script":
            self._capture_script = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._description_depth is not None:
            self.description_parts.append(self.get_starttag_text() or f"<{tag} />")

    def handle_endtag(self, tag: str) -> None:
        if self._description_depth is not None:
            if self._description_depth == 1 and tag == "div":
                self._description_depth = None
                self._capture_position = False
                return
            self.description_parts.append(f"</{tag}>")
            if tag not in VOID_TAGS:
                self._description_depth -= 1
            if tag == "em":
                self._capture_position = False
            return
        if tag == "h2":
            self._capture_title = False
        elif tag == "script":
            self._capture_script = False

    def handle_data(self, data: str) -> None:
        if self._description_depth is not None:
            self.description_parts.append(html.escape(data))
            if self._capture_position:
                self.position_parts.append(data)
        elif self._capture_title:
            self.title_parts.append(data)
        elif self._capture_script:
            self.script_parts.append(data)

    def result(self) -> dict[str, Any]:
        scripts = "\n".join(self.script_parts)
        request_match = re.search(r"jobReqId:\s*['\"]([^'\"]+)", scripts)
        token_match = re.search(r"jobId:\s*['\"]([^'\"]+)", scripts)
        return {
            "title": optional_text("".join(self.title_parts)),
            "position_at": re.sub(
                r"^Position\s+at\s+", "", optional_text("".join(self.position_parts)) or "", flags=re.I
            )
            or None,
            "mta_job_id": request_match.group(1) if request_match else None,
            "jobvite_token": token_match.group(1) if token_match else None,
            "apply_url": self.apply_url,
            "description_html": "".join(self.description_parts),
        }


class _ReadableHTMLParser(HTMLParser):
    block_tags = {
        "address", "article", "blockquote", "div", "h1", "h2", "h3", "h4",
        "h5", "h6", "li", "ol", "p", "section", "table", "td", "tr", "ul",
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


def parse_listing_html(source: str) -> list[dict[str, Any]]:
    parser = MTAListingParser()
    parser.feed(source)
    return parser.records


def parse_detail_html(source: str) -> dict[str, Any]:
    parser = MTADetailParser()
    parser.feed(source)
    return parser.result()


def extract_labels(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    lines = [line.strip(" -") for line in text.splitlines() if line.strip(" -")]
    fields: dict[str, str] = {}
    for index, line in enumerate(lines):
        if line.upper().rstrip(":") in {
            "JOB SUMMARY", "DUTIES AND RESPONSIBILITIES", "RESPONSIBILITIES",
            "REQUIRED EDUCATION AND EXPERIENCE", "QUALIFICATIONS",
        }:
            break
        match = re.match(r"^([^:]{2,90}):\s*(.*)$", line)
        if not match:
            continue
        label = optional_text(match.group(1))
        value = optional_text(match.group(2))
        if not value and index + 1 < len(lines) and ":" not in lines[index + 1]:
            value = optional_text(lines[index + 1])
        if label and value and label not in fields:
            fields[label] = value
    return fields


def is_heading(line: str) -> bool:
    stripped = line.strip(" :")
    letters = [char for char in stripped if char.isalpha()]
    return bool(letters) and len(stripped) <= 120 and all(char.isupper() for char in letters)


def extract_sections(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    lines = [line.strip() for line in text.splitlines()]
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if not line:
            continue
        if is_heading(line):
            current = line.strip(" :")
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return {
        heading: "\n".join(content).strip()
        for heading, content in sections.items()
        if content
    }


def parse_us_date(value: Any) -> date | None:
    text = optional_text(value)
    if not text:
        return None
    for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse_money(value: str | None) -> tuple[Decimal | None, Decimal | None, str | None]:
    text = optional_text(value)
    if not text:
        return None, None, None
    amounts: list[Decimal] = []
    for raw in re.findall(r"\$\s*([0-9][0-9,]*(?:\s+[0-9]{3})*(?:\.\d+)?)", text):
        try:
            amounts.append(Decimal(re.sub(r"[,\s]", "", raw)))
        except InvalidOperation:
            continue
    if not amounts:
        return None, None, None
    lowered = text.casefold()
    if "hour" in lowered or "/hr" in lowered:
        period = "hour"
    elif "day" in lowered or "/day" in lowered:
        period = "day"
    elif "week" in lowered:
        period = "week"
    elif "month" in lowered:
        period = "month"
    else:
        period = "year"
    minimum = min(amounts[:2])
    maximum = max(amounts[:2])
    return minimum, maximum, period


def parse_location(value: str | None) -> tuple[str | None, str | None]:
    text = optional_text(value)
    if not text:
        return None, None
    parts = [part.strip() for part in text.split(",") if part.strip()]
    city = parts[0] if parts else None
    state = None
    if len(parts) > 1:
        region = parts[1].upper()
        if region in {"NY", "NEW YORK"}:
            state = "NY"
        elif re.fullmatch(r"[A-Z]{2}", region):
            state = region
    return city, state


def token_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = [part for part in urlparse(url).path.split("/") if part]
    try:
        index = parts.index("job")
        return parts[index + 1]
    except (ValueError, IndexError):
        return None


AGENCY_NAMES = {
    "LIRR": "Long Island Rail Road",
    "MNR": "Metro-North Railroad",
    "NYCT": "New York City Transit",
    "MTAHQ": "MTA Headquarters",
    "MTABC": "MTA Bus Company",
    "SIR": "Staten Island Railway",
    "B&T": "MTA Bridges and Tunnels",
}


class MTAJobsAdapter(JobSourceAdapter):
    source_key = "mta"
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
        listing_html = self.client.get_text(BOARD_URL)
        all_records = parse_listing_html(listing_html)
        if not all_records:
            raise RuntimeError("MTA Jobvite board returned no recognizable job listings")

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
                "collection_backend": "MTA public Jobvite board",
                "coverage_scope": "Openings published on MTA's Jobvite-hosted board",
                "adapter_version": self.adapter_version,
            },
        )

    def _load_detail(self, listing: dict[str, Any]) -> dict[str, Any]:
        try:
            detail_html = self.client.get_text(str(listing["url"]))
            detail = parse_detail_html(detail_html)
            if not detail.get("title"):
                raise RuntimeError("Detail page omitted its job title")
            return {**listing, "detail": detail, "_details_included": True}
        except Exception as exc:
            return {
                **listing,
                "_details_included": False,
                "detail_error": str(exc),
            }

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
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        canonical_url = optional_text(record.get("url"))
        external_id = optional_text(record.get("id")) or token_from_url(canonical_url)
        if not title or not canonical_url or not external_id:
            raise ValueError("MTA record requires a title, URL, and Jobvite token")

        description_html = detail.get("description_html")
        description = html_to_text(description_html)
        labels = extract_labels(description)
        sections = extract_sections(description)
        requirement_sections = [
            (heading, text)
            for heading, text in sections.items()
            if re.search(
                r"REQUIRED|REQUIREMENT|QUALIFICATION|EDUCATION AND EXPERIENCE|"
                r"KNOWLEDGE.{0,12}SKILLS|LICENSE|SELECTION CRITERIA",
                heading,
                flags=re.I,
            )
        ]
        requirements = [
            {"type": heading, "text": text} for heading, text in requirement_sections
        ]
        requirements_text = "\n\n".join(
            f"{heading}\n{text}" for heading, text in requirement_sections
        ) or None
        summary = next(
            (text for heading, text in sections.items() if "JOB SUMMARY" in heading.upper()),
            None,
        )

        agency_raw = optional_text(detail.get("position_at")) or labels.get("MTA Agency")
        employer_name = AGENCY_NAMES.get(agency_raw or "", agency_raw or "Metropolitan Transportation Authority")
        department = labels.get("Department")
        location_text = optional_text(record.get("location")) or labels.get("Primary Location(s)")
        city, state = parse_location(location_text)

        salary_label = next(
            (
                value
                for label, value in labels.items()
                if re.search(r"SALARY|RATE OF PAY|PAY RATE|COMPENSATION", label, flags=re.I)
            ),
            None,
        )
        salary_min, salary_max, period = parse_money(salary_label)
        closing_label = next(
            (value for label, value in labels.items() if "CLOSING DATE" in label.upper()),
            None,
        )
        closes_on = parse_us_date(closing_label)
        status = "active"
        if closes_on and closes_on < observed_at.astimezone(NY_TIMEZONE).date():
            status = "expired"

        posted_on = parse_us_date(record.get("posted_date"))
        posted_at = (
            datetime.combine(posted_on, datetime_time.min, NY_TIMEZONE)
            if posted_on
            else None
        )
        mta_job_id = optional_text(detail.get("mta_job_id"))
        apply_url = optional_text(detail.get("apply_url")) or f"{canonical_url}/apply"
        details_included = bool(record.get("_details_included"))

        return CanonicalJob(
            source_key=self.source_key,
            employer_name=employer_name,
            external_id=external_id,
            title=title,
            normalized_title=normalize_title(title),
            summary=summary,
            description_text=description,
            requirements_text=requirements_text,
            requirements=requirements,
            canonical_url=canonical_url,
            apply_url=apply_url,
            source_category=optional_text(record.get("category")),
            source_department=department,
            source_agency=employer_name,
            location_text=location_text,
            city=city,
            state=state or "NY",
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if salary_min is not None else None,
            salary_period=period,
            salary_raw=salary_label,
            schedule=labels.get("Shift (if applicable)"),
            posted_at=posted_at,
            closes_on=closes_on,
            status=status,
            observed_at=observed_at,
            raw_payload=record,
            source_metadata={
                "details_included": details_included,
                "listing_only_preserve_fields": [
                    "employer_name",
                    "source_agency",
                    "status",
                ],
                "mta_job_id": mta_job_id,
                "jobvite_token": external_id,
                "jobvite_category": optional_text(record.get("category")),
                "position_at": optional_text(detail.get("position_at")),
                "detail_labels": labels,
                "collection_backend": "MTA public Jobvite board",
            },
        )
