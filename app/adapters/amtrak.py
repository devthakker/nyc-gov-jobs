"""Amtrak adapter for its public SAP SuccessFactors careers board."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from app.adapters.base import CollectionResult, JobSourceAdapter
from app.adapters.public_web import PublicPageClient, attribute, class_names, html_to_text, optional_text
from app.domain import CanonicalJob


PUBLIC_ROOT = "https://careers.amtrak.com"
BOARD_URL = f"{PUBLIC_ROOT}/go/View-All-Jobs-at-Amtrak/400419/"
NY_TIMEZONE = ZoneInfo("America/New_York")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

# Order is intentional: specific occupational families win over broad
# Engineering/Mechanical and Corporate memberships when a job appears in more
# than one official Amtrak category.
CATEGORY_BOARDS = {
    "Information Technology": f"{PUBLIC_ROOT}/go/Information-Technology/8337000/",
    "Railroad Operations": f"{PUBLIC_ROOT}/go/Railroad-Operations/8337200/",
    "Customer Service": f"{PUBLIC_ROOT}/go/Customer-Service/8336700/",
    "Laborer Skilled Trades": f"{PUBLIC_ROOT}/go/Laborer-Skilled-Trades/8337100/",
    "Internships & Co-ops": f"{PUBLIC_ROOT}/go/Internship-%26-Co-Ops/8336900/",
    "Engineering & Mechanical": f"{PUBLIC_ROOT}/go/Engineering-%26-Mechanical/8336800/",
    "Corporate": f"{PUBLIC_ROOT}/go/Corporate/8336600/",
}


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def page_url(board_url: str, offset: int) -> str:
    path = board_url if offset == 0 else f"{board_url}{offset}/"
    return f"{path}?q=&sortColumn=referencedate&sortDirection=desc"


def token_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = [part for part in urlparse(url).path.split("/") if part]
    for part in reversed(parts):
        if part.isdigit():
            return part
    return None


def parse_date(value: Any) -> date | None:
    text = optional_text(value)
    if not text:
        return None
    for pattern in (
        "%b %d, %Y",
        "%a %b %d %H:%M:%S UTC %Y",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%d",
    ):
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
    maximum = amounts[1] if len(amounts) > 1 else amounts[0]
    # Amtrak labels the field "salary/hourly range" without publishing a unit.
    # Values under $500 are hourly; larger values are annual compensation.
    period = "hour" if maximum <= Decimal("500") else "year"
    return amounts[0], maximum, period


def parse_state(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = re.search(r"\b[A-Z]{2}\b", text.upper())
    return match.group(0) if match else None


class AmtrakListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict[str, Any]] = []
        self.table_found = False
        self.table_complete = False
        self._table_depth: int | None = None
        self._row: dict[str, Any] | None = None
        self._field: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and attribute(attrs, "id") == "searchresults":
            self.table_found = True
            self._table_depth = 1
            return
        if self._table_depth is None:
            return
        if tag == "table":
            self._table_depth += 1
        elif tag == "tr" and "data-row" in class_names(attrs):
            self._row = {}
        elif tag == "a" and self._row is not None and "jobTitle-link" in class_names(attrs) and not self._row.get("title"):
            href = attribute(attrs, "href")
            if href:
                self._row["url"] = urljoin(PUBLIC_ROOT, href)
                self._field = "title"
                self._parts = []
        elif tag == "td" and self._row is not None:
            classes = class_names(attrs)
            if "colLocation" in classes:
                self._field = "location"
                self._parts = []
            elif "colDate" in classes:
                self._field = "posted"
                self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._table_depth is None:
            return
        if tag == "a" and self._row is not None and self._field == "title":
            self._row["title"] = optional_text("".join(self._parts))
            self._field = None
        elif tag == "td" and self._row is not None and self._field in {"location", "posted"}:
            self._row[self._field] = optional_text("".join(self._parts))
            self._field = None
        elif tag == "tr" and self._row is not None:
            token = token_from_url(self._row.get("url"))
            if token and self._row.get("title"):
                self._row["id"] = token
                self.records.append(self._row)
            self._row = None
            self._field = None
        elif tag == "table":
            self._table_depth -= 1
            if self._table_depth == 0:
                self.table_complete = True
                self._table_depth = None

    def handle_data(self, data: str) -> None:
        if self._field:
            self._parts.append(data)


class AmtrakDetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, str] = {}
        self.apply_url: str | None = None
        self.description_parts: list[str] = []
        self._title = False
        self._title_parts: list[str] = []
        self._description_depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        itemprop = attribute(attrs, "itemprop")
        if tag == "meta" and itemprop:
            value = attribute(attrs, "content")
            if value:
                self.fields[itemprop] = value
        if tag == "span" and itemprop == "title":
            self._title = True
            self._title_parts = []
        if self._description_depth is None and tag == "span" and "jobdescription" in class_names(attrs):
            self._description_depth = 1
            return
        if self._description_depth is not None:
            self.description_parts.append(self.get_starttag_text() or f"<{tag}>")
            if tag not in VOID_TAGS:
                self._description_depth += 1
            return
        if tag == "a" and "apply" in class_names(attrs) and self.apply_url is None:
            href = attribute(attrs, "href")
            if href:
                self.apply_url = urljoin(PUBLIC_ROOT, href)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._description_depth is not None:
            self.description_parts.append(self.get_starttag_text() or f"<{tag} />")

    def handle_endtag(self, tag: str) -> None:
        if self._description_depth is not None:
            if self._description_depth == 1 and tag == "span":
                self._description_depth = None
                return
            self.description_parts.append(f"</{tag}>")
            if tag not in VOID_TAGS:
                self._description_depth -= 1
            return
        if tag == "span" and self._title:
            self.fields["title"] = optional_text("".join(self._title_parts)) or ""
            self._title = False

    def handle_data(self, data: str) -> None:
        if self._description_depth is not None:
            import html

            self.description_parts.append(html.escape(data))
        elif self._title:
            self._title_parts.append(data)


def parse_listing_html(source: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    parser = AmtrakListingParser()
    parser.feed(source)
    if not parser.table_found or not parser.table_complete:
        raise RuntimeError("Amtrak response omitted a complete search-results table")
    count_match = re.search(
        r"Results\s*<b>\s*([0-9]+)\s*[–-]\s*([0-9]+)\s*</b>\s*of\s*<b>\s*([0-9]+)",
        source,
        flags=re.I,
    )
    if not count_match:
        raise RuntimeError("Amtrak response omitted pagination counts")
    return parser.records, {
        "start": int(count_match.group(1)),
        "end": int(count_match.group(2)),
        "total": int(count_match.group(3)),
    }


def parse_detail_html(source: str) -> dict[str, Any]:
    if re.search(r"this position has been filled", source, flags=re.I):
        return {
            "filled": True,
            "description_html": "<p>Sorry, this position has been filled.</p>",
        }
    parser = AmtrakDetailParser()
    parser.feed(source)
    description_html = "".join(parser.description_parts)
    if not parser.fields.get("title") or not description_html:
        raise RuntimeError("Amtrak detail page omitted its title or description")
    return {**parser.fields, "apply_url": parser.apply_url, "description_html": description_html}


def extract_section(text: str | None, heading: str, following: tuple[str, ...]) -> str | None:
    if not text:
        return None
    stops = "|".join(re.escape(item) for item in following)
    match = re.search(
        rf"(?:^|\n){re.escape(heading)}\s*\n(.+?)(?=\n(?:{stops})\s*\n|\Z)",
        text,
        flags=re.I | re.S,
    )
    return match.group(1).strip() if match else None


class AmtrakJobsAdapter(JobSourceAdapter):
    source_key = "amtrak"
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

    def _collect_board(self, board_url: str, *, limit: int | None = None) -> tuple[list[dict[str, Any]], int]:
        first_records, metadata = parse_listing_html(self.client.get_text(page_url(board_url, 0)))
        if not first_records:
            raise RuntimeError(f"Amtrak board returned no listings: {board_url}")
        total = metadata["total"]
        page_size = metadata["end"] - metadata["start"] + 1
        records = list(first_records)
        needed = total if limit is None else min(total, limit)
        for offset in range(page_size, needed, page_size):
            page_records, page_metadata = parse_listing_html(self.client.get_text(page_url(board_url, offset)))
            if page_metadata["total"] != total or page_metadata["start"] != offset + 1:
                raise RuntimeError(f"Amtrak pagination changed while loading offset {offset}")
            if not page_records:
                raise RuntimeError(f"Amtrak pagination returned no listings at offset {offset}")
            records.extend(page_records)
        unique = {str(record["id"]): record for record in records}
        if limit is None and len(unique) != total:
            raise RuntimeError(f"Amtrak board yielded {len(unique)} unique jobs; site reported {total}")
        values = list(unique.values())
        return values[:limit] if limit is not None else values, total

    def _category_map(self) -> tuple[dict[str, list[str]], list[str]]:
        categories: dict[str, list[str]] = {}
        errors: list[str] = []
        for label, board_url in CATEGORY_BOARDS.items():
            try:
                records, _ = self._collect_board(board_url)
            except Exception as exc:
                errors.append(f"{label}: {exc}")
                continue
            for record in records:
                categories.setdefault(str(record["id"]), []).append(label)
        return categories, errors

    def collect(self, *, limit: int | None = None) -> CollectionResult:
        last_error: RuntimeError | None = None
        # SuccessFactors results can change while a five-page snapshot is in
        # flight. Restart the entire listing pass a few times; never reconcile
        # a mixed-total result.
        for attempt in range(4):
            try:
                records, reported_count = self._collect_board(BOARD_URL, limit=limit)
                break
            except RuntimeError as exc:
                last_error = exc
                if limit is not None or attempt == 3:
                    raise
        else:  # pragma: no cover - the loop either succeeds or raises
            raise last_error or RuntimeError("Amtrak collection failed")
        category_map, category_errors = self._category_map()
        prepared: list[dict[str, Any]] = []
        for record in records:
            native_categories = category_map.get(str(record["id"]), [])
            prepared.append(
                {
                    **record,
                    "category": native_categories[0] if native_categories else None,
                    "native_categories": native_categories,
                }
            )
        records = prepared

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
                "category_mapping_coverage": sum(bool(record.get("native_categories")) for record in records),
                "category_mapping_errors": category_errors,
                "collection_url": BOARD_URL,
                "collection_backend": "Amtrak public SAP SuccessFactors board",
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
        return CollectionResult(
            records=prepared,
            metadata={**metadata, "mode": "import", "import_path": str(path), "adapter_version": self.adapter_version},
        )

    def normalize(self, record: dict[str, Any], observed_at: datetime) -> CanonicalJob:
        detail = record.get("detail") if isinstance(record.get("detail"), dict) else {}
        external_id = optional_text(record.get("id"))
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        canonical_url = optional_text(record.get("url"))
        if not external_id or not title or not canonical_url:
            raise ValueError("Amtrak record requires a platform ID, title, and canonical URL")

        description_html = detail.get("description_html")
        description = html_to_text(description_html)
        headings = (
            "Essential Functions", "Minimum Qualifications", "Preferred Qualifications",
            "Knowledge, Skills, and Abilities", "Environmental Conditions/Physical Demands",
        )
        summary = extract_section(description, "Job Summary", headings)
        minimum = extract_section(description, "Minimum Qualifications", headings[2:])
        preferred = extract_section(description, "Preferred Qualifications", headings[3:])
        requirement_sections = [("Minimum Qualifications", minimum), ("Preferred Qualifications", preferred)]
        requirements = [{"type": heading, "text": text} for heading, text in requirement_sections if text]
        requirements_text = "\n\n".join(f"{heading}\n{text}" for heading, text in requirement_sections if text) or None

        salary_match = re.search(
            r"salary/hourly range is\s*(\$\s*[0-9][0-9,.]*(?:\s*[–-]\s*\$?\s*[0-9][0-9,.]*)?)",
            description or "",
            flags=re.I,
        )
        salary_raw = optional_text(salary_match.group(1)) if salary_match else None
        salary_min, salary_max, salary_period = parse_salary(salary_raw)
        work_match = re.search(r"Work Arrangement:\s*([^\n]+?)(?=\s+Click here|\n|$)", description or "", flags=re.I)
        work_arrangement = optional_text(work_match.group(1)) if work_match else None
        mode_text = (work_arrangement or title).casefold()
        work_mode = "remote" if "remote" in mode_text else "hybrid" if "hybrid" in mode_text else "on_site"

        city = optional_text(detail.get("addressLocality"))
        state = parse_state(detail.get("addressRegion"))
        postal_code = optional_text(detail.get("postalCode"))
        country = optional_text(detail.get("addressCountry"))
        location_text = ", ".join(part for part in (city, state, country, postal_code) if part) or optional_text(record.get("location"))
        posted = parse_date(detail.get("datePosted")) or parse_date(record.get("posted"))
        posted_at = datetime.combine(posted, datetime_time.min, NY_TIMEZONE) if posted else None
        requisition_match = re.search(r"Requisition ID:\s*([A-Za-z0-9-]+)", description or "", flags=re.I)
        job_code_match = re.search(r"\s-\s(\d{8})\s-\s", title)

        return CanonicalJob(
            source_key=self.source_key,
            employer_name="Amtrak",
            external_id=external_id,
            title=title,
            normalized_title=normalize_title(title),
            summary=summary,
            description_text=description,
            requirements_text=requirements_text,
            requirements=requirements,
            canonical_url=canonical_url,
            apply_url=optional_text(detail.get("apply_url")) or canonical_url,
            source_category=optional_text(record.get("category")),
            source_agency="Amtrak",
            location_text=location_text,
            city=city,
            state=state,
            postal_code=postal_code,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if salary_min is not None else None,
            salary_period=salary_period,
            salary_raw=salary_raw,
            work_mode=work_mode,
            posted_at=posted_at,
            status="removed" if detail.get("filled") is True else "active",
            observed_at=observed_at,
            raw_payload=record,
            source_metadata={
                "details_included": bool(record.get("_details_included")),
                "listing_only_preserve_fields": ["employer_name", "source_agency", "work_mode", "status"],
                "successfactors_job_id": external_id,
                "requisition_id": requisition_match.group(1) if requisition_match else None,
                "amtrak_job_code": job_code_match.group(1) if job_code_match else None,
                "native_categories": record.get("native_categories", []),
                "work_arrangement": work_arrangement,
                "filled_notice": detail.get("filled") is True,
                "collection_backend": "Amtrak public SAP SuccessFactors board",
            },
        )
