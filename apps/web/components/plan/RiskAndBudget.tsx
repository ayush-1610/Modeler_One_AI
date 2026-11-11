"use client";

// The two run settings the person signs with the MAP: the ICH M15 model risk (it decides the acceptance criteria every
// round is judged by, so it is never assumed) and the campaign's time budget (MS-01's fractions split it across the
// stages; the run follows it). Run integrity, 2026-10-18.

import { useState } from "react";

import type { Envelope } from "@/lib/api";
import { planApi, type PlanView } from "@/lib/plan";

type Risk = "low" | "medium" | "high";

export function RiskAndBudget({ projectId, view, apply }: {
  projectId: string;
  view: PlanView;
  apply: <T>(call: () => Promise<Envelope<T>>, ok?: string) => Promise<string | null>;
}) {
  const structure = view.plan.structure;
  const [risk, setRisk] = useState<Risk | "">(structure.model_risk ?? "");
  const [why, setWhy] = useState("");
  const [hours, setHours] = useState(String(structure.campaign_budget_seconds / 3600));
  const [problem, setProblem] = useState<string | null>(null);
  const riskChanged = risk !== "" && risk !== structure.model_risk;
  const budgetSeconds = Math.round(Number(hours) * 3600);
  const budgetChanged = Number.isFinite(budgetSeconds) && budgetSeconds !== structure.campaign_budget_seconds;

  return (
    <div className="row flex-wrap gap-8 mb-8" data-testid="risk-and-budget">
      <label className="muted fs-13" htmlFor="plan-risk">Model risk (ICH M15)</label>
      <select id="plan-risk" value={risk} onChange={(e) => setRisk(e.target.value as Risk | "")}
              className={structure.model_risk ? "" : "needs"}>
        <option value="">not set</option>
        <option value="low">low</option>
        <option value="medium">medium</option>
        <option value="high">high</option>
      </select>
      {riskChanged && (
        <>
          <input aria-label="Why this risk" placeholder="why: model influence and decision consequence" value={why}
                 onChange={(e) => setWhy(e.target.value)} className="flex-1 minw-200" />
          <button className="btn" disabled={!why.trim()}
                  onClick={async () => setProblem(await apply(() => planApi.structure(projectId, "model_risk", risk, why.trim()),
                                                              `Model risk set to ${risk}.`))}>Set risk</button>
        </>
      )}
      <label className="muted fs-13 ml-12" htmlFor="plan-budget">Time budget (hours)</label>
      <input id="plan-budget" type="number" min={0.25} max={48} step={0.25} value={hours}
             onChange={(e) => setHours(e.target.value)} className="w-80" />
      {budgetChanged && (
        <button className="btn"
                onClick={async () => setProblem(await apply(
                  () => planApi.structure(projectId, "campaign_budget_seconds", budgetSeconds,
                                          `campaign time budget set to ${hours} h`), `Time budget set to ${hours} h.`))}>
          Set budget</button>
      )}
      {problem && <span className="chip high">{problem}</span>}
    </div>
  );
}
