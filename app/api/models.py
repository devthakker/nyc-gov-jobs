"""Validated request and response contracts for the public API."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from math import ceil
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator, model_validator


class JobStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REMOVED = "removed"
    UNKNOWN = "unknown"


class WorkMode(str, Enum):
    ON_SITE = "on_site"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class JobSort(str, Enum):
    NEWEST = "newest"
    OLDEST = "oldest"
    TITLE = "title"
    CLOSING_SOON = "closing_soon"
    SALARY_DESC = "salary_desc"
    RELEVANCE = "relevance"


class StrictQueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobQueryParams(StrictQueryModel):
    """Filters accepted by ``GET /api/v1/jobs``.

    List fields use repeated query parameters, for example
    ``?track=customer-service&track=administrative-office-support``.
    """

    q: str | None = Field(default=None, min_length=2, max_length=200)
    track: list[str] = Field(default_factory=list, max_length=20)
    source: list[str] = Field(default_factory=list, max_length=20)
    state: list[str] = Field(default_factory=list, max_length=20)
    status: list[JobStatus] = Field(default_factory=lambda: [JobStatus.ACTIVE], max_length=4)
    work_mode: list[WorkMode] = Field(default_factory=list, max_length=4)
    salary_available: bool | None = None
    posted_since: date | None = None
    primary_track_only: bool = False
    sort: JobSort = JobSort.NEWEST
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @field_validator("q")
    @classmethod
    def strip_search(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("track", "source", mode="before")
    @classmethod
    def normalize_slug_lists(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return list(dict.fromkeys(str(item).strip().lower() for item in value if str(item).strip()))

    @field_validator("state", mode="before")
    @classmethod
    def normalize_states(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        states = list(dict.fromkeys(str(item).strip().upper() for item in value if str(item).strip()))
        invalid = [state for state in states if len(state) != 2 or not state.isalpha()]
        if invalid:
            raise ValueError("state values must be two-letter codes")
        return states


class TrackQueryParams(StrictQueryModel):
    include_empty: bool = False


class SourceQueryParams(StrictQueryModel):
    enabled_only: bool = True


class APIInfoResponse(BaseModel):
    name: str
    version: str
    documentation_url: str
    openapi_url: str


class SourceRefResponse(BaseModel):
    key: str
    name: str
    last_success_at: datetime | None = None


class EmployerResponse(BaseModel):
    name: str


class LocationResponse(BaseModel):
    text: str | None = None
    city: str | None = None
    borough: str | None = None
    region: str | None = None
    state: str | None = None
    postal_code: str | None = None


class SalaryResponse(BaseModel):
    minimum: float | None = None
    maximum: float | None = None
    currency: str | None = None
    period: str | None = None
    display_text: str | None = None


class TrackAssignmentResponse(BaseModel):
    slug: str
    name: str
    is_primary: bool
    confidence: float = Field(ge=0, le=1)
    review_status: str


class RequirementResponse(BaseModel):
    type: str | None = None
    text: str

    @model_validator(mode="before")
    @classmethod
    def normalize_requirement(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"text": value}
        if isinstance(value, dict):
            text = value.get("text") or value.get("description") or value.get("name")
            return {"type": value.get("type"), "text": str(text or value)}
        return {"text": str(value)}


class LicenseResponse(BaseModel):
    name: str

    @model_validator(mode="before")
    @classmethod
    def normalize_license(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        if isinstance(value, dict):
            name = value.get("name") or value.get("text") or value.get("type")
            return {"name": str(name or value)}
        return {"name": str(value)}


class JobListItemResponse(BaseModel):
    id: UUID
    external_id: str
    title: str
    summary: str | None = None
    canonical_url: HttpUrl
    apply_url: HttpUrl | None = None
    source: SourceRefResponse
    employer: EmployerResponse
    location: LocationResponse
    salary: SalaryResponse | None = None
    source_category: str | None = None
    source_department: str | None = None
    source_agency: str | None = None
    employment_type: str | None = None
    schedule: str | None = None
    work_mode: WorkMode | None = None
    experience_level: str | None = None
    posted_at: datetime | None = None
    opens_on: date | None = None
    closes_on: date | None = None
    status: JobStatus
    tracks: list[TrackAssignmentResponse]
    first_seen_at: datetime
    last_seen_at: datetime
    last_changed_at: datetime


class JobDetailResponse(JobListItemResponse):
    description_text: str | None = None
    requirements_text: str | None = None
    requirements: list[RequirementResponse]
    licenses: list[LicenseResponse]
    experience_years_min: float | None = None
    education_level: str | None = None


class PaginationResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool

    @classmethod
    def from_query(cls, *, page: int, page_size: int, total_items: int) -> Self:
        total_pages = ceil(total_items / page_size) if total_items else 0
        return cls(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1 and total_pages > 0,
        )


class JobListResponse(BaseModel):
    items: list[JobListItemResponse]
    pagination: PaginationResponse


class TrackResponse(BaseModel):
    slug: str
    name: str
    description: str
    taxonomy_version: str
    sort_order: int
    job_count: int
    primary_job_count: int
    needs_review_count: int


class NewsletterSubscriptionRequest(BaseModel):
    """Public signup payload. Consent must be affirmative and preferences explicit."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: str | None = Field(default=None, max_length=100)
    frequency: Literal["weekly"] = "weekly"
    all_tracks: bool = True
    track_slugs: list[str] = Field(default_factory=list, max_length=20)
    consent: Literal[True]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = " ".join(value.split())
        return clean or None

    @field_validator("track_slugs", mode="before")
    @classmethod
    def normalize_track_slugs(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return list(dict.fromkeys(str(item).strip().lower() for item in value if str(item).strip()))

    @model_validator(mode="after")
    def validate_track_choice(self) -> Self:
        if self.all_tracks and self.track_slugs:
            raise ValueError("track_slugs must be empty when all_tracks is true")
        if not self.all_tracks and not self.track_slugs:
            raise ValueError("select at least one track or choose all_tracks")
        return self


class NewsletterTrackResponse(BaseModel):
    slug: str
    name: str


class NewsletterSubscriptionResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str | None
    status: Literal["subscribed"]
    frequency: Literal["weekly"]
    all_tracks: bool
    tracks: list[NewsletterTrackResponse]
    subscribed_at: datetime
    created: bool


class SourceResponse(BaseModel):
    key: str
    name: str
    base_url: HttpUrl
    enabled: bool
    adapter_version: str | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int
    active_job_count: int
    total_job_count: int
    latest_sync_status: str | None = None


class TrackCountResponse(BaseModel):
    slug: str
    name: str
    job_count: int


class StatsResponse(BaseModel):
    generated_at: datetime
    total_jobs: int
    active_jobs: int
    expired_jobs: int
    removed_jobs: int
    unknown_jobs: int
    unclassified_active_jobs: int
    jobs_needing_review: int
    enabled_sources: int
    active_tracks: int
    latest_source_success_at: datetime | None = None
    primary_track_counts: list[TrackCountResponse]


class HealthResponse(BaseModel):
    status: str
    database: str
    checked_at: datetime


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
