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
import { planApi, ROLE_LABEL, type PlanView } from "@/lib/plan";
import { minutes, reviewApi, type ReviewPage, type ReviewStudy } from "@/lib/review";

type Apply = <T>(call: () => Promise<Envelope<T>>, ok?: string) => Promise<string | null>;
type Run = ReturnType<typeof useMutation>["run"];

/** The limits every round is judged by at the chosen tier, as the MAP records them (the ruleset, provisional until the
 *  SME signs), and a stricter internal target: MS-01 §8 allows a project to judge more strictly than its tier, never
 *  more loosely. The MAP records the target, and the verdicts apply it to the internal groups' AUC and Cmax (S1–S4). */
function AcceptanceCriteria({ projectId, review, apply }: { projectId: string; review: ReviewPage; apply: Apply }) {
  const a = review.acceptance;
  const [target, setTarget] = useState(a.internal_target_pe === null ? "" : String(a.internal_target_pe));
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const limit = (c: (typeof a.pk_parameters)[number]) =>
    c.max_fold !== null ? `within ${c.max_fold}-fold` : c.guest_delta !== null ? `Guest et al. limits, δ = ${c.guest_delta}` : "—";
  return (
    <section data-testid="acceptance-criteria">
      <h3>The acceptance criteria <span className="chip medium" title={`ruleset ${a.ruleset}`}>provisional (SME)</span></h3>
      {!a.tier ? <p className="muted credibility-lede">No tier yet: the criteria follow the model risk, which is never assumed.</p> : <>
        <p className="muted credibility-lede">At the <strong>{a.tier}</strong> tier ({a.description}), every round is judged by
          these limits; at least {Math.round(Number(a.min_fraction_within) * 100)} % of the comparisons in each group must fall
          within them. Ruleset {a.ruleset}, {a.status === "UNVERIFIED" ? "UNVERIFIED until the SME signs" : a.status}.</p>
        <div className="table-scroll">
          <table className="stage-split">
            <thead><tr><th>Quantity</th><th>Limit</th><th>Source</th></tr></thead>
            <tbody>
              {[...a.pk_parameters, ...a.ddi_ratios].map((c) => (
                <tr key={c.quantity} data-testid={`criterion-${c.quantity}`}>
                  <td>{c.quantity}</td><td className="nowrap">{limit(c)}</td><td className="muted">{c.citation ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>}
      <div className="internal-target" data-testid="internal-target">
        <strong>Internal target</strong>{" "}
        {a.internal_target_pe !== null
          ? <>|prediction error| ≤ {a.internal_target_pe} %{a.target_set_here ? ", set here" : ", from the brief"}.</>
          : "none: the tier's limits apply."}
        {a.loosest_target_pe !== null && <span className="muted"> A target may be stricter than the tier, at most {a.loosest_target_pe} % here.</span>}
        <div className="row" style={{ gap: 6, marginTop: 6 }}>
          <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="% (empty: none)" aria-label="internal target, %"
                 data-testid="target-input" style={{ width: 110 }} />
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="why (required)" aria-label="why this target"
                 data-testid="target-reason" style={{ flex: 1, minWidth: 180 }} />
          <button type="button" className="btn tiny" disabled={!reason.trim()} data-testid="target-save"
                  onClick={async () => {
                    const value = target.trim() === "" ? null : Number(target);
                    const failed = await apply(() => planApi.structure(projectId, "internal_target_pe", value, reason.trim()),
                                               value === null ? "No internal target." : `Internal target ${value} %.`);
                    setProblem(failed);
                    if (!failed) setReason("");
                  }}>Set</button>
        </div>
        {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
        <p className="muted credibility-lede" style={{ marginTop: 6 }} data-testid="target-applied">The MAP records it, and every
          round judges the internal groups&apos; AUC and Cmax (S1–S4) by it on top of the tier&apos;s limit; external
          validation (S5) is judged by the tier alone (MS-01 §8).</p>
      </div>
    </section>
  );
}

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
        {(risk.influence_text || risk.consequence_text) && (
          <dl className="m15-why" data-testid="credibility-m15-why">
            {risk.influence_text && <><dt>How the model is used</dt><dd>{risk.influence_text}</dd></>}
            {risk.consequence_text && <><dt>What a wrong decision means</dt><dd>{risk.consequence_text}</dd></>}
          </dl>
        )}
        <RiskAndBudget projectId={projectId} view={view} apply={apply} />
      </section>
      <AcceptanceCriteria projectId={projectId} review={review} apply={apply} />
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
