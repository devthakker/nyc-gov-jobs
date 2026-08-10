import { APIError, getJob, getJobs, subscribeToNewsletter } from "./client";
import { jobDetailFixture, jobFixture } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("preserves repeated query parameters", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        items: [jobFixture],
        pagination: { page: 1, page_size: 12, total_items: 1, total_pages: 1, has_next: false, has_previous: false },
      }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const params = new URLSearchParams();
    params.append("track", "it-data-cybersecurity");
    params.append("track", "customer-service");

    const response = await getJobs(params);

    expect(response.items[0].title).toBe("Help Desk Technician");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/jobs?track=it-data-cybersecurity&track=customer-service",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("returns a typed job detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify(jobDetailFixture), { status: 200 }),
    ));
    expect((await getJob(jobDetailFixture.id)).requirements[0].type).toBe("Minimum qualifications");
  });

  it("turns structured error responses into APIError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "not_found", message: "Missing" } }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    ));

    await expect(getJob("missing")).rejects.toMatchObject({
      status: 404,
      code: "not_found",
      message: "Missing",
    } satisfies Partial<APIError>);
  });

  it("posts a typed newsletter subscription as JSON", async () => {
    const responsePayload = {
      id: "22222222-2222-4222-8222-222222222222",
      email: "devin@example.com",
      name: "Devin",
      status: "subscribed",
      frequency: "weekly",
      all_tracks: true,
      tracks: [],
      subscribed_at: "2026-08-10T12:00:00Z",
      created: true,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responsePayload), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await subscribeToNewsletter({
      email: "devin@example.com",
      name: "Devin",
      frequency: "weekly",
      all_tracks: true,
      track_slugs: [],
      consent: true,
    });

    expect(result.created).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/newsletter/subscriptions",
      expect.objectContaining({
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: expect.stringContaining("devin@example.com"),
      }),
    );
  });
});
