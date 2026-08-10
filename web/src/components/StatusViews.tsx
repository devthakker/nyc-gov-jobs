import { AlertTriangle, SearchX } from "lucide-react";

export function LoadingLedger() {
  return (
    <div className="loading-ledger" aria-label="Loading jobs" role="status">
      {Array.from({ length: 4 }).map((_, index) => (
        <div className="loading-row" key={index}>
          <span />
          <div><i /><i /><i /></div>
        </div>
      ))}
    </div>
  );
}

export function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="status-panel status-panel--error" role="alert">
      <AlertTriangle size={28} aria-hidden="true" />
      <div><h2>We lost the data line.</h2><p>{message}</p></div>
      <button type="button" onClick={onRetry}>Try again</button>
    </div>
  );
}

export function EmptyPanel({ onClear }: { onClear: () => void }) {
  return (
    <div className="status-panel">
      <SearchX size={32} aria-hidden="true" />
      <div>
        <h2>No exact matches—yet.</h2>
        <p>Try removing a filter or using a broader job title.</p>
      </div>
      <button type="button" onClick={onClear}>Clear filters</button>
    </div>
  );
}
