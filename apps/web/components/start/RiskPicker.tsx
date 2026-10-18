"use client";

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Block, Fields } from "@/components/start/Blocks";
import { Seg } from "@/components/start/FieldRow";
import type { BriefView } from "@/lib/brief";
import { valueOf, type BriefChange, type Open, type Save } from "@/lib/start";

const RATINGS = ["low", "medium", "high"];
type Rating = string | null;

/** The ICH M15 model risk (§2.1.5): the person rates the model's influence and the decision's consequence; the tiers
 *  those ratings admit are offered (the API's table, so the rule lives in one place); different ratings need a reason.
 *  The tier is never assumed (R0): without it the plan cannot be signed. */
export function RiskPicker({ view, save, open }: { view: BriefView; save: Save; open: Open }) {
  const stored = {
    influence: valueOf(view, "m15.influence_rating") as Rating,
    consequence: valueOf(view, "m15.consequence_rating") as Rating,
    tier: valueOf(view, "acceptance.tier") as Rating,
    why: (valueOf(view, "m15.risk_justification") as string | null) ?? "",
  };
  const [influence, setInfluence] = useState<Rating>(stored.influence);
  const [consequence, setConsequence] = useState<Rating>(stored.consequence);
  const [tier, setTier] = useState<Rating>(stored.tier);
  const [why, setWhy] = useState(stored.why);
  const [problem, setProblem] = useState<string | null>(null);

  const admitted = influence && consequence ? view.start.risk.admitted[`${influence}/${consequence}`] ?? [] : [];
  // a tier the new ratings do not admit is dropped; a single admitted tier is offered selected, for the person to save
  const draftTier = admitted.length === 1 ? admitted[0] : tier && admitted.includes(tier) ? tier : null;
  const needsWhy = admitted.length > 1;
  const changed = influence !== stored.influence || consequence !== stored.consequence || draftTier !== stored.tier
    || (needsWhy && why.trim() !== stored.why);

  async function commit() {
    const changes: BriefChange[] = [];
    const set = (path: string, before: Rating, after: Rating) => {
      if (after !== before) changes.push(after ? { path, status: "EDITED", value: after } : { path, status: "MISSING" });
    };
    set("m15.influence_rating", stored.influence, influence);
    set("m15.consequence_rating", stored.consequence, consequence);
    set("acceptance.tier", stored.tier, draftTier);
    if (needsWhy && why.trim() && why.trim() !== stored.why) {
      changes.push({ path: "m15.risk_justification", status: "EDITED", value: why.trim() });
    }
    setProblem(changes.length ? await save(changes) : null);
  }

  return (
    <Block n={3} title="Model risk (ICH M15)" testId="start-risk"
           lede="Rate how much the model weighs in the decision and what a wrong decision would mean; the tier follows from both and sets the acceptance criteria.">
      <Fields view={view} paths={["m15.influence", "m15.consequence"]} save={save} open={open}
              labels={{ "m15.influence": "How the model is used", "m15.consequence": "What a wrong decision means" }} />
      <div className="risk-grid">
        <div className="risk-row">
          <span className="sb-label">Model influence</span>
          <Seg options={RATINGS} value={influence} onPick={setInfluence} testId="risk-influence" />
        </div>
        <div className="risk-row">
          <span className="sb-label">Decision consequence</span>
          <Seg options={RATINGS} value={consequence} onPick={setConsequence} testId="risk-consequence" />
        </div>
        <div className="risk-row">
          <span className="sb-label">Model risk</span>
          {admitted.length ? (
            <Seg options={RATINGS.filter((r) => admitted.includes(r))} value={draftTier} onPick={setTier} testId="risk-tier" />
          ) : <span className="muted">rate both first</span>}
        </div>
        {needsWhy && (
          <div className="risk-row">
            <label className="sb-label" htmlFor="risk-why">Why this tier</label>
            <textarea id="risk-why" rows={2} value={why} data-testid="risk-why" onChange={(e) => setWhy(e.target.value)}
                      placeholder="Influence and consequence differ: say why the risk is the tier you chose" />
          </div>
        )}
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className="btn primary" disabled={!changed || (needsWhy && !!draftTier && !why.trim() && !stored.why)}
                data-testid="risk-save" onClick={commit}>Save the model risk</button>
        {stored.tier && <span className="muted" data-testid="risk-current">Saved: {stored.tier}</span>}
      </div>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      {view.start.risk.problems.map((p) => <InlineIssue key={p} testId="risk-problem">{p}</InlineIssue>)}
    </Block>
  );
}
