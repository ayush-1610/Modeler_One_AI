"use client";

// The estimation plan (redesign §3.3, map rows p5-fit and m-bounds; D-34): every numeric parameter, fixed or estimated,
// with its start value and source, the stages MS-01 lets it be fitted at, the bounds MS-01 §2.2 proposes (a provisional
// data rule, UNVERIFIED until the SME signs) and what the validator says of a fit's bounds. Estimating a parameter is the
// person's choice, with a reason; the proposal only fills the form. Every other MS-01 candidate may be fitted by the
// diagnosis within MS-01's own default unless the person keeps it fixed, with a reason (D-37). Estimated parameters
// can be fitted as one, through one factor that keeps their split (PI-4 B2): the person says why, and where the split
// comes from; both are signed with the MAP.

import { Fragment, useState } from "react";

import { EmptyState, InlineIssue } from "@/components/kit";
import type { Envelope, Schema } from "@/lib/api";
import { planApi } from "@/lib/plan";
import type { ReviewPage } from "@/lib/review";

type Row = Schema<"EstimationRow">;
type Group = Schema<"FitGroupRow">;
type Apply = <T>(call: () => Promise<Envelope<T>>, ok?: string) => Promise<string | null>;
type Filter = "all" | "estimated" | "diagnosis" | "candidates" | "flagged";

