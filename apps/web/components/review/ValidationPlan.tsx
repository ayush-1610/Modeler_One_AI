"use client";

// The validation plan (redesign §3.3): what S4 and S5 judge under the MAP this plan generates, which studies, and what
// happens when a validation fails (MS-01 §4, §6.6). The criteria are the tier's (see Credibility), provisional until the
// SME signs. A blinded study's values stay hidden until the MAP is signed (D-15).

import { InlineIssue } from "@/components/kit";
import type { ReviewPage } from "@/lib/review";

const TITLE: Record<string, string> = { S4: "S4 · internal validation", S5: "S5 · external validation" };

export function ValidationPlan({ review }: { review: ReviewPage }) {
  const tier = review.acceptance.tier;
  return (
    <div className="validation-plan" data-testid="validation-plan">
      {review.validation.map((v) => (
        <section key={v.stage} data-testid={`validation-${v.stage}`}>
          <h3>{TITLE[v.stage] ?? v.stage}</h3>
          <p className="credibility-lede">{v.judges}</p>
          {v.skip_reason ? <InlineIssue severity="note">{v.skip_reason}</InlineIssue> : (
            <ul className="validation-studies">
              {v.studies.map((s) => (
                <li key={s.study_id} data-testid={`validation-${v.stage}-${s.study_id}`}>
                  <code>{s.study_id}</code>
                  {s.blinded && <span className="chip medium" title="its values are hidden until the MAP is signed (D-15)">blinded</span>}
                </li>
              ))}
            </ul>
          )}
          {v.notes.length > 0 && <ul className="limitations">{v.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          <p className="validation-failure"><strong>If it fails:</strong> {v.on_failure}</p>
        </section>
      ))}
      <p className="muted review-hint">Judged by the acceptance criteria of the {tier ?? "(not yet set)"} tier, under Credibility:
        provisional (SME) until the SME signs the ruleset.</p>
    </div>
  );
}
