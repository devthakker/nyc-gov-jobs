import type { Job } from "../api/client";

export function formatNumber(value: number | undefined): string {
  return new Intl.NumberFormat("en-US").format(value ?? 0);
}

export function formatDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const isoDate = value.length === 10 ? `${value}T12:00:00` : value;
  const date = new Date(isoDate);
  if (Number.isNaN(date.valueOf())) return null;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function formatRelativeDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return null;
  const days = Math.round((date.valueOf() - Date.now()) / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  if (days > 1 && days < 30) return `in ${days} days`;
  if (days < -1 && days > -30) return `${Math.abs(days)} days ago`;
  return formatDate(value);
}

export function formatSalary(job: Pick<Job, "salary">): string | null {
  const salary = job.salary;
  if (!salary) return null;
  const currency = salary.currency ?? "USD";
  const formatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  });
  const minimum = salary.minimum == null ? null : formatter.format(salary.minimum);
  const maximum = salary.maximum == null ? null : formatter.format(salary.maximum);
  const range = minimum && maximum ? `${minimum}–${maximum}` : minimum ?? maximum;
  if (range) return `${range}${salary.period ? ` / ${salary.period}` : ""}`;
  return salary.display_text ?? null;
}

export function locationLabel(job: Pick<Job, "location">): string {
  return (
    job.location.text ||
    [job.location.city, job.location.state].filter(Boolean).join(", ") ||
    job.location.region ||
    "Location not listed"
  );
}

export function workModeLabel(value: Job["work_mode"]): string | null {
  if (!value || value === "unknown") return null;
  return value.replace("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}
