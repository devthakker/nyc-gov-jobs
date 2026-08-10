"""Versioned, read-only HTTP API for canonical jobs."""

from app.api.main import app, create_app

__all__ = ["app", "create_app"]
