"use client";

// The review table (redesign §3.3, map row m-exclude): every model input with its value, the source the CPF keeps and
// its quote, grade and flags, who or what supplied it, and a confidence that is display only. Filters narrow it; a
// value can be set aside with a reason, and the next source takes its place. Conflicts, held values and missing inputs
// are settled in Inputs, where the person keeps one or checks it.

import Link from "next/link";
import { useState } from "react";

import { EmptyState, InlineIssue } from "@/components/kit";
import type { useMutation } from "@/lib/hooks";
import {
  CONFIDENCE_CHIP, FILTERS, matches, reviewApi, STATE_LABEL, type Filter, type ReviewPage, type ReviewRow,
} from "@/lib/review";

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

export function ReviewTable({ projectId, review, run, busy }: { projectId: string; review: ReviewPage; run: Run; busy: boolean }) {
  const [filter, setFilter] = useState<Filter>("all");
  const rows = review.rows.filter((r) => matches(r, filter));
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
              <tr><th>Input</th><th className="num">Value</th><th>Source and quote</th><th>Grade</th><th>Supplied by</th>
                <th>Confidence</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const state = STATE_LABEL[r.state];
                return (
                  <tr key={r.id} data-testid={`review-row-${r.id}`} className={r.state === "kept" ? "" : "waiting"}>
                    <td>
                      <code>{r.id}</code>
                      {r.state !== "kept" && <div><span className={`chip ${state.chip}`}>{state.label}</span></div>}
                      {r.message && <div className="muted review-note">{r.message}</div>}
                    </td>
                    <td className="num">{value(r)}</td>
                    <td className="review-source">
                      <div>{where(r)}</div>
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
      <p className="muted review-hint">Confidence is shown, not used: it sums up the grade, the flags and how many other
        sources agree. The value each input takes is chosen by the source-selection rule (D-32).</p>
    </div>
  );
}
