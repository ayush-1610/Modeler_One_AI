import type { ReactNode } from "react";

import type { Rating } from "@/lib/api";

export function RiskChip({ rating }: { rating: Rating | null }) {
  if (!rating) return <span className="chip neutral">not rated</span>;
  return (
    <span className={`chip ${rating}`}>
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
    <div className="row" style={{ gap: 8 }}>
      <div className="meter" style={{ width: 120 }}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <span className="muted" style={{ fontVariantNumeric: "tabular-nums" }}>{pct}%</span>
    </div>
  );
}

export function StatusChip({ status }: { status: string }) {
  const map: Record<string, string> = {
    PASSED: "low", ACCEPTED: "low", COMPLETED: "low", RUNNING: "brand",
    ESCALATED: "high", REJECTED: "high", FAILED: "high", ABORTED: "high", PROPOSED: "medium",
    SKIPPED: "neutral", AWAITING_SIGNATURE: "medium",
  };
  return <span className={`chip ${map[status] ?? "neutral"}`}>{status.toLowerCase()}</span>;
}

export function Card({ title, action, children }: { title?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || action) && (
        <div className="spread" style={{ marginBottom: 12 }}>
          {title && <h2 style={{ margin: 0 }}>{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
