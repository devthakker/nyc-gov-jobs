const API_PARAMETERS = new Set([
  "q",
  "track",
  "source",
  "state",
  "status",
  "work_mode",
  "salary_available",
  "posted_since",
  "primary_track_only",
  "sort",
  "page",
  "page_size",
]);

export function apiSearchParams(source: URLSearchParams): URLSearchParams {
  const output = new URLSearchParams();
  source.forEach((value, key) => {
    if (API_PARAMETERS.has(key) && value) output.append(key, value);
  });
  if (!output.has("page_size")) output.set("page_size", "12");
  return output;
}

export function replaceValue(
  source: URLSearchParams,
  key: string,
  value: string | null,
): URLSearchParams {
  const output = new URLSearchParams(source);
  output.delete(key);
  if (value) output.set(key, value);
  if (key !== "page") output.delete("page");
  return output;
}

export function toggleValue(
  source: URLSearchParams,
  key: string,
  value: string,
): URLSearchParams {
  const output = new URLSearchParams(source);
  const values = output.getAll(key);
  output.delete(key);
  const nextValues = values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];
  nextValues.forEach((item) => output.append(key, item));
  output.delete("page");
  return output;
}

export function activeFilterCount(params: URLSearchParams): number {
  return ["q", "track", "source", "state", "work_mode", "salary_available"].reduce(
    (total, key) => total + params.getAll(key).length,
    0,
  );
}
