import { ArrowLeft, ArrowRight } from "lucide-react";

type PaginationProps = {
  page: number;
  totalPages: number;
  hasPrevious: boolean;
  hasNext: boolean;
  onPage: (page: number) => void;
};

export function Pagination({ page, totalPages, hasPrevious, hasNext, onPage }: PaginationProps) {
  if (totalPages <= 1) return null;
  const visible = Array.from(
    new Set([1, page - 1, page, page + 1, totalPages].filter((item) => item >= 1 && item <= totalPages)),
  );

  return (
    <nav className="pagination" aria-label="Job results pages">
      <button type="button" disabled={!hasPrevious} onClick={() => onPage(page - 1)}>
        <ArrowLeft size={16} aria-hidden="true" /> Previous
      </button>
      <div className="pagination__pages">
        {visible.map((item, index) => (
          <span className="pagination__slot" key={item}>
            {index > 0 && item - visible[index - 1] > 1 && <span aria-hidden="true">…</span>}
            <button
              type="button"
              className={item === page ? "is-current" : ""}
              aria-current={item === page ? "page" : undefined}
              onClick={() => onPage(item)}
            >
              {item}
            </button>
          </span>
        ))}
      </div>
      <button type="button" disabled={!hasNext} onClick={() => onPage(page + 1)}>
        Next <ArrowRight size={16} aria-hidden="true" />
      </button>
    </nav>
  );
}
