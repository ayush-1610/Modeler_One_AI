"use client";

// The ICH M15 model risk as Start asks for it (map rows p1-m15, p1-risk): the person rates model influence and decision
// consequence, the two ratings bound the risk (M15 §2.1.5, checked by the API), and the person sets it with the reasons.
// The model risk decides the acceptance criteria every round is judged by, so nothing assumes it.

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { RiskChip } from "@/components/ui";
import { ChoiceField, FieldRow, type OpenQuote, type Save } from "@/components/start/Fields";
import type { StartPage } from "@/lib/start";

function admits(allowed: string[]): string {
  if (allowed.length === 1) return `The ratings agree: ICH M15 gives a model risk of ${allowed[0]}.`;
  const words = allowed.length === 2 ? allowed.join(" or ") : `${allowed.slice(0, -1).join(", ")} or ${allowed.at(-1)}`;
  return `The ratings differ: ICH M15 admits ${words}. Choose one and say why.`;
}

export function RiskBlock({ view, onSave, onOpen, busy }: {
  view: StartPage; onSave: Save; onOpen: OpenQuote; busy: boolean;
}) {
  const field = (path: string) => view.risk_fields.find((f) => f.path === path)!;
  const { risk } = view;
  const [changing, setChanging] = useState(false);
  const [tier, setTier] = useState("");
  const [reasons, setReasons] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const choices = risk.allowed.length ? risk.allowed : ["low", "medium", "high"];
  const picked = tier || risk.suggested || "";

  async function set() {
    const failed = await onSave([{ path: "acceptance.tier", status: "EDITED", value: picked, note: reasons.trim() }],
                                `Model risk set to ${picked} at Start`);
    setProblem(failed);
    if (!failed) { setChanging(false); setTier(""); setReasons(""); }
  }

  return (
    <div className="risk-block" data-testid="risk-block">
      <div className="risk-ratings">
        <div>
          <ChoiceField field={field("m15.influence_rating")} onSave={onSave} onOpen={onOpen} busy={busy} />
          <FieldRow field={field("m15.influence")} onSave={onSave} onOpen={onOpen} busy={busy}
                    hint="what the proposal says of it, if anything" />
        </div>
        <div>
          <ChoiceField field={field("m15.consequence_rating")} onSave={onSave} onOpen={onOpen} busy={busy} />
          <FieldRow field={field("m15.consequence")} onSave={onSave} onOpen={onOpen} busy={busy}
                    hint="what the proposal says of it, if anything" />
        </div>
      </div>
      <div className="risk-tier" data-testid="field-acceptance.tier">
        <div className="field-row-head">
          <span className="field-label">Model risk (ICH M15)<span className="req" aria-label="needed"> *</span></span>
          {risk.tier && !changing && <RiskChip rating={risk.tier} />}
        </div>
        {risk.allowed.length > 0 && <p className="muted risk-bound" data-testid="risk-bound">{admits(risk.allowed)}</p>}
        {risk.tier && !changing ? (
          <div className="row">
            <span className="risk-reasons">{risk.reasons}</span>
            <button type="button" className="link-btn" disabled={busy} onClick={() => setChanging(true)}>Change</button>
          </div>
        ) : (
          <div className="row" style={{ alignItems: "flex-start" }}>
            <select aria-label="Model risk" data-testid="risk-tier" value={picked} onChange={(e) => setTier(e.target.value)}>
              <option value="">choose</option>
              {choices.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <input aria-label="Why this model risk" data-testid="risk-reasons" style={{ flex: 1, minWidth: 220 }}
                   placeholder="why: what the model's answer weighs in the decision, and what a wrong one would mean"
                   value={reasons} onChange={(e) => setReasons(e.target.value)} />
            <button type="button" className="btn primary" data-testid="risk-set" disabled={busy || !picked || !reasons.trim()}
                    onClick={set}>Set the model risk</button>
            {changing && <button type="button" className="btn" onClick={() => setChanging(false)}>Cancel</button>}
          </div>
        )}
        {risk.problem && <InlineIssue severity="error" testId="risk-problem">{risk.problem}: set it again.</InlineIssue>}
        {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      </div>
    </div>
  );
}
