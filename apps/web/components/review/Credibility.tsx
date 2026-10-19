"use client";

// Credibility (ICH M15; redesign §3.3) and the studies' roles. The model risk is the one Start set, changed here only
// with a reason (the R0 control); the time budget is split across the stages by MS-01's fixed shares, shown as the MAP
// will sign them (D-31: no per-stage overrides, more time is a larger budget signed again); the limitations are the
// ones the MAP names. A study can be left out with a reason, and taken back.

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { RiskAndBudget } from "@/components/plan/RiskAndBudget";
import type { Envelope } from "@/lib/api";
import type { useMutation } from "@/lib/hooks";
import { ROLE_LABEL, type PlanView } from "@/lib/plan";
import { minutes, reviewApi, type ReviewPage, type ReviewStudy } from "@/lib/review";

type Apply = <T>(call: () => Promise<Envelope<T>>, ok?: string) => Promise<string | null>;
type Run = ReturnType<typeof useMutation>["run"];

export function Credibility({ projectId, view, review, apply }: {
  projectId: string; view: PlanView; review: ReviewPage; apply: Apply;
}) {
  const { risk } = review;
  return (
    <div className="credibility" data-testid="credibility">
      <section>
        <h3>The model risk</h3>
        <p className="muted credibility-lede">
          {risk.tier ? <>The MAP carries <strong>{risk.tier}</strong>{risk.set_here ? `, set here: ${risk.reason}` : ", as set at Start"}.</>
            : "Not set yet: it is never assumed, and the plan cannot be signed without it."}
          {(risk.influence || risk.consequence) && <> Start rated model influence <strong>{risk.influence ?? "—"}</strong> and
            decision consequence <strong>{risk.consequence ?? "—"}</strong>{risk.justification ? `: ${risk.justification}` : "."}</>}
        </p>
        <RiskAndBudget projectId={projectId} view={view} apply={apply} />
      </section>
      <section>
        <h3>The time budget, stage by stage</h3>
        <p className="muted credibility-lede">MS-01&apos;s fixed shares of the {minutes(review.budget_seconds)} budget, as the MAP
          signs them. A stage ends when it passes; more time means a larger budget, signed again.</p>
        <div className="table-scroll">
          <table className="stage-split" data-testid="stage-split">
            <thead><tr><th>Stage</th><th className="num">Share</th><th className="num">Time</th><th className="num">Rounds at most</th></tr></thead>
            <tbody>
              {review.stages.map((s) => (
                <tr key={s.stage} data-testid={`stage-${s.stage}`}>
                  <td>{s.stage}</td><td className="num">{Math.round(Number(s.fraction) * 100)} %</td>
                  <td className="num">{minutes(s.budget_seconds)}</td><td className="num">{s.max_rounds}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section>
        <h3>The limitations the MAP names ({review.limitations.length})</h3>
        {review.limitations.length === 0 ? <p className="muted">None.</p> : (
          <ul className="limitations" data-testid="limitations">
            {review.limitations.map((l) => <li key={l}>{l}</li>)}
          </ul>
        )}
        <p className="muted credibility-lede">They come from the MS-01 split, each study simulated with the healthy adult
          default, the assumptions the brief states, and every warning acknowledged below.</p>
      </section>
    </div>
  );
}

function LeaveOut({ study, onChange, busy }: { study: ReviewStudy; onChange: (why: string | null, reason: string) => Promise<string | null>; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  if (study.excluded) {
    return <button type="button" className="link-btn" disabled={busy}
                   onClick={async () => setProblem(await onChange(null, `${study.study_id} included again at Review`))}>Include again</button>;
  }
  if (!open) return <button type="button" className="link-btn" disabled={busy} data-testid={`leave-out-${study.study_id}`} onClick={() => setOpen(true)}>Leave out</button>;
  return (
    <span className="review-exclude">
      <input aria-label={`Why leave out ${study.study_id}`} placeholder="why (required)" value={why} onChange={(e) => setWhy(e.target.value)} />
      <button type="button" className="btn tiny" disabled={busy || !why.trim()}
              onClick={async () => { const failed = await onChange(why.trim(), why.trim()); setProblem(failed); if (!failed) setOpen(false); }}>Leave out</button>
      <button type="button" className="btn tiny" onClick={() => setOpen(false)}>Cancel</button>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </span>
  );
}

/** The studies with the role the plan gives each (changed on the canvas above, with a reason), whether it is blinded
 *  until the signature (D-15, following the S5 role), its demographics, and leaving it out. */
export function StudiesTable({ projectId, review, run, busy }: { projectId: string; review: ReviewPage; run: Run; busy: boolean }) {
  async function change(study: ReviewStudy, why: string | null, reason: string) {
    return (await run(() => reviewApi.leaveOut(projectId, study.study_id, why, reason))).problem;
  }
  return (
    <div className="table-scroll" data-testid="review-studies">
      <table>
        <thead><tr><th>Study</th><th>Role</th><th>Purpose</th><th>Origin</th><th>Demographics</th><th /></tr></thead>
        <tbody>
          {review.studies.map((s) => (
            <tr key={s.study_id} className={s.excluded ? "left-out" : ""} data-testid={`review-study-${s.study_id}`}>
              <td><code>{s.study_id}</code>{s.blinded && <span className="chip neutral" title="its values are hidden until the MAP is signed (D-15)"> blinded</span>}</td>
              <td>{s.excluded ? <span className="muted">left out: {s.excluded}</span> : s.role ? ROLE_LABEL[s.role] : "—"}
                {s.role_by && s.role_by !== "default" && !s.excluded && <span className="muted"> · set by {s.role_by}</span>}</td>
              <td>{s.purpose?.replace(/_/g, " ") ?? "—"}</td>
              <td>{s.origin?.toLowerCase().replace(/_/g, " ") ?? "—"}</td>
              <td>{s.demographics === "default" ? "healthy adult default" : s.demographics}</td>
              <td><LeaveOut study={s} busy={busy} onChange={(why, reason) => change(s, why, reason)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
