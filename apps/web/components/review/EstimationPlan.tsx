"use client";

// The estimation plan (redesign §3.3, map rows p5-fit and m-bounds; D-34): every numeric parameter, fixed or estimated,
// with its start value and source, the stages MS-01 lets it be fitted at, the bounds MS-01 §2.2 proposes (a provisional
// data rule, UNVERIFIED until the SME signs) and what the validator says of a fit's bounds. Estimating a parameter is the
// person's choice, with a reason; the proposal only fills the form.

import { Fragment, useState } from "react";

import { EmptyState, InlineIssue } from "@/components/kit";
import type { Envelope, Schema } from "@/lib/api";
import { planApi } from "@/lib/plan";
import type { ReviewPage } from "@/lib/review";

type Row = Schema<"EstimationRow">;
type Apply = <T>(call: () => Promise<Envelope<T>>, ok?: string) => Promise<string | null>;
type Filter = "all" | "estimated" | "candidates" | "flagged";

const FILTERS: { id: Filter; label: string; keep: (r: Row) => boolean }[] = [
  { id: "all", label: "All", keep: () => true },
  { id: "estimated", label: "Estimated", keep: (r) => r.estimated !== null },
  { id: "candidates", label: "MS-01 candidates", keep: (r) => r.candidate_at.length > 0 },
  { id: "flagged", label: "Flagged", keep: (r) => r.findings.length > 0 },
];

const num = (x: number) => String(+x.toPrecision(4));
// what the CPF says of the start value (FIXED there means measured or known, not "not estimated")
const START: Record<string, string> = { FIXED: "measured", PREDICTED: "predicted", DERIVED: "derived", FITTED: "fitted before" };

function bounds(lower: number | null, upper: number | null, scale: string | null): string {
  return lower === null || upper === null ? "—" : `[${num(lower)}, ${num(upper)}] ${scale ?? ""}`.trim();
}

function EstimateForm({ row, onSave, onClose }: {
  row: Row; onSave: (fit: Schema<"FitRequest">) => Promise<string | null>; onClose: () => void;
}) {
  const proposal = row.proposal;
  const fit = row.estimated;
  const [stages, setStages] = useState<string[]>(fit?.stages ?? (row.candidate_at.length ? [row.candidate_at[0]] : ["S1"]));
  const [lower, setLower] = useState(String(fit?.lower ?? proposal.lower ?? ""));
  const [upper, setUpper] = useState(String(fit?.upper ?? proposal.upper ?? ""));
  const [scale, setScale] = useState<"linear" | "log">(fit?.scale ?? proposal.scale ?? "log");
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const useProposal = () => {
    if (proposal.lower === null || proposal.upper === null) return;
    setLower(String(proposal.lower));
    setUpper(String(proposal.upper));
    setScale(proposal.scale ?? "log");
  };
  return (
    <div className="estimate-form" data-testid={`estimate-form-${row.id}`}>
      <div className="row" style={{ gap: 8 }}>
        {["S1", "S2", "S3"].map((st) => (
          <label key={st} className="estimate-stage">
            <input type="checkbox" checked={stages.includes(st)} aria-label={`estimate ${row.id} in ${st}`}
                   onChange={(e) => setStages(e.target.checked ? [...stages, st] : stages.filter((x) => x !== st))} />
            {st}{row.candidate_at.includes(st) ? "" : "*"}
          </label>
        ))}
        <select value={scale} onChange={(e) => setScale(e.target.value as "linear" | "log")} aria-label={`scale of ${row.id}`}>
          <option value="log">log</option><option value="linear">linear</option>
        </select>
        <input value={lower} onChange={(e) => setLower(e.target.value)} aria-label={`lower bound of ${row.id}`} placeholder="lower" />
        <input value={upper} onChange={(e) => setUpper(e.target.value)} aria-label={`upper bound of ${row.id}`} placeholder="upper" />
        {proposal.lower !== null && (
          <button type="button" className="link-btn" onClick={useProposal} data-testid={`use-proposal-${row.id}`}>
            Use the proposed bounds</button>
        )}
      </div>
      <div className="row" style={{ gap: 8, marginTop: 6 }}>
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="why estimate it (required)"
               aria-label={`why estimate ${row.id}`} style={{ flex: 1, minWidth: 220 }} />
        <button type="button" className="btn tiny primary" data-testid={`estimate-save-${row.id}`}
                disabled={!reason.trim() || !stages.length || lower.trim() === "" || upper.trim() === ""}
                onClick={async () => {
                  const failed = await onSave({ stages, lower: Number(lower), upper: Number(upper), scale, reason: reason.trim() });
                  setProblem(failed);
                  if (!failed) onClose();
                }}>Save</button>
        <button type="button" className="btn tiny" onClick={onClose}>Cancel</button>
      </div>
      <p className="muted estimate-hint">* not an MS-01 candidate at that stage (the validator says so)</p>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </div>
  );
}

