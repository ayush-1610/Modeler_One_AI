"use client";

// The review table (redesign §3.3, map row m-exclude): every model input with its value, the source the CPF keeps and
// its quote, grade and flags, who or what supplied it, and a confidence that is display only. Filters narrow it; a
// value can be set aside with a reason, and the next source takes its place. Conflicts, held values and missing inputs
// are settled in Inputs, where the person keeps one or checks it.

import Link from "next/link";
import { useState } from "react";

import { EmptyState, InlineIssue } from "@/components/kit";
import { SortHeader, TableMore } from "@/components/kit/SortableTable";
import { PeekButton } from "@/components/kit/SourcePeek";
import type { useMutation } from "@/lib/hooks";
import {
  CONFIDENCE_CHIP, FILTERS, matches, reviewApi, STATE_LABEL, type Filter, type ReviewPage, type ReviewRow,
} from "@/lib/review";
import { numericKey, ordinal, useTableView } from "@/lib/tableView";

type Run = ReturnType<typeof useMutation>["run"];

function value(row: ReviewRow): string {
  if (row.value === null || row.value === undefined) return "—";
  const v = typeof row.value === "number" ? String(+row.value.toPrecision(4)) : String(row.value);
  return row.unit ? `${v} ${row.unit}` : v;
}

function where(row: ReviewRow): string {
  const s = row.source;
  if (!s) return "—";
  const what = [s.title || s.type.toLowerCase().replace(/_/g, " "), s.year, s.locator].filter(Boolean).join(" · ");
  return s.page ? `${what} · p.${s.page}` : what;
}

