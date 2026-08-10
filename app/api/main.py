"""ASGI application factory for the Job Tracks public API."""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.models import APIInfoResponse
from app.api.routes import router


API_VERSION = "1.0.0"


def _cors_origins() -> list[str]:
    raw = os.getenv(
        "API_CORS_ORIGINS",
        "http://localhost:4000,http://127.0.0.1:4000",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    application = FastAPI(
        title="Job Tracks API",
        version=API_VERSION,
        summary="Search normalized public jobs by source and occupational track.",
        description=(
            "A versioned API over the local canonical jobs database. Job catalog endpoints "
            "are read-only; the newsletter signup endpoint only stores delivery preferences. "
            "Source payloads and internal classification reasoning are intentionally excluded."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "Job Tracks Pilot"},
        license_info={"name": "Internal pilot"},
    )
    application.add_middleware(GZipMiddleware, minimum_size=1000)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type", "X-Request-ID"],
    )

    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "").strip()
        if not request_id or len(request_id) > 128:
            request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @application.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 422: "validation_error"}
        code = codes.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": str(exc.detail)}},
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "One or more request parameters are invalid.",
                    "details": jsonable_encoder(exc.errors()),
                }
            },
        )

    @application.exception_handler(psycopg.Error)
    async def database_error(_: Request, __: psycopg.Error) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "database_unavailable",
                    "message": "The jobs database is temporarily unavailable.",
                }
            },
            headers={"Retry-After": "5"},
        )

    @application.get(
        "/",
        response_model=APIInfoResponse,
        include_in_schema=False,
    )
    def api_info() -> APIInfoResponse:
        return APIInfoResponse(
            name="Job Tracks API",
            version=API_VERSION,
            documentation_url="/docs",
            openapi_url="/openapi.json",
        )

    application.include_router(router)
    return application


app = create_app()
