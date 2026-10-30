"use client";

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Block, Fields } from "@/components/start/Blocks";
import { NeedsYou, Seg } from "@/components/start/FieldRow";
import type { BriefView } from "@/lib/brief";
import { recordOf, valueOf, type BriefChange, type Marks, type Open, type Save } from "@/lib/start";

const RATINGS = ["low", "medium", "high"];
type Rating = string | null;

/** The internal target (MS-01 §8): a stricter |prediction error| the internal comparisons must also meet, never looser
 *  than the tier. An acceptance criterion, so it sits under the tier (page review 1), not in the notes. */
function InternalTarget({ view, save, marks, tier }: { view: BriefView; save: Save; marks: Marks; tier: Rating }) {
  const path = "acceptance.internal_target_pe";
  const stored = valueOf(view, path) as number | null;
  const [text, setText] = useState(stored == null ? "" : String(stored));
  const [problem, setProblem] = useState<string | null>(null);
  const widest = tier ? view.start.risk.target_max[tier] : null;
  const changed = text.trim() !== (stored == null ? "" : String(stored));

  async function commit() {
    const change: BriefChange = text.trim() ? { path, status: "EDITED", value: Number(text) } : { path, status: "MISSING" };
    setProblem(await save([change]));
  }

  return (
    <div className={`risk-row${marks.issues(path).length ? " needs-you" : ""}`} data-testid="risk-target">
      <label className="sb-label" htmlFor="risk-target-input">Internal target (optional)</label>
      <div className="sb-value">
        <div className="row" style={{ gap: 6, alignItems: "center" }}>
          <span className="muted">|prediction error| at most</span>
          <input id="risk-target-input" type="number" min={0} step="any" value={text} style={{ width: 90 }}
                 data-testid="risk-target-input" onChange={(e) => setText(e.target.value)} />
          <span className="muted">%</span>
          <button type="button" className="btn" disabled={!changed} data-testid="risk-target-save" onClick={commit}>Save</button>
        </div>
        <span className="muted" style={{ fontSize: 12.5 }}>
          Applied to the internal AUC and Cmax comparisons (S1–S4), on top of the tier
          {widest != null ? `; at most ${widest} % at the ${tier} tier.` : "; rate the tier first."}
        </span>
        {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
        <NeedsYou issues={marks.issues(path)} />
      </div>
    </div>
  );
}

/** A rating the intake agent suggested (DRAFTED): a starting point only, never the rating. */
function suggestion(view: BriefView, path: string): Rating {
  const record = recordOf(view, path);
  return record.status === "DRAFTED" ? (record.value as Rating) : null;
}

/** What the intake agent suggested for a rating no person has saved yet. */
function Suggested({ stored, suggested, testId }: { stored: Rating; suggested: Rating; testId: string }) {
  if (stored || !suggested) return null;
  return <span className="muted" style={{ fontSize: 12.5 }} data-testid={testId}>suggested by the intake agent: {suggested};
    it counts once you save it</span>;
}

/** The ICH M15 model risk (§2.1.5): the person rates the model's influence and the decision's consequence; the tiers
 *  those ratings admit are offered (the API's table, so the rule lives in one place); different ratings need a reason.
 *  The tier is never assumed (R0): without it the plan cannot be signed. The intake agent's suggested ratings are
 *  preselected, and count only once the person saves them; why each rating is what it is sits under the ratings, the
 *  agent's draft confirmed or changed in place (page review 1, decisions 1b and 4). The tier's acceptance criteria are
 *  shown beside it, and the internal target under it. */
export function RiskPicker({ view, save, open, marks }: { view: BriefView; save: Save; open: Open; marks: Marks }) {
  const stored = {
    influence: valueOf(view, "m15.influence_rating") as Rating,
    consequence: valueOf(view, "m15.consequence_rating") as Rating,
    tier: valueOf(view, "acceptance.tier") as Rating,
    why: (valueOf(view, "m15.risk_justification") as string | null) ?? "",
  };
  const suggested = { influence: suggestion(view, "m15.influence_suggested"), consequence: suggestion(view, "m15.consequence_suggested") };
  const [influence, setInfluence] = useState<Rating>(stored.influence ?? suggested.influence);
  const [consequence, setConsequence] = useState<Rating>(stored.consequence ?? suggested.consequence);
  const [tier, setTier] = useState<Rating>(stored.tier);
  const [why, setWhy] = useState(stored.why);
  const [problem, setProblem] = useState<string | null>(null);

  const admitted = influence && consequence ? view.start.risk.admitted[`${influence}/${consequence}`] ?? [] : [];
  // a tier the new ratings do not admit is dropped; a single admitted tier is offered selected, for the person to save
  const draftTier = admitted.length === 1 ? admitted[0] : tier && admitted.includes(tier) ? tier : null;
  const needsWhy = admitted.length > 1;
  const changed = influence !== stored.influence || consequence !== stored.consequence || draftTier !== stored.tier
    || (needsWhy && why.trim() !== stored.why);
  const shownTier = draftTier ?? stored.tier;
  const issues = marks.issues("acceptance.tier");

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
      <div className={`risk-grid${issues.length ? " needs-you" : ""}`}>
        <div className="risk-row">
          <span className="sb-label">Model influence</span>
          <div className="sb-value">
            <Seg options={RATINGS} value={influence} onPick={setInfluence} testId="risk-influence" />
            <Suggested stored={stored.influence} suggested={suggested.influence} testId="risk-influence-suggested" />
          </div>
        </div>
        <div className="risk-row">
          <span className="sb-label">Decision consequence</span>
          <div className="sb-value">
            <Seg options={RATINGS} value={consequence} onPick={setConsequence} testId="risk-consequence" />
            <Suggested stored={stored.consequence} suggested={suggested.consequence} testId="risk-consequence-suggested" />
          </div>
        </div>
        <div className="risk-row">
          <span className="sb-label">Model risk</span>
          <div className="sb-value">
            {admitted.length ? (
              <Seg options={RATINGS.filter((r) => admitted.includes(r))} value={draftTier} onPick={setTier} testId="risk-tier" />
            ) : <span className="muted">rate both first</span>}
            {shownTier && view.start.risk.criteria[shownTier] && (
              <span className="muted" style={{ fontSize: 12.5 }} data-testid="risk-criteria">
                {shownTier}: {view.start.risk.criteria[shownTier]} · {view.start.risk.ruleset}
              </span>
            )}
          </div>
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
      <NeedsYou issues={issues} testId="risk-problem" />
      <Fields view={view} paths={["m15.influence", "m15.consequence"]} save={save} open={open} marks={marks}
              confirmable={["m15.influence", "m15.consequence"]} />
      <InternalTarget key={view.brief.fields["acceptance.internal_target_pe"]?.at ?? ""} view={view} save={save} marks={marks}
                      tier={stored.tier} />
    </Block>
  );
}
