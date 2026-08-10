import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { NewsletterPage } from "./NewsletterPage";
import { trackFixture } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NewsletterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NewsletterPage", () => {
  it("saves an all-tracks signup and shows the confirmation receipt", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).startsWith("/api/v1/tracks")) {
        return Promise.resolve(new Response(JSON.stringify([trackFixture]), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({
        id: "22222222-2222-4222-8222-222222222222",
        email: "devin@example.com",
        name: "Devin",
        status: "subscribed",
        frequency: "weekly",
        all_tracks: true,
        tracks: [],
        subscribed_at: "2026-08-10T12:00:00Z",
        created: true,
      }), { status: 201 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/First name/), "Devin");
    await user.type(screen.getByLabelText("Email address"), "devin@example.com");
    await user.click(screen.getByLabelText(/I agree to receive/));
    await user.click(screen.getByRole("button", { name: /Start my weekly dispatch/ }));

    expect(await screen.findByRole("heading", { name: "You’re on the list." })).toBeInTheDocument();
    expect(screen.getByText("devin@example.com")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/newsletter/subscriptions",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("requires at least one track when a focused brief is selected", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify([trackFixture]), { status: 200 }),
    ));
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/Only my career tracks/));
    await user.click(screen.getByRole("button", { name: /Start my weekly dispatch/ }));

    expect(screen.getByRole("alert")).toHaveTextContent("Choose at least one career track");
  });
});
