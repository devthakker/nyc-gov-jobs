import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { jobFixture } from "../test/fixtures";
import { JobCard } from "./JobCard";

describe("JobCard", () => {
  it("shows the normalized opportunity and links to its detail route", () => {
    render(
      <MemoryRouter initialEntries={["/?track=it-data-cybersecurity"]}>
        <JobCard job={jobFixture} number={1} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Help Desk Technician" })).toBeInTheDocument();
    expect(screen.getByText("New York City Transit")).toBeInTheDocument();
    expect(screen.getByText("Brooklyn, NY")).toBeInTheDocument();
    expect(screen.getByText(/\$60,000/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View Help Desk Technician" })).toHaveAttribute(
      "href",
      `/jobs/${jobFixture.id}`,
    );
  });
});
