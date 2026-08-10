"""Email-client-friendly rendering aligned with the Job Tracks site design."""

from __future__ import annotations

import html
from datetime import date, datetime
from decimal import Decimal

from app.newsletter.models import DigestJob, Subscriber


INK = "#11231f"
PAPER = "#f3eee4"
CREAM = "#fffaf0"
SIGNAL = "#ec5128"
MINT = "#b7d8cd"
SUN = "#efc650"
MUTED = "#65706b"


def _date(value: date | datetime | None) -> str:
    if value is None:
        return "Not listed"
    return value.strftime("%b %d, %Y").replace(" 0", " ")


def _money(value: Decimal) -> str:
    number = float(value)
    return f"${number:,.0f}" if number.is_integer() else f"${number:,.2f}"


def salary(job: DigestJob) -> str:
    if job.salary_raw:
        return job.salary_raw
    if job.salary_min is None and job.salary_max is None:
        return "Not listed"
    if job.salary_min is not None and job.salary_max is not None:
        amount = f"{_money(job.salary_min)}–{_money(job.salary_max)}"
    else:
        amount = _money(job.salary_min or job.salary_max or Decimal(0))
    period = f" / {job.salary_period}" if job.salary_period else ""
    return f"{amount}{period}"


def location(job: DigestJob) -> str:
    return job.location_text or ", ".join(item for item in (job.city, job.state) if item) or "New York"


def _job_row(job: DigestJob, number: int, site_url: str) -> str:
    detail_url = f"{site_url.rstrip('/')}/jobs/{job.id}"
    title = html.escape(job.title)
    employer = html.escape(job.employer_name)
    source = html.escape(job.source_name)
    track = html.escape(job.track_name or "Public opportunity")
    safe_location = html.escape(location(job))
    safe_salary = html.escape(salary(job))
    deadline = html.escape(_date(job.closes_on))
    official_url = html.escape(job.apply_url or job.canonical_url, quote=True)
    safe_detail_url = html.escape(detail_url, quote=True)
    summary = ""
    if job.summary:
        clean_summary = " ".join(job.summary.split())
        if len(clean_summary) > 220:
            clean_summary = clean_summary[:217].rsplit(" ", 1)[0] + "…"
        summary = (
            f'<p style="margin:13px 0 0;color:{MUTED};font-size:14px;line-height:1.55;">'
            f"{html.escape(clean_summary)}</p>"
        )
    return f"""
      <tr>
        <td style="padding:0 24px 18px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid {INK};background:{CREAM};">
            <tr>
              <td width="48" valign="top" style="width:48px;padding:22px 0 0;text-align:center;color:{MUTED};font-family:Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:.08em;">{number:02d}</td>
              <td style="padding:20px 18px 22px 0;">
                <p style="margin:0;color:{SIGNAL};font-family:Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;">{source} &nbsp;·&nbsp; <span style="color:{INK};">{track}</span></p>
                <h2 style="margin:10px 0 0;color:{INK};font-family:Georgia,serif;font-size:25px;font-weight:500;line-height:1.08;letter-spacing:-.02em;">
                  <a href="{safe_detail_url}" style="color:{INK};text-decoration:none;">{title}</a>
                </h2>
                <p style="margin:8px 0 0;color:#29403a;font-family:Arial,sans-serif;font-size:13px;font-weight:700;">{employer}</p>
                {summary}
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:18px;border-top:1px solid rgba(17,35,31,.25);border-collapse:collapse;">
                  <tr>
                    <td width="34%" valign="top" style="padding:12px 8px 0 0;color:{MUTED};font-family:Arial,sans-serif;font-size:10px;line-height:1.4;text-transform:uppercase;"><strong style="display:block;color:{INK};font-size:11px;">{safe_location}</strong>Location</td>
                    <td width="33%" valign="top" style="padding:12px 8px 0;color:{MUTED};font-family:Arial,sans-serif;font-size:10px;line-height:1.4;text-transform:uppercase;"><strong style="display:block;color:{INK};font-size:11px;">{safe_salary}</strong>Listed pay</td>
                    <td width="33%" valign="top" style="padding:12px 0 0 8px;color:{MUTED};font-family:Arial,sans-serif;font-size:10px;line-height:1.4;text-transform:uppercase;"><strong style="display:block;color:{INK};font-size:11px;">{deadline}</strong>Closing date</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td colspan="2" style="border-top:1px solid {INK};background:{PAPER};">
                <a href="{official_url}" style="display:block;padding:13px 18px;color:{INK};font-family:Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:.07em;text-align:right;text-decoration:none;text-transform:uppercase;">Open official posting&nbsp; →</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>"""


