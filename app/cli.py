"""Command-line interface for source synchronization."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.adapters import ADAPTERS
from app.adapters.base import CollectionResult, JobSourceAdapter
from app.classification import (
    CLASSIFIER_VERSION,
    TAXONOMY_VERSION,
    classification_counts,
    classify_job,
)
from app.config import Settings
from app.repository import JobRepository


def metadata_observed_at(metadata: dict[str, Any]) -> datetime:
    raw = metadata.get("scraped_at")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def process_collection(
    *,
    repository: JobRepository,
    adapter: JobSourceAdapter,
    collection: CollectionResult,
    run_id: Any,
    source_id: Any,
    limited: bool,
    imported: bool,
) -> dict[str, Any]:
    counts = {
        "discovered": len(collection.records),
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "failed": 0,
    }
    errors: list[dict[str, str]] = []
    observed_at = metadata_observed_at(collection.metadata)

    for record in collection.records:
        external_id = str(record.get("id") or record.get("url") or "unknown")
        if record.get("detail_error"):
            counts["failed"] += 1
            errors.append({"record": external_id, "error": str(record["detail_error"])})
            continue
        try:
            job = adapter.normalize(record, observed_at)
            outcome = repository.upsert_job(source_id, job)
            counts[outcome] += 1
        except Exception as exc:  # One malformed record must not abort the source.
            logging.exception("Record failed: %s", external_id)
            counts["failed"] += 1
            errors.append({"record": external_id, "error": str(exc)})

    expected = collection.metadata.get("site_reported_count")
    count_matches = expected is None or expected == counts["discovered"]
    complete_snapshot = (
        not imported
        and not limited
        and counts["failed"] == 0
        and count_matches
        and counts["discovered"] > 0
    )
    status = "partial" if counts["failed"] else "succeeded"
    diagnostics = {
        **collection.metadata,
        "complete_snapshot": complete_snapshot,
        "count_matches_site": count_matches,
        "errors": errors[:100],
    }
    if errors:
        diagnostics["error_summary"] = f"{len(errors)} record(s) failed"
    missing = repository.finish_sync(
        run_id=run_id,
        source_id=source_id,
        status=status,
        counts=counts,
        diagnostics=diagnostics,
        reconcile=complete_snapshot,
    )
    return {
        "run_id": str(run_id),
        "source": adapter.source_key,
        "status": status,
        "counts": counts,
        "complete_snapshot": complete_snapshot,
        "missing_reconciliation": missing,
    }


def make_adapter(args: argparse.Namespace) -> JobSourceAdapter:
    adapter_class = ADAPTERS[args.source]
    if args.command == "sync" and args.source in {
        "amtrak",
        "cuny",
        "mta",
        "newyork_presbyterian",
        "northwell",
        "nysdol_apprenticeships",
        "nyc_jobs",
        "port_authority",
        "resorts_world_nyc",
        "statejobsny",
    }:
        return adapter_class(
            delay=args.delay,
            timeout=args.timeout,
            retries=args.retries,
            workers=args.workers,
            include_details=not args.listing_only,
        )
    return adapter_class()


def execute_classification(args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    with JobRepository(settings.database_url) as repository:
        jobs = repository.jobs_for_classification(
            source_key=args.source,
            active_only=not args.include_inactive,
            limit=args.limit,
        )
        applied_sets = []
        counts = {
            "considered": len(jobs),
            "classified": 0,
            "unclassified": 0,
            "skipped_human": 0,
            "needs_review": 0,
            "assignments": 0,
            "persisted_changes": 0,
            "unchanged": 0,
        }
        unclassified_samples: list[dict[str, str]] = []
        review_samples: list[dict[str, Any]] = []
        for job in jobs:
            assignments = classify_job(job)
            if args.dry_run:
                outcome = "classified" if assignments else "unclassified"
            else:
                outcome = repository.replace_automated_job_tracks(
                    job["id"], [assignment.as_dict() for assignment in assignments]
                )

            if outcome == "skipped_human":
                counts["skipped_human"] += 1
                continue
            if outcome == "unchanged":
                counts["unchanged"] += 1
            elif not args.dry_run:
                counts["persisted_changes"] += 1
            if not assignments:
                counts["unclassified"] += 1
                if len(unclassified_samples) < 20:
                    unclassified_samples.append(
                        {
                            "source": job["source_key"],
                            "external_id": job["external_id"],
                            "title": job["title"],
                        }
                    )
                continue
            counts["classified"] += 1
            counts["assignments"] += len(assignments)
            if any(item.review_status == "needs_review" for item in assignments):
                counts["needs_review"] += 1
                if len(review_samples) < 20:
                    review_samples.append(
                        {
                            "source": job["source_key"],
                            "external_id": job["external_id"],
                            "title": job["title"],
                            "tracks": [
                                {
                                    "slug": item.track_slug,
                                    "primary": item.is_primary,
                                    "confidence": item.confidence,
                                }
                                for item in assignments
                            ],
                        }
                    )
            applied_sets.append(assignments)

    primary_counts, secondary_counts = classification_counts(applied_sets)
    return {
        "status": "dry_run" if args.dry_run else "succeeded",
        "source": args.source or "all",
        "active_only": not args.include_inactive,
        "taxonomy_version": TAXONOMY_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "counts": counts,
        "primary_track_counts": primary_counts,
        "secondary_track_counts": secondary_counts,
        "unclassified_samples": unclassified_samples,
        "needs_review_samples": review_samples,
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings.from_environment()
    if args.command == "classify":
        return execute_classification(args, settings)
    adapter = make_adapter(args)
    with JobRepository(settings.database_url) as repository:
        run_id, source_id, _ = repository.begin_sync(
            adapter.source_key, adapter.adapter_version
        )
        try:
            if args.command == "sync":
                collection = adapter.collect(limit=args.limit)
                return process_collection(
                    repository=repository,
                    adapter=adapter,
                    collection=collection,
                    run_id=run_id,
                    source_id=source_id,
                    limited=args.limit is not None,
                    imported=False,
                )
            collection = adapter.load_export(Path(args.path))
            return process_collection(
                repository=repository,
                adapter=adapter,
                collection=collection,
                run_id=run_id,
                source_id=source_id,
                limited=False,
                imported=True,
            )
        except Exception as exc:
            repository.fail_sync(run_id, source_id, str(exc))
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobtracks",
        description="Synchronize public job sources into the pilot PostgreSQL database.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync = subparsers.add_parser("sync", help="Collect one live source")
    sync.add_argument("--source", choices=sorted(ADAPTERS), required=True)
    sync.add_argument("--limit", type=int, help="Development-only record limit")
    sync.add_argument("--workers", type=int, default=4)
    sync.add_argument(
        "--listing-only",
        action="store_true",
        help="Collect all listing cards without fetching detail pages",
    )
    sync.add_argument("--delay", type=float, default=0.25)
    sync.add_argument("--timeout", type=float, default=30)
    sync.add_argument("--retries", type=int, default=3)

    importer = subparsers.add_parser("import-json", help="Import an existing scraper export")
    importer.add_argument("--source", choices=sorted(ADAPTERS), required=True)
    importer.add_argument("--path", required=True)

    classify = subparsers.add_parser(
        "classify",
        help="Assign occupational tracks to canonical jobs",
    )
    classify.add_argument("--source", choices=sorted(ADAPTERS))
    classify.add_argument("--limit", type=int, help="Development-only job limit")
    classify.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include expired and removed jobs",
    )
    classify.add_argument(
        "--dry-run",
        action="store_true",
        help="Report proposed assignments without changing PostgreSQL",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.command == "classify":
        if args.limit is not None and args.limit < 1:
            raise SystemExit("--limit must be at least 1")
        return
    if args.command != "sync":
        return
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.delay < 0 or args.timeout <= 0 or args.retries < 0:
        raise SystemExit("delay/retries cannot be negative and timeout must be positive")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    try:
        result = execute(args)
    except Exception as exc:
        logging.error("%s", exc)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
