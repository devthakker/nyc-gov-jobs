import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { JobsPage } from "./JobsPage";
import { jobFixture, sourceFixture, statsFixture, trackFixture } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());

describe("JobsPage", () => {
  it("loads catalog context and jobs using the URL filters", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.startsWith("/api/v1/jobs?")
        ? {
            items: [jobFixture],
            pagination: { page: 1, page_size: 12, total_items: 1, total_pages: 1, has_next: false, has_previous: false },
          }
        : url === "/api/v1/tracks"
          ? [trackFixture]
          : url === "/api/v1/sources"
            ? [sourceFixture]
            : statsFixture;
      return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?track=it-data-cybersecurity"]}>
          <JobsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Help Desk Technician" })).toBeInTheDocument();
    expect(screen.getByText("1 matches")).toBeInTheDocument();
    expect(screen.getByText("Career track")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("track=it-data-cybersecurity"),
        expect.any(Object),
      );
    });
  });
});
