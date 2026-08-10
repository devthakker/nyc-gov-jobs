import { Check, RotateCcw, X } from "lucide-react";
import type { Source, Track } from "../api/client";

type FiltersProps = {
  tracks: Track[];
  sources: Source[];
  params: URLSearchParams;
  open: boolean;
  onClose: () => void;
  onToggle: (key: string, value: string) => void;
  onReplace: (key: string, value: string | null) => void;
  onClear: () => void;
};

export function Filters({
  tracks,
  sources,
  params,
  open,
  onClose,
  onToggle,
  onReplace,
  onClear,
}: FiltersProps) {
  const selectedTracks = params.getAll("track");
  const selectedSources = params.getAll("source");

  return (
    <aside className={`filters ${open ? "is-open" : ""}`} aria-label="Filter job listings">
      <div className="filters__mobile-head">
        <strong>Refine opportunities</strong>
        <button type="button" onClick={onClose} aria-label="Close filters"><X size={20} /></button>
      </div>

      <section className="filter-section track-filter">
        <div className="filter-section__heading">
          <div>
            <span className="filter-number">01</span>
            <h2>Career track</h2>
          </div>
          {selectedTracks.length > 0 && <span>{selectedTracks.length} selected</span>}
        </div>
        <div className="track-list">
          {tracks.map((track) => {
            const selected = selectedTracks.includes(track.slug);
            return (
              <button
                type="button"
                key={track.slug}
                className={selected ? "is-selected" : ""}
                aria-pressed={selected}
                onClick={() => onToggle("track", track.slug)}
              >
                <span className="track-list__check">{selected && <Check size={13} />}</span>
                <span className="track-list__name">{track.name}</span>
                <span className="track-list__count">{track.job_count}</span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="filter-section">
        <div className="filter-section__heading">
          <div>
            <span className="filter-number">02</span>
            <h2>Source</h2>
          </div>
        </div>
        <div className="source-list">
          {sources.map((source) => {
            const selected = selectedSources.includes(source.key);
            return (
              <label key={source.key}>
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => onToggle("source", source.key)}
                />
                <span>{source.name}</span>
                <small>{source.active_job_count}</small>
              </label>
            );
          })}
        </div>
      </section>

      <section className="filter-section compact-filters">
        <div className="filter-section__heading">
          <div>
            <span className="filter-number">03</span>
            <h2>Details</h2>
          </div>
        </div>
        <label className="select-label">
          <span>State</span>
          <select value={params.get("state") ?? ""} onChange={(event) => onReplace("state", event.target.value || null)}>
            <option value="">Any state</option>
            <option value="NY">New York</option>
            <option value="NJ">New Jersey</option>
          </select>
        </label>
        <label className="select-label">
          <span>Work mode</span>
          <select
            value={params.get("work_mode") ?? ""}
            onChange={(event) => onReplace("work_mode", event.target.value || null)}
          >
            <option value="">Any arrangement</option>
            <option value="on_site">On site</option>
            <option value="hybrid">Hybrid</option>
            <option value="remote">Remote</option>
          </select>
        </label>
        <label className="salary-toggle">
          <input
            type="checkbox"
            checked={params.get("salary_available") === "true"}
            onChange={(event) => onReplace("salary_available", event.target.checked ? "true" : null)}
          />
          <span>Only roles with listed pay</span>
        </label>
      </section>

      <button type="button" className="clear-filters" onClick={onClear}>
        <RotateCcw size={15} aria-hidden="true" /> Reset all filters
      </button>
      <button type="button" className="filters__done" onClick={onClose}>Show results</button>
    </aside>
  );
}