const FILTERS: { id: Filter; label: string; keep: (r: Row) => boolean }[] = [
  { id: "all", label: "All", keep: () => true },
  { id: "estimated", label: "Estimated", keep: (r) => r.estimated !== null },
  { id: "diagnosis", label: "The diagnosis may fit", keep: (r) => r.diagnosis_may_fit !== null },
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

/** A change that needs a reason: one link opens the reason and its button. */
function WithReason({ testId, label, ask, button, onDo }: {
  testId: string; label: string; ask: string; button: string; onDo: (reason: string) => Promise<string | null>;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (!open) return <button type="button" className="link-btn" onClick={() => setOpen(true)} data-testid={testId}>{label}</button>;
  return (
    <span className="review-exclude">
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={`${ask} (required)`} aria-label={ask} />
      <button type="button" className="btn tiny" disabled={!reason.trim()} onClick={async () => { if (!(await onDo(reason.trim()))) setOpen(false); }}>
        {button}</button>
      <button type="button" className="btn tiny" onClick={() => setOpen(false)}>Cancel</button>
    </span>
  );
}

/** Estimated parameters fitted as one (PI-4 B2): each at f x its start value, so their split is kept and the data
 * estimate only the factor f ("Use as Factor" in the OSP desktop). */
function GroupForm({ estimated, onSave, onClose }: {
  estimated: Row[]; onSave: (name: string, group: Schema<"GroupRequest">) => Promise<string | null>; onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [lower, setLower] = useState("0.1");
  const [upper, setUpper] = useState("10");
  const [scale, setScale] = useState<"linear" | "log">("log");
  const [splitSource, setSplitSource] = useState("");
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const ready = /^[A-Za-z][A-Za-z0-9_.-]*$/.test(name) && members.length >= 2 && splitSource.trim() && reason.trim()
    && lower.trim() !== "" && upper.trim() !== "";
  return (
    <div className="estimate-form" data-testid="group-form">
      <p className="muted estimate-hint">
        Each member is simulated at the factor times its start value, so their split is kept and the data estimate only
        the factor (1 is the start values). Use it for parallel pathways the data cannot tell apart.
      </p>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        {estimated.map((r) => (
          <label key={r.id} className="estimate-stage">
            <input type="checkbox" checked={members.includes(r.id)} aria-label={`fit ${r.id} in the group`}
                   data-testid={`group-member-${r.id}`}
                   onChange={(e) => setMembers(e.target.checked ? [...members, r.id] : members.filter((m) => m !== r.id))} />
            <code>{r.id}</code>
          </label>
        ))}
      </div>
      <div className="row" style={{ gap: 8, marginTop: 6 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="group name, e.g. hepatic"
               aria-label="group name" data-testid="group-name" />
        <select value={scale} onChange={(e) => setScale(e.target.value as "linear" | "log")} aria-label="scale of the factor">
          <option value="log">log</option><option value="linear">linear</option>
        </select>
        <input value={lower} onChange={(e) => setLower(e.target.value)} aria-label="lower bound of the factor" placeholder="lower" />
        <input value={upper} onChange={(e) => setUpper(e.target.value)} aria-label="upper bound of the factor" placeholder="upper" />
      </div>
      <div className="row" style={{ gap: 8, marginTop: 6 }}>
        <input value={splitSource} onChange={(e) => setSplitSource(e.target.value)} style={{ flex: 1, minWidth: 220 }}
               placeholder="where the split comes from, e.g. in vitro fm, HLM (Author 2020) (required)"
               aria-label="where the split comes from" data-testid="group-split-source" />
      </div>
      <div className="row" style={{ gap: 8, marginTop: 6 }}>
        <input value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1, minWidth: 220 }}
               placeholder="why fit them as one (required)" aria-label="why fit them as one" data-testid="group-reason" />
        <button type="button" className="btn tiny primary" disabled={!ready} data-testid="group-save"
                onClick={async () => {
                  const failed = await onSave(name, { members, lower: Number(lower), upper: Number(upper), scale,
                                                      split_source: splitSource.trim(), reason: reason.trim() });
                  setProblem(failed);
                  if (!failed) onClose();
                }}>Fit as one</button>
        <button type="button" className="btn tiny" onClick={onClose}>Cancel</button>
      </div>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </div>
  );
}

function Groups({ projectId, groups, estimated, apply }: {
  projectId: string; groups: Group[]; estimated: Row[]; apply: Apply;
}) {
  const [adding, setAdding] = useState(false);
  return (
    <div className="estimation-groups" data-testid="fit-groups">
      <h4>Fitted as one</h4>
      {groups.length === 0 && <p className="muted review-note">No group: each estimated parameter is fitted on its own.</p>}
      {groups.map((g) => (
        <div key={g.name} className="review-note" data-testid={`fit-group-${g.name}`}>
          <span className="chip brand">{g.name}</span> {g.members.map((m) => <code key={m}>{m} </code>)}
          · factor {bounds(g.lower, g.upper, g.scale)}
          <div className="muted">Split from: {g.split_source}</div>
          <div className="muted">Why: {g.reason} ({g.by})</div>
          <WithReason testId={`ungroup-${g.name}`} label="Fit them each on its own" ask={`why fit ${g.name}'s members each on its own`}
                      button="Ungroup" onDo={(reason) => apply(() => planApi.ungroup(projectId, g.name, reason),
                        `${g.name}: its members are fitted each on its own.`)} />
        </div>
      ))}
      {adding ? <GroupForm estimated={estimated} onClose={() => setAdding(false)}
                           onSave={(name, group) => apply(() => planApi.group(projectId, name, group),
                             `${group.members.join(", ")} fitted as one (${name}).`)} />
        : estimated.length >= 2 && (
          <button type="button" className="link-btn" onClick={() => setAdding(true)} data-testid="group-add">
            Fit estimated parameters as one…</button>
        )}
    </div>
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
                      {r.group && <span className="chip brand" data-testid={`grouped-${r.id}`}> as one with {r.group}</span>}
                      <div className="review-note">{bounds(r.estimated.lower, r.estimated.upper, r.estimated.scale)}</div>
                      <div className="muted review-note">{r.estimated.reason}</div>
                    </> : r.diagnosis_may_fit ? <>
                      <span className="chip brand" data-testid={`diagnosis-may-fit-${r.id}`}>the diagnosis may fit it in {r.diagnosis_may_fit.stages.join(", ")}</span>
                      <div className="review-note">{bounds(r.diagnosis_may_fit.lower, r.diagnosis_may_fit.upper, r.diagnosis_may_fit.scale)}</div>
                      <div className="muted review-note">MS-01&apos;s default</div>
                    </> : r.held_fixed ? <>
                      <span className="chip neutral" data-testid={`held-fixed-${r.id}`}>held fixed</span>
                      <div className="muted review-note">{r.held_fixed.reason}</div>
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
                    {editing !== r.id && (r.estimated || r.diagnosis_may_fit) && (
                      // an MS-01 candidate is held fixed (else the diagnosis could fit it within MS-01's default); another
                      // parameter only loses the person's fit
                      <> · <WithReason testId={`fix-${r.id}`} label={r.estimated ? "Fix it" : "Keep fixed"} ask={`why keep ${r.id} fixed`}
                                       button="Fix"
                                       onDo={(reason) => apply(() => r.candidate_at.length ? planApi.hold(projectId, r.id, reason)
                                         : planApi.unfit(projectId, r.id, reason), `${r.id} fixed.`)} /></>
                    )}
                    {editing !== r.id && r.held_fixed && (
                      <> · <WithReason testId={`release-${r.id}`} label="Let the diagnosis fit it" ask={`why let the diagnosis fit ${r.id}`}
                                       button="Let it" onDo={(reason) => apply(() => planApi.release(projectId, r.id, reason),
                                         `The diagnosis may fit ${r.id} within MS-01's default.`)} /></>
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
      <Groups projectId={projectId} groups={review.fit_groups} estimated={rows.filter((r) => r.estimated !== null)} apply={apply} />
      <p className="muted review-hint">Proposed bounds follow MS-01&apos;s default bounds ({rule.source}, data rule v{rule.version},{" "}
        {rule.status === "UNVERIFIED" ? "provisional until the SME signs" : rule.status}): relative ones around the start value,
        absolute ones only in MS-01&apos;s unit, each kept within the registry&apos;s physical bounds. The MAP may narrow them;
        wider bounds are said and acknowledged. A parameter MS-01 gives no default for gets 0.1–10× its start value.
        An MS-01 candidate you neither estimate nor keep fixed may be fitted by the diagnosis at its stages, within MS-01&apos;s
        own default; the signed MAP lists each one.</p>
    </div>
  );
}
