"""CLI for previewing and sending the opportunity dispatch."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.config import Settings
from app.newsletter.mailer import build_message, send_message
from app.newsletter.models import Subscriber
from app.newsletter.renderer import render_html, render_text
from app.newsletter.repository import NewsletterRepository


DEFAULT_SUBJECT = "Job Tracks — Your weekly opportunity dispatch"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render or send the Job Tracks newsletter")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preview", "send"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--max-jobs", type=int, default=20)
        sub.add_argument("--track", action="append", default=[])
        sub.add_argument("--site-url", default=os.getenv("SITE_URL", "http://localhost:4000"))
        sub.add_argument("--subject", default=DEFAULT_SUBJECT)
        sub.add_argument("--to", action="append", default=[])
    preview = subparsers.choices["preview"]
    preview.add_argument("--output", type=Path, default=Path("newsletter-preview.html"))
    send = subparsers.choices["send"]
    send.add_argument("--from-address", default=os.getenv("NEWSLETTER_FROM", "Job Tracks <dispatch@jobtracks.local>"))
    send.add_argument("--smtp-host", default=os.getenv("SMTP_HOST", "mailpit"))
    send.add_argument("--smtp-port", type=int, default=int(os.getenv("SMTP_PORT", "1025")))
    send.add_argument("--smtp-security", choices=("none", "starttls", "ssl"), default=os.getenv("SMTP_SECURITY", "none"))
    send.add_argument("--smtp-username", default=os.getenv("SMTP_USERNAME"))
    send.add_argument("--smtp-password", default=os.getenv("SMTP_PASSWORD"))
    return parser


def _preview_subscriber(address: str, tracks: list[str]) -> Subscriber:
    return Subscriber(
        id=None,
        email=address,
        name="Preview reader",
        all_tracks=not tracks,
        track_slugs=tuple(tracks),
    )


def main() -> None:
    args = _parser().parse_args()
    if not 1 <= args.max_jobs <= 100:
        raise SystemExit("--max-jobs must be between 1 and 100")
    settings = Settings.from_environment()
    with NewsletterRepository(settings.database_url) as repository:
        if args.command == "preview":
            subscriber = _preview_subscriber(
                args.to[0] if args.to else "preview@jobtracks.local",
                args.track,
            )
            jobs = repository.list_jobs(track_slugs=subscriber.track_slugs, max_jobs=args.max_jobs)
            output = render_html(subscriber, jobs, site_url=args.site_url)
            args.output.write_text(output, encoding="utf-8")
            print(f"Rendered {len(jobs)} jobs to {args.output}")
            return

        subscribers = (
            [_preview_subscriber(address, args.track) for address in args.to]
            if args.to
            else repository.list_subscribers()
        )
        if not subscribers:
            print("No active subscribers. Nothing was sent.")
            return

        deliveries: list[tuple[Subscriber, list, str, str]] = []
        for subscriber in subscribers:
            tracks = () if subscriber.all_tracks else subscriber.track_slugs
            jobs = repository.list_jobs(track_slugs=tracks, max_jobs=args.max_jobs)
            deliveries.append(
                (
                    subscriber,
                    jobs,
                    render_text(subscriber, jobs, site_url=args.site_url),
                    render_html(subscriber, jobs, site_url=args.site_url),
                )
            )

        issue = repository.create_issue(
            subject=args.subject,
            job_ids=(job.id for _, jobs, _, _ in deliveries for job in jobs),
            recipient_count=len(deliveries),
            rendered_content="\n".join(html_body for _, _, _, html_body in deliveries),
            max_jobs=args.max_jobs,
        )
        repository.mark_sending(issue)
        sent = 0
        try:
            for subscriber, jobs, text_body, html_body in deliveries:
                message = build_message(
                    subject=args.subject,
                    sender=args.from_address,
                    recipient=subscriber.email,
                    text_body=text_body,
                    html_body=html_body,
                )
                send_message(
                    message,
                    host=args.smtp_host,
                    port=args.smtp_port,
                    security=args.smtp_security,
                    username=args.smtp_username,
                    password=args.smtp_password,
                )
                sent += 1
                print(f"Sent {len(jobs)} jobs to {subscriber.email}")
        except Exception as exc:
            repository.mark_failed(issue, recipient_count=sent, error=str(exc))
            raise
        repository.mark_sent(issue, recipient_count=sent)
        print(f"Issue {issue} sent to {sent} subscriber(s)")


if __name__ == "__main__":
    main()