function Exclude({ row, onExclude, busy }: { row: ReviewRow; onExclude: (reason: string) => Promise<string | null>; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  if (!row.evidence_id) return null;
  if (!open) {
    return <button type="button" className="link-btn" disabled={busy} data-testid={`exclude-${row.id}`}
                   onClick={() => setOpen(true)}>Exclude</button>;
  }
  const only = row.agreeing === 0 && row.alternatives === 0;
  return (
    <span className="review-exclude">
      {only && <InlineIssue testId={`exclude-only-${row.id}`}>This is its only source: the input will wait for a value in
        Inputs, and the plan until then.</InlineIssue>}
      <input aria-label={`Why exclude ${row.id}`} placeholder="why (required)" value={reason}
             data-testid={`exclude-reason-${row.id}`} onChange={(e) => setReason(e.target.value)} />
      <button type="button" className="btn tiny" disabled={busy || !reason.trim()} data-testid={`exclude-confirm-${row.id}`}
              onClick={async () => { const failed = await onExclude(reason.trim()); setProblem(failed); if (!failed) setOpen(false); }}>
        Exclude</button>
      <button type="button" className="btn tiny" onClick={() => setOpen(false)}>Cancel</button>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </span>
  );
}

// sortable by its heads, 25 rows at a time (the 2026-11-11 audit, item 11); an input that waits on a person (a conflict,
// a held value, a missing input) is never paged or hidden by the text filter; a pressed chip narrows it too
const confidenceOrder = ordinal(["high", "medium", "low"]);
const REVIEW_KEYS = {
  input: (r: ReviewRow) => r.id, value: (r: ReviewRow) => numericKey(r.value), source: (r: ReviewRow) => where(r),
  grade: (r: ReviewRow) => r.grade ?? null, by: (r: ReviewRow) => r.supplied_by ?? null,
  confidence: (r: ReviewRow) => confidenceOrder(r.confidence ?? null),
};

export function ReviewTable({ projectId, review, run, busy }: { projectId: string; review: ReviewPage; run: Run; busy: boolean }) {
  const [filter, setFilter] = useState<Filter>("all");
  // a row the person has typed in (an exclusion reason) stays shown, so its text is not lost; it is not counted as
  // needing attention, and focus alone (tabbing through) does not pin it. On the bubbling input event: an update from a
  // capture-phase handler would put the controlled field back to its old value before the field's own onChange runs
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set());
  const view = useTableView({
    rows: review.rows, keys: REVIEW_KEYS, pageSize: 25, filter: (r) => matches(r, filter), filterKey: filter,
    keep: (r) => r.state !== "kept", pin: (r) => touched.has(r.id),
  });
  const rows = view.visible;
  const touch = (id: string) => { if (!touched.has(id)) setTouched(new Set([...touched, id])); };
  const count: Record<Filter, number> = review.counts;

  async function exclude(row: ReviewRow, reason: string): Promise<string | null> {
    return (await run(() => reviewApi.exclude(projectId, row.evidence_id as string, reason))).problem;
  }

  return (
    <div className="review-table" data-testid="review-table">
      <div className="review-filters" role="group" aria-label="Show">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" aria-pressed={filter === f.id} data-testid={`review-filter-${f.id}`}
                  onClick={() => setFilter(f.id)}>{f.label} <span className="count">{count[f.id]}</span></button>
        ))}
      </div>
      {review.counts.open > 0 && (
        <InlineIssue>
          {review.counts.open} input{review.counts.open === 1 ? "" : "s"} still wait{review.counts.open === 1 ? "s" : ""} on a
          person: keep one, check it or give a value in <Link href={`/projects/${projectId}/inputs`}>Inputs</Link>.
        </InlineIssue>
      )}
      {rows.length === 0 ? <EmptyState title="Nothing here">No input matches this filter.</EmptyState> : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr><SortHeader view={view} col="input" label="Input" /><SortHeader view={view} col="value" label="Value" numeric />
                <SortHeader view={view} col="source" label="Source and quote" /><SortHeader view={view} col="grade" label="Grade" />
                <SortHeader view={view} col="by" label="Supplied by" /><SortHeader view={view} col="confidence" label="Confidence" /><th /></tr>
            </thead>
            <tbody className="paged-rows">
              {rows.map((r) => {
                const state = STATE_LABEL[r.state];
                return (
                  <tr key={r.id} data-testid={`review-row-${r.id}`} className={r.state === "kept" ? "" : "waiting"}
                      onInput={() => touch(r.id)}>
                    <td>
                      <code>{r.id}</code>
                      {r.state !== "kept" && <div><span className={`chip ${state.chip}`}>{state.label}</span></div>}
                      {r.message && <div className="muted review-note">{r.message}</div>}
                    </td>
                    <td className="num">{value(r)}</td>
                    <td className="review-source">
                      <div className="review-source-head">
                        <span>{where(r)}</span>
                        <PeekButton projectId={projectId} source={r.source ? { ...r.source, quote: r.quote } : null}
                                    label={r.id} testId={`peek-${r.id}`} />
                      </div>
                      {r.quote && <q title={r.quote}>{r.quote.length > 140 ? `${r.quote.slice(0, 137)}…` : r.quote}</q>}
                      {(r.agreeing > 0 || r.alternatives > 0) && (
                        <div className="muted review-note">
                          {r.agreeing > 0 && `${r.agreeing} other source${r.agreeing === 1 ? " agrees" : "s agree"}`}
                          {r.agreeing > 0 && r.alternatives > 0 && " · "}
                          {r.alternatives > 0 && `${r.alternatives} alternative${r.alternatives === 1 ? "" : "s"}`}
                        </div>
                      )}
                      {r.flags.map((f) => <div key={f} className="review-flag">{f}</div>)}
                    </td>
                    <td>{r.grade ?? "—"}</td>
                    <td>{r.supplied_by ?? "—"}{r.changed_by_person && r.supplied_by !== "person" ? " · changed by a person" : ""}</td>
                    <td>{r.confidence ? <span className={`chip ${CONFIDENCE_CHIP[r.confidence]}`}>{r.confidence}</span> : "—"}</td>
                    <td><Exclude row={r} busy={busy} onExclude={(reason) => exclude(r, reason)} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <TableMore view={view} noun="inputs" testId="review-more" />
      <p className="muted review-hint">Confidence is shown, not used: it sums up the grade, the flags and how many other
        sources agree. The value each input takes is chosen by the source-selection rule.</p>
    </div>
  );
}