function FixAgain({ row, onFix }: { row: Row; onFix: (reason: string) => Promise<string | null> }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (!open) return <button type="button" className="link-btn" onClick={() => setOpen(true)} data-testid={`fix-${row.id}`}>Fix it</button>;
  return (
    <span className="review-exclude">
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="why fix it (required)" aria-label={`why fix ${row.id}`} />
      <button type="button" className="btn tiny" disabled={!reason.trim()} onClick={async () => { if (!(await onFix(reason.trim()))) setOpen(false); }}>
        Fix</button>
      <button type="button" className="btn tiny" onClick={() => setOpen(false)}>Cancel</button>
    </span>
  );
}

export function EstimationPlan({ projectId, review, apply }: { projectId: string; review: ReviewPage; apply: Apply }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [editing, setEditing] = useState<string | null>(null);
  const rows = review.estimation;
  const shown = rows.filter(FILTERS.find((f) => f.id === filter)!.keep);
  const rule = review.bounds_rule;
  return (
    <div className="estimation-plan" data-testid="estimation-plan">
      <div className="review-filters" role="group" aria-label="Filter the estimation plan">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}
                  data-testid={`estimation-filter-${f.id}`}>
            {f.label} <span className="count">{rows.filter(f.keep).length}</span>
          </button>
        ))}
      </div>
      {shown.length === 0 ? <EmptyState title="No parameter matches this filter">Choose another filter.</EmptyState> : (
        <div className="table-scroll">
          <table className="review-table estimation-table">
            <thead><tr><th>Parameter</th><th>Start value</th><th>Source</th><th>Fixed or estimated</th><th>Proposed bounds</th><th /></tr></thead>
            <tbody>
              {shown.map((r) => (
                <Fragment key={r.id}>
                <tr data-testid={`estimation-row-${r.id}`} className={r.findings.some((f) => f.severity === "error") ? "waiting" : ""}>
                  <td><code>{r.id}</code>
                    {r.candidate_at.length > 0 && <div className="muted review-note">MS-01 candidate at {r.candidate_at.join(", ")}</div>}</td>
                  <td>{num(Number(r.value))}{r.unit ? ` ${r.unit}` : ""}
                    <div className="muted review-note">{START[r.status] ?? r.status.toLowerCase()}</div></td>
                  <td className="review-source">{r.source ?? "—"}{r.grade && <span className="muted"> · grade {r.grade}</span>}</td>
                  <td>
                    {r.estimated ? <>
                      <span className="chip brand">estimated in {r.estimated.stages.join(", ")}</span>
                      <div className="review-note">{bounds(r.estimated.lower, r.estimated.upper, r.estimated.scale)}</div>
                      <div className="muted review-note">{r.estimated.reason}</div>
                    </> : <span className="chip neutral">fixed</span>}
                    {r.findings.map((f) => (
                      <div key={f.rule} className={f.severity === "error" ? "review-flag error" : "review-flag"} data-testid={`finding-${r.id}-${f.rule}`}>
                        {f.message}</div>
                    ))}
                  </td>
                  <td data-testid={`proposal-${r.id}`}>
                    {r.proposal.fixed ? <span className="chip medium" title={r.proposal.note}>MS-01: fixed</span>
                      : <>{bounds(r.proposal.lower, r.proposal.upper, r.proposal.scale)}</>}
                    <div className="muted review-note">{r.proposal.basis}</div>
                    {r.proposal.note && !r.proposal.fixed && <div className="muted review-note">{r.proposal.note}</div>}
                  </td>
                  <td className="num">
                    {editing === r.id ? null : (
                      <button type="button" className="link-btn" onClick={() => setEditing(r.id)} data-testid={`estimate-${r.id}`}>
                        {r.estimated ? "Change" : "Estimate"}</button>
                    )}
                    {r.estimated && editing !== r.id && (
                      <> · <FixAgain row={r} onFix={(reason) => apply(() => planApi.unfit(projectId, r.id, reason), `${r.id} fixed again.`)} /></>
                    )}
                  </td>
                </tr>
                {editing === r.id && (
                  <tr className="estimate-row"><td colSpan={6}>
                    <EstimateForm row={r} onClose={() => setEditing(null)}
                                  onSave={(fit) => apply(() => planApi.fit(projectId, r.id, fit), `${r.id} estimated in ${fit.stages.join(", ")}.`)} />
                  </td></tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted review-hint">Proposed bounds follow MS-01 §2.2&apos;s default bounds ({rule.source}, data rule v{rule.version},{" "}
        {rule.status === "UNVERIFIED" ? "provisional until the SME signs" : rule.status}): relative ones around the start value,
        absolute ones only in MS-01&apos;s unit, each kept within the registry&apos;s physical bounds. The MAP may narrow them;
        wider bounds are said and acknowledged. A parameter MS-01 gives no default for gets 0.1–10× its start value.</p>
    </div>
  );
}
