import { activeFilterCount, apiSearchParams, replaceValue, toggleValue } from "./searchParams";

describe("URL search parameter helpers", () => {
  it("passes only API parameters and applies the site page size", () => {
    const params = apiSearchParams(new URLSearchParams("q=help+desk&track=it&debug=true"));

    expect(params.toString()).toContain("q=help+desk");
    expect(params.getAll("track")).toEqual(["it"]);
    expect(params.get("debug")).toBeNull();
    expect(params.get("page_size")).toBe("12");
  });

  it("toggles repeated filters without losing unrelated values", () => {
    const original = new URLSearchParams("track=it&source=mta&page=4");
    const added = toggleValue(original, "track", "customer-service");
    const removed = toggleValue(added, "track", "it");

    expect(added.getAll("track")).toEqual(["it", "customer-service"]);
    expect(added.get("source")).toBe("mta");
    expect(added.get("page")).toBeNull();
    expect(removed.getAll("track")).toEqual(["customer-service"]);
  });

  it("resets pagination when a filter changes", () => {
    const next = replaceValue(new URLSearchParams("page=3&sort=newest"), "sort", "title");
    expect(next.get("sort")).toBe("title");
    expect(next.get("page")).toBeNull();
  });

  it("counts repeated active filters", () => {
    expect(activeFilterCount(new URLSearchParams("q=help&track=it&track=admin&sort=title"))).toBe(3);
  });
});
