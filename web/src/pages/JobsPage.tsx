import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Mail, Search, SlidersHorizontal, Sparkles } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getJobs, getSources, getStats, getTracks } from "../api/client";
import { Filters } from "../components/Filters";
import { JobCard } from "../components/JobCard";
import { Pagination } from "../components/Pagination";
import { EmptyPanel, ErrorPanel, LoadingLedger } from "../components/StatusViews";
import { formatDate, formatNumber } from "../lib/formatters";
import { activeFilterCount, apiSearchParams, replaceValue, toggleValue } from "../lib/searchParams";

export function JobsPage() {
  const [params, setParams] = useSearchParams();
  const [queryText, setQueryText] = useState(params.get("q") ?? "");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const apiParams = useMemo(() => apiSearchParams(params), [params]);

  useEffect(() => setQueryText(params.get("q") ?? ""), [params]);

  const jobsQuery = useQuery({
    queryKey: ["jobs", apiParams.toString()],
    queryFn: ({ signal }) => getJobs(apiParams, signal),
    placeholderData: (previous) => previous,
  });
  const tracksQuery = useQuery({ queryKey: ["tracks"], queryFn: ({ signal }) => getTracks(signal) });
  const sourcesQuery = useQuery({ queryKey: ["sources"], queryFn: ({ signal }) => getSources(signal) });
  const statsQuery = useQuery({ queryKey: ["stats"], queryFn: ({ signal }) => getStats(signal) });

  const update = (next: URLSearchParams) => setParams(next, { replace: true });
  const clearFilters = () => {
    setQueryText("");
    setParams({}, { replace: true });
  };
  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    const clean = queryText.trim();
    update(replaceValue(params, "q", clean.length >= 2 ? clean : null));
  };
  const page = jobsQuery.data?.pagination.page ?? Number(params.get("page") ?? 1);
  const firstResult = jobsQuery.data ? (page - 1) * jobsQuery.data.pagination.page_size : 0;
  const filterCount = activeFilterCount(params);

  return (
    <>
      <section className="hero">
        <div className="hero__index" aria-hidden="true">NY / 01</div>
        <div className="hero__copy">
          <span className="eyebrow">The public opportunity index</span>
          <h1>Find your way into <em>essential work.</em></h1>
          <p>
            Public-service and apprenticeship openings, organized into career paths you can actually use.
          </p>
        </div>
        <div className="hero__dispatch">
          <span><Sparkles size={16} aria-hidden="true" /> Dispatch note</span>
          <p>Start with a track. Then narrow by employer, place, or pay.</p>
        </div>
        <div className="hero__rule" aria-hidden="true"><span /></div>
      </section>

      <section className="catalog-stats" aria-label="Catalog summary">
        <div><strong>{formatNumber(statsQuery.data?.active_jobs)}</strong><span>active roles</span></div>
        <div><strong>{formatNumber(statsQuery.data?.enabled_sources)}</strong><span>public sources</span></div>
        <div><strong>{formatNumber(statsQuery.data?.active_tracks)}</strong><span>career tracks</span></div>
        <div className="catalog-stats__updated">
          <span>Latest source refresh</span>
          <strong>{formatDate(statsQuery.data?.latest_source_success_at) ?? "Checking…"}</strong>
        </div>
      </section>

      <section className="search-band" aria-label="Search opportunities">
        <form onSubmit={submitSearch}>
          <label htmlFor="job-search">Search by job title, skill, or keyword</label>
          <div className="search-control">
            <Search size={23} aria-hidden="true" />
            <input
              id="job-search"
              type="search"
              value={queryText}
              onChange={(event) => setQueryText(event.target.value)}
              placeholder="Try “electrician” or “help desk”"
            />
            <button type="submit">Search the index</button>
          </div>
        </form>
      </section>

      <div className="opportunity-layout">
        <button className="mobile-filter-button" type="button" onClick={() => setFiltersOpen(true)}>
          <SlidersHorizontal size={17} aria-hidden="true" /> Filters
          {filterCount > 0 && <span>{filterCount}</span>}
        </button>
        {filtersOpen && <button className="filter-scrim" aria-label="Close filters" onClick={() => setFiltersOpen(false)} />}
        <Filters
          tracks={tracksQuery.data ?? []}
          sources={sourcesQuery.data ?? []}
          params={params}
          open={filtersOpen}
          onClose={() => setFiltersOpen(false)}
          onToggle={(key, value) => update(toggleValue(params, key, value))}
          onReplace={(key, value) => update(replaceValue(params, key, value))}
          onClear={clearFilters}
        />

        <section className="results" aria-live="polite">
          <div className="results__head">
            <div>
              <span className="eyebrow">Opportunity ledger</span>
              <h2>
                {jobsQuery.data ? `${formatNumber(jobsQuery.data.pagination.total_items)} matches` : "Reading the index"}
              </h2>
            </div>
            <label>
              <span>Sort</span>
              <select
                value={params.get("sort") ?? "newest"}
                onChange={(event) => update(replaceValue(params, "sort", event.target.value))}
              >
                <option value="newest">Newest first</option>
                <option value="closing_soon">Closing soon</option>
                <option value="salary_desc">Highest listed pay</option>
                <option value="title">Title A–Z</option>
                {params.get("q") && <option value="relevance">Most relevant</option>}
              </select>
            </label>
          </div>

          {jobsQuery.isError ? (
            <ErrorPanel message={jobsQuery.error.message} onRetry={() => jobsQuery.refetch()} />
          ) : jobsQuery.isLoading ? (
            <LoadingLedger />
          ) : jobsQuery.data?.items.length === 0 ? (
            <EmptyPanel onClear={clearFilters} />
          ) : (
            <div className={jobsQuery.isFetching ? "job-list is-refreshing" : "job-list"}>
              {jobsQuery.data?.items.map((job, index) => (
                <JobCard key={job.id} job={job} number={firstResult + index + 1} />
              ))}
            </div>
          )}

          {jobsQuery.data && (
            <Pagination
              page={jobsQuery.data.pagination.page}
              totalPages={jobsQuery.data.pagination.total_pages}
              hasPrevious={jobsQuery.data.pagination.has_previous}
              hasNext={jobsQuery.data.pagination.has_next}
              onPage={(nextPage) => {
                update(replaceValue(params, "page", String(nextPage)));
                const results = document.querySelector(".results");
                const top = results ? window.scrollY + results.getBoundingClientRect().top - 20 : 0;
                window.scrollTo({ top, behavior: "smooth" });
              }}
            />
          )}
        </section>
      </div>

      <section className="dispatch-invite" aria-labelledby="dispatch-invite-title">
        <div className="dispatch-invite__stamp" aria-hidden="true">
          <Mail size={28} />
          <span>Weekly / NY</span>
        </div>
        <div className="dispatch-invite__copy">
          <span className="eyebrow">The opportunity dispatch</span>
          <h2 id="dispatch-invite-title">Let the index come to you.</h2>
          <p>Choose the career tracks you care about. We’ll gather the newest public openings into one useful weekly note.</p>
        </div>
        <Link to="/newsletter">
          Set up job alerts <ArrowUpRight size={19} aria-hidden="true" />
        </Link>
      </section>
    </>
  );
}
