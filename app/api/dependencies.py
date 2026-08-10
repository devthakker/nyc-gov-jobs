"""FastAPI dependency providers."""

from __future__ import annotations

import os
from collections.abc import Iterator

from app.api.repository import ReadOnlyJobRepository
from app.api.newsletter_repository import NewsletterSubscriptionRepository
from app.config import Settings


def get_repository() -> Iterator[ReadOnlyJobRepository]:
    settings = Settings.from_environment()
    timeout_ms = int(os.getenv("API_STATEMENT_TIMEOUT_MS", "5000"))
    with ReadOnlyJobRepository(
        settings.database_url,
        statement_timeout_ms=timeout_ms,
    ) as repository:
        yield repository


def get_newsletter_repository() -> Iterator[NewsletterSubscriptionRepository]:
    settings = Settings.from_environment()
    timeout_ms = int(os.getenv("API_STATEMENT_TIMEOUT_MS", "5000"))
    with NewsletterSubscriptionRepository(
        settings.database_url,
        statement_timeout_ms=timeout_ms,
    ) as repository:
        yield repository
