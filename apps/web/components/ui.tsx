import type { ReactNode } from "react";

import type { Rating } from "@/lib/api";

const RATINGS: readonly string[] = ["low", "medium", "high"] satisfies Rating[];

/** A rating as the record states it; a value outside low / medium / high is shown as it is, uncoloured. */
export function RiskChip({ rating }: { rating: string | null }) {
  if (!rating) return <span className="chip neutral">not rated</span>;
  return (
    <span className={`chip ${RATINGS.includes(rating) ? rating : "neutral"}`}>
      <span className="chip-dot" aria-hidden />
      {rating}
    </span>
  );
}

const PROV_CLASS: Record<string, string> = {
  ParameterIdentification: "fitted",
  fitted: "fitted",
  measured: "measured",
  Publication: "measured",
  Database: "measured",
  predicted: "predicted",
  assumed: "predicted",
};

export function ProvenanceChip({ source }: { source: string }) {
  const cls = PROV_CLASS[source] ?? "";
  const label = source === "ParameterIdentification" ? "fitted (PI)" : source;
  return <span className={`prov ${cls}`}>{label}</span>;
}

export function Completeness({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="row gap-8">
      <div className="meter w-120">
        <span style={{ width: `${pct}%` }} />
      </div>
      <span className="muted tnum">{pct}%</span>
    </div>
  );
}

export function StatusChip({ status }: { status: string }) {
  const map: Record<string, string> = {
    PASSED: "low", ACCEPTED: "low", COMPLETED: "low", RUNNING: "brand",
    ESCALATED: "high", REJECTED: "high", FAILED: "high", ABORTED: "high", PROPOSED: "medium",
    SKIPPED: "neutral", AWAITING_SIGNATURE: "medium",
    APPROVED: "low", DRAFT: "medium", STALE: "high", SUPERSEDED: "neutral", IN_REVIEW: "medium",
  };
  return <span className={`chip ${map[status] ?? "neutral"}`}>{status.toLowerCase()}</span>;
}

export function Card({ title, action, children }: { title?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || action) && (
        <div className="spread mb-12">
          {title && <h2 className="m-0">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

/** What stopped a page from showing live data. Never paired with sample data. */
export function ApiProblem({ problem }: { problem: string }) {
  return <div className="banner err mb-14" data-testid="api-problem">{problem}</div>;
}
