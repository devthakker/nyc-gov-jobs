"""Versioned API routes with explicit request and response contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.dependencies import get_newsletter_repository, get_repository
from app.api.models import (
    ErrorResponse,
    HealthResponse,
    JobDetailResponse,
    JobListResponse,
    JobQueryParams,
    NewsletterSubscriptionRequest,
    NewsletterSubscriptionResponse,
    PaginationResponse,
    SourceQueryParams,
    SourceResponse,
    StatsResponse,
    TrackQueryParams,
    TrackResponse,
)
from app.api.newsletter_repository import NewsletterSubscriptionRepository, UnknownTrackSlugs
from app.api.repository import ReadOnlyJobRepository


ERROR_RESPONSES = {
    422: {"model": ErrorResponse, "description": "Invalid query or path parameter"},
    503: {"model": ErrorResponse, "description": "Database unavailable"},
}

router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)
Repository = Annotated[ReadOnlyJobRepository, Depends(get_repository)]
NewsletterRepository = Annotated[
    NewsletterSubscriptionRepository,
    Depends(get_newsletter_repository),
]


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check API and database health",
    tags=["system"],
)
def health(repository: Repository) -> HealthResponse:
    is_read_only = repository.health()
    return HealthResponse(
        status="ok" if is_read_only else "degraded",
        database="read_only" if is_read_only else "unexpected_write_mode",
        checked_at=datetime.now(timezone.utc),
    )


@router.get(
    "/jobs",
    response_model=JobListResponse,
    summary="Search and filter jobs",
    tags=["jobs"],
)
def list_jobs(
    filters: Annotated[JobQueryParams, Query()],
    repository: Repository,
) -> JobListResponse:
    jobs, total = repository.list_jobs(filters)
    return JobListResponse(
        items=jobs,
        pagination=PaginationResponse.from_query(
            page=filters.page,
            page_size=filters.page_size,
            total_items=total,
        ),
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobDetailResponse,
    responses={404: {"model": ErrorResponse, "description": "Job not found"}},
    summary="Get one canonical job",
    tags=["jobs"],
)
def get_job(job_id: UUID, repository: Repository) -> dict:
    job = repository.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested job does not exist.",
        )
    return job


@router.get(
    "/tracks",
    response_model=list[TrackResponse],
    summary="List occupational tracks and counts",
    tags=["catalog"],
)
def list_tracks(
    filters: Annotated[TrackQueryParams, Query()],
    repository: Repository,
) -> list[dict]:
    return repository.list_tracks(include_empty=filters.include_empty)


@router.get(
    "/sources",
    response_model=list[SourceResponse],
    summary="List job sources and synchronization status",
    tags=["catalog"],
)
def list_sources(
    filters: Annotated[SourceQueryParams, Query()],
    repository: Repository,
) -> list[dict]:
    return repository.list_sources(enabled_only=filters.enabled_only)


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Get aggregate job and classification statistics",
    tags=["catalog"],
)
def stats(repository: Repository) -> dict:
    return repository.stats()


@router.post(
    "/newsletter/subscriptions",
    response_model=NewsletterSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": NewsletterSubscriptionResponse, "description": "Preferences updated"},
        201: {"model": NewsletterSubscriptionResponse, "description": "Subscription created"},
    },
    summary="Subscribe to the weekly opportunity dispatch",
    tags=["newsletter"],
)
def subscribe_to_newsletter(
    request: NewsletterSubscriptionRequest,
    response: Response,
    repository: NewsletterRepository,
) -> dict:
    try:
        subscription = repository.subscribe(request)
    except UnknownTrackSlugs as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown or inactive track: {', '.join(exc.slugs)}",
        ) from exc
    if not subscription["created"]:
        response.status_code = status.HTTP_200_OK
    return subscription
