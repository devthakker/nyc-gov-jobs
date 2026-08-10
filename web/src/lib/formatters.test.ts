import { formatDate, formatSalary, locationLabel, workModeLabel } from "./formatters";
import { jobFixture } from "../test/fixtures";

describe("job display formatters", () => {
  it("prefers source salary text and canonical location text", () => {
    expect(formatSalary(jobFixture)).toBe("$60,000–$75,000 / year");
    expect(locationLabel(jobFixture)).toBe("Brooklyn, NY");
  });

  it("formats dates and work modes for readers", () => {
    expect(formatDate("2026-08-10")).toBe("Aug 10, 2026");
    expect(workModeLabel("on_site")).toBe("On site");
    expect(workModeLabel("unknown")).toBeNull();
  });
});
