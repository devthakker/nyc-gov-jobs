"""Resorts World NYC adapter for its official Workday careers portal."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as datetime_time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from app.adapters.base import CollectionResult, JobSourceAdapter
from app.adapters.public_web import PublicPageClient, html_to_text, optional_text
from app.domain import CanonicalJob


PUBLIC_ROOT = "https://rwlasvegas.wd501.myworkdayjobs.com/Resorts_World_External_Careers"
API_ROOT = "https://rwlasvegas.wd501.myworkdayjobs.com/wday/cxs/rwlasvegas/Resorts_World_External_Careers"
SEARCH_URL = f"{API_ROOT}/jobs"
PAGE_SIZE = 20
NY_TIMEZONE = ZoneInfo("America/New_York")


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def search_payload(*, offset: int, facets: dict[str, list[str]] | None = None) -> dict[str, Any]:
    return {"appliedFacets": facets or {}, "limit": PAGE_SIZE, "offset": offset, "searchText": ""}


def validate_search(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    try:
        total = int(payload["total"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Resorts World response omitted a valid total") from exc
    rows = payload.get("jobPostings")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError("Resorts World response omitted a valid jobPostings list")
    return rows, total


def req_id(record: dict[str, Any]) -> str | None:
    fields = record.get("bulletFields")
    if isinstance(fields, list) and fields:
        return optional_text(fields[0])
    return optional_text(record.get("jobReqId"))


def parse_iso_date(value: Any) -> datetime | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        day = datetime.fromisoformat(text).date()
    except ValueError:
        return None
    return datetime.combine(day, datetime_time.min, NY_TIMEZONE)


def sections(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    heading_pattern = re.compile(r"(?m)^([A-Z][A-Za-z/& ,()-]{2,50}):?\s*$")
    matches = list(heading_pattern.finditer(text))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            result[match.group(1).strip().casefold()] = content
    return result


def salary_excerpt(text: str | None) -> str | None:
    if not text:
        return None
    for pattern in (
        r"[^\n]*(?:salary|pay range|hourly rate|compensation)[^\n]*\$[^\n]+",
        r"\$\s*[0-9][0-9,.]*(?:\s*[–-]\s*\$?\s*[0-9][0-9,.]*)?\s*(?:per|/)\s*(?:hour|year)",
    ):
        match = re.search(pattern, text, flags=re.I)
        if match:
            return optional_text(match.group(0))
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
    maximum = values[1] if len(values) > 1 else values[0]
    lowered = text.casefold()
    period = "hour" if "hour" in lowered or maximum < Decimal("500") else "year"
    return values[0], maximum, period


class ResortsWorldNYCAdapter(JobSourceAdapter):
    source_key = "resorts_world_nyc"
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

    def _collect_search(self, *, facets: dict[str, list[str]] | None = None, limit: int | None = None) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        first_payload = self.client.post_json(SEARCH_URL, search_payload(offset=0, facets=facets))
        rows, total = validate_search(first_payload)
        records = list(rows)
        needed = total if limit is None else min(total, limit)
        for offset in range(PAGE_SIZE, needed, PAGE_SIZE):
            page_payload = self.client.post_json(SEARCH_URL, search_payload(offset=offset, facets=facets))
            page_rows, page_total = validate_search(page_payload)
            if page_total != total or not page_rows:
                raise RuntimeError(f"Resorts World pagination changed or ended at offset {offset}")
            records.extend(page_rows)
        unique: dict[str, dict[str, Any]] = {}
        for record in records:
            token = req_id(record)
            if not token or not optional_text(record.get("externalPath")):
                raise RuntimeError("Resorts World listing omitted a requisition ID or external path")
            unique[token] = record
        if limit is None and len(unique) != total:
            raise RuntimeError(f"Resorts World yielded {len(unique)} unique jobs; Workday reported {total}")
        values = list(unique.values())
        return (values[:limit] if limit is not None else values), total, first_payload

    def _category_map(self, first_payload: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
        mapping: dict[str, str] = {}
        errors: list[str] = []
        facets = first_payload.get("facets") if isinstance(first_payload.get("facets"), list) else []
        category_facet = next((item for item in facets if item.get("facetParameter") == "jobFamilyGroup"), None)
        values = category_facet.get("values", []) if isinstance(category_facet, dict) else []
        for value in values if isinstance(values, list) else []:
            label = optional_text(value.get("descriptor")) if isinstance(value, dict) else None
            facet_id = optional_text(value.get("id")) if isinstance(value, dict) else None
            if not label or not facet_id:
                continue
            try:
                rows, _, _ = self._collect_search(facets={"jobFamilyGroup": [facet_id]})
                for row in rows:
                    token = req_id(row)
                    if token:
                        mapping[token] = label
            except Exception as exc:
                errors.append(f"{label}: {exc}")
        return mapping, errors

    def collect(self, *, limit: int | None = None) -> CollectionResult:
        records, reported_count, first_payload = self._collect_search(limit=limit)
        category_map, category_errors = self._category_map(first_payload)
        records = [{**record, "category": category_map.get(req_id(record) or "")} for record in records]
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
                "category_mapping_coverage": sum(bool(record.get("category")) for record in records),
                "category_mapping_errors": category_errors,
                "collection_url": SEARCH_URL,
                "collection_backend": "Resorts World NYC public Workday API",
                "adapter_version": self.adapter_version,
            },
        )

    def _load_detail(self, listing: dict[str, Any]) -> dict[str, Any]:
        try:
            path = str(listing["externalPath"])
            payload = self.client.get_json(f"{API_ROOT}{path}")
            detail = payload.get("jobPostingInfo")
            if not isinstance(detail, dict) or req_id(detail) != req_id(listing):
                raise RuntimeError("Resorts World detail omitted or mismatched its requisition ID")
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
            records = payload.get("jobs", payload.get("records", payload.get("jobPostings", [])))
            metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
        else:
            raise RuntimeError(f"Unsupported export shape in {path}")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise RuntimeError(f"Export does not contain a valid jobs/records list: {path}")
        prepared = [{**record, "_details_included": isinstance(record.get("detail"), dict)} for record in records]
        return CollectionResult(records=prepared, metadata={**metadata, "mode": "import", "import_path": str(path), "adapter_version": self.adapter_version})

    def normalize(self, record: dict[str, Any], observed_at: datetime) -> CanonicalJob:
        detail = record.get("detail") if isinstance(record.get("detail"), dict) else {}
        external_id = req_id(detail) or req_id(record)
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        canonical_url = optional_text(detail.get("externalUrl"))
        if not canonical_url and optional_text(record.get("externalPath")):
            canonical_url = urljoin(f"{PUBLIC_ROOT}/", str(record["externalPath"]).lstrip("/"))
        if not external_id or not title or not canonical_url:
            raise ValueError("Resorts World record requires a requisition ID, title, and public URL")

        description = html_to_text(detail.get("jobDescription"))
        parsed_sections = sections(description)
        requirement_parts = [
            (name.title(), content)
            for name, content in parsed_sections.items()
            if name in {"essential requirements", "knowledge/work experience", "qualifications", "education/experience"}
        ]
        requirements_text = "\n\n".join(f"{name}\n{content}" for name, content in requirement_parts) or None
        salary_raw = salary_excerpt(description)
        salary_min, salary_max, salary_period = parse_salary(salary_raw)
        location = optional_text(detail.get("location")) or optional_text(record.get("locationsText"))
        is_new_york = bool(location and "resorts world new york" in location.casefold())

        return CanonicalJob(
            source_key=self.source_key,
            employer_name="Resorts World New York City",
            external_id=external_id,
            title=title,
            normalized_title=normalize_title(title),
            summary=parsed_sections.get("job responsibilities"),
            description_text=description,
            requirements_text=requirements_text,
            requirements=[{"type": name, "text": content} for name, content in requirement_parts],
            canonical_url=canonical_url,
            apply_url=canonical_url,
            source_category=optional_text(record.get("category")),
            source_agency="Resorts World New York City",
            location_text=location,
            city="Jamaica" if is_new_york else None,
            state="NY" if is_new_york else None,
            postal_code="11420" if is_new_york else None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if salary_min is not None else None,
            salary_period=salary_period,
            salary_raw=salary_raw,
            employment_type=optional_text(detail.get("timeType")) or optional_text(record.get("timeType")),
            work_mode="on_site",
            posted_at=parse_iso_date(detail.get("startDate")),
            status="active",
            observed_at=observed_at,
            raw_payload=record,
            source_metadata={
                "details_included": bool(record.get("_details_included")),
                "listing_only_preserve_fields": ["employer_name", "source_agency", "work_mode", "status"],
                "workday_requisition_id": external_id,
                "workday_posting_id": optional_text(detail.get("id")),
                "workday_category": optional_text(record.get("category")),
                "collection_backend": "Resorts World NYC public Workday API",
            },
        )