def render_html(
    subscriber: Subscriber,
    jobs: list[DigestJob],
    *,
    site_url: str,
    generated_at: datetime | None = None,
) -> str:
    generated = generated_at or datetime.now().astimezone()
    greeting = f"For {html.escape(subscriber.name)}," if subscriber.name else "Your weekly brief,"
    track_note = (
        "across the full opportunity index"
        if subscriber.all_tracks
        else f"from {len(subscriber.track_slugs)} selected career track{'s' if len(subscriber.track_slugs) != 1 else ''}"
    )
    rows = "".join(_job_row(job, index, site_url) for index, job in enumerate(jobs, start=1))
    if not rows:
        rows = f"""
        <tr><td style="padding:0 24px 24px;"><div style="border:1px solid {INK};padding:28px;background:{CREAM};"><h2 style="margin:0;font-family:Georgia,serif;font-size:25px;font-weight:500;">No new openings in this edition.</h2><p style="margin:10px 0 0;color:{MUTED};font-family:Arial,sans-serif;font-size:14px;line-height:1.5;">We’ll keep watching the index for the next dispatch.</p></div></td></tr>"""
    safe_site_url = html.escape(site_url.rstrip("/"), quote=True)
    preheader = html.escape(f"{len(jobs)} public opportunities, organized into useful career tracks.")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Job Tracks Opportunity Dispatch</title>
  <style>
    @media only screen and (max-width:620px) {{
      .email-shell {{ width:100% !important; }}
      .mobile-pad {{ padding-left:22px !important; padding-right:22px !important; }}
      .hero-title {{ font-size:42px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:{PAPER};color:{INK};font-family:Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{preheader}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;background:{PAPER};">
    <tr><td align="center" style="padding:28px 10px;">
      <table role="presentation" width="640" cellspacing="0" cellpadding="0" class="email-shell" style="width:640px;max-width:640px;border-collapse:collapse;background:{PAPER};border:1px solid {INK};">
        <tr>
          <td class="mobile-pad" style="padding:18px 26px;border-bottom:1px solid {INK};background:{CREAM};">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>
              <td width="48"><table role="presentation" width="42" height="42" cellspacing="0" cellpadding="0" style="width:42px;height:42px;border-collapse:collapse;background:{SIGNAL};border:1px solid {INK};"><tr><td align="center" style="color:{CREAM};font-size:12px;font-weight:700;">J</td><td align="center" style="border-left:1px solid {INK};color:{CREAM};font-size:12px;font-weight:700;">T</td></tr></table></td>
              <td style="padding-left:12px;color:{INK};font-family:Georgia,serif;font-size:18px;font-weight:600;">Job Tracks<br><span style="color:{MUTED};font-family:Arial,sans-serif;font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;">New York opportunity pilot</span></td>
              <td align="right" style="color:{MUTED};font-size:9px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;">Weekly / NY</td>
            </tr></table>
          </td>
        </tr>
        <tr>
          <td class="mobile-pad" style="padding:54px 34px 48px;background:{INK};">
            <p style="margin:0;color:{MINT};font-size:10px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;">The opportunity dispatch</p>
            <h1 class="hero-title" style="margin:18px 0 0;color:{CREAM};font-family:Georgia,serif;font-size:55px;font-weight:400;line-height:.92;letter-spacing:-.04em;">Less searching.<br><em style="color:{SUN};font-weight:400;">More direction.</em></h1>
            <p style="margin:25px 0 0;color:rgba(255,255,255,.72);font-size:14px;line-height:1.6;">{greeting} {len(jobs)} current opening{'s' if len(jobs) != 1 else ''} {html.escape(track_note)}.</p>
          </td>
        </tr>
        <tr><td style="height:7px;background:{SIGNAL};"><div style="width:24%;height:7px;background:{SUN};"></div></td></tr>
        <tr>
          <td class="mobile-pad" style="padding:22px 24px 18px;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>
              <td style="color:{SIGNAL};font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;">Opportunity ledger</td>
              <td align="right" style="color:{MUTED};font-size:10px;">{html.escape(_date(generated))}</td>
            </tr></table>
          </td>
        </tr>
        {rows}
        <tr>
          <td class="mobile-pad" style="padding:24px 30px;background:{MINT};border-top:1px solid {INK};">
            <h2 style="margin:0;font-family:Georgia,serif;font-size:25px;font-weight:500;">Keep exploring the full index.</h2>
            <p style="margin:9px 0 17px;color:#29403a;font-size:13px;line-height:1.5;">Search every source, career track, employer, and location on Job Tracks.</p>
            <a href="{safe_site_url}" style="display:inline-block;padding:12px 16px;color:{CREAM};background:{SIGNAL};font-size:10px;font-weight:700;letter-spacing:.08em;text-decoration:none;text-transform:uppercase;">Browse current jobs →</a>
          </td>
        </tr>
        <tr><td class="mobile-pad" style="padding:22px 30px;color:{MUTED};background:{CREAM};font-size:10px;line-height:1.6;">Job Tracks organizes public listings for this local pilot. Always confirm requirements and deadlines on the employer’s official posting.<br><br>You received this because this address subscribed to the weekly opportunity dispatch.</td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def render_text(subscriber: Subscriber, jobs: list[DigestJob], *, site_url: str) -> str:
    greeting = f"Hi {subscriber.name}," if subscriber.name else "Hello,"
    lines = [
        "JOB TRACKS — THE OPPORTUNITY DISPATCH",
        greeting,
        f"{len(jobs)} current public opportunity(s) in your weekly brief.",
        "",
    ]
    for number, job in enumerate(jobs, start=1):
        lines.extend(
            [
                f"{number:02d}. {job.title}",
                f"Employer: {job.employer_name}",
                f"Track: {job.track_name or 'Public opportunity'}",
                f"Location: {location(job)}",
                f"Listed pay: {salary(job)}",
                f"Closing date: {_date(job.closes_on)}",
                f"Official posting: {job.apply_url or job.canonical_url}",
                "",
            ]
        )
    lines.extend(
        [
            f"Browse the full index: {site_url.rstrip('/')}",
            "Always confirm requirements and deadlines on the employer's official posting.",
        ]
    )
    return "\n".join(lines)

