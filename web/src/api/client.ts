import type { components } from "./schema";

export type Job = components["schemas"]["JobListItemResponse"];
export type JobDetail = components["schemas"]["JobDetailResponse"];
export type JobList = components["schemas"]["JobListResponse"];
export type Track = components["schemas"]["TrackResponse"];
export type Source = components["schemas"]["SourceResponse"];
export type Stats = components["schemas"]["StatsResponse"];
export type APIErrorResponse = components["schemas"]["ErrorResponse"];
export type NewsletterSubscriptionRequest = components["schemas"]["NewsletterSubscriptionRequest"];
export type NewsletterSubscription = components["schemas"]["NewsletterSubscriptionResponse"];

export class APIError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "APIError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(
  path: string,
  options: { signal?: AbortSignal; method?: "GET" | "POST"; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method: options.method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  if (!response.ok) {
    let payload: APIErrorResponse | undefined;
    try {
      payload = (await response.json()) as APIErrorResponse;
    } catch {
      payload = undefined;
    }
    throw new APIError(
      response.status,
      payload?.error.code ?? "request_failed",
      payload?.error.message ?? `Request failed with status ${response.status}.`,
    );
  }

  return (await response.json()) as T;
}

export function getJobs(params: URLSearchParams, signal?: AbortSignal): Promise<JobList> {
  const query = params.toString();
  return request<JobList>(`/api/v1/jobs${query ? `?${query}` : ""}`, { signal });
}

export function getJob(jobId: string, signal?: AbortSignal): Promise<JobDetail> {
  return request<JobDetail>(`/api/v1/jobs/${encodeURIComponent(jobId)}`, { signal });
}

export function getTracks(signal?: AbortSignal, includeEmpty = false): Promise<Track[]> {
  return request<Track[]>(`/api/v1/tracks${includeEmpty ? "?include_empty=true" : ""}`, { signal });
}

export function getSources(signal?: AbortSignal): Promise<Source[]> {
  return request<Source[]>("/api/v1/sources", { signal });
}

export function getStats(signal?: AbortSignal): Promise<Stats> {
  return request<Stats>("/api/v1/stats", { signal });
}

export function subscribeToNewsletter(
  subscription: NewsletterSubscriptionRequest,
  signal?: AbortSignal,
): Promise<NewsletterSubscription> {
  return request<NewsletterSubscription>("/api/v1/newsletter/subscriptions", {
    method: "POST",
    body: subscription,
    signal,
  });
}
