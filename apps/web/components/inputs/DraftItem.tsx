"use client";

// A sheet read by code on arrival and not saved yet (plan 2026-11-05 §3.1, build C2), on its study's or product's
// card: its data drawn, what code read and left out, and only what the sheet does not say, asked here. A document's
// value for the same study is offered with its quote. Once nothing is left, its data join the card, to confirm.

import { useState } from "react";

import { PeekButton, type PeekSource } from "@/components/kit/SourcePeek";
import { send, type Schema } from "@/lib/api";

import { DatasetView } from "./DatasetView";
import type { Run } from "./InputsTodo";

type Item = Schema<"ReviewItem">;
type Offer = { value: string; label: string; source: PeekSource };
type Draft = {
  sid: string; sheet: string; kind: "concentration_time" | "dissolution"; needs: string[]; labels: Record<string, string>;
  answers: Record<string, string>; problems: string[]; notes: string[]; offers: Record<string, Offer[]>;
};

const CHOICES: Record<string, [string, string][]> = {
  purpose: [["model_building", "Model building: trains the model"], ["external_validation", "External validation: only judges it"],
            ["application_verification", "Application verification: checks the application's prediction"]],
  formulation: [["solution", "Solution"], ["suspension", "Suspension"], ["ir_tablet", "IR tablet"], ["ir_capsule", "IR capsule"],
                ["mr", "Modified release"], ["other", "Other"]],
  food_state: [["fasted", "Fasted"], ["fed", "Fed"]],
  route: [["oral", "Oral"], ["iv_bolus", "IV bolus"], ["iv_infusion", "IV infusion"]],
  role: [["TEST", "Test"], ["RLD", "RLD"], ["REFERENCE", "Reference"], ["OTHER", "Other"]],
};
const NUMBERS = new Set(["n", "dose", "infusion_time_min"]);
const ON_THE_SHEET = new Set(["value_columns", "time_column"]);     // a reading's own settings: corrected on the sheet

export function DraftItem({ projectId, item, run }: { projectId: string; item: Item; run: Run }) {
  const draft = item.draft as unknown as Draft;
  const [values, setValues] = useState<Record<string, string>>({});
  const asked = draft.needs.filter((n) => !ON_THE_SHEET.has(n));
  const onSheet = draft.needs.filter((n) => ON_THE_SHEET.has(n));
  const ready = asked.length > 0 && onSheet.length === 0 && asked.every((n) => (values[n] ?? "").trim() !== "");
  const set = (key: string, value: string) => setValues({ ...values, [key]: value });
  const id = (n: string) => `draft-${draft.sid}-${draft.sheet}-${n}`;
  return (
    <div className="draft-item" data-testid={`draft-${draft.sheet}`}>
      {item.data && <DatasetView data={item.data} label={item.label} />}
      {draft.notes.length > 0 && (
        <details className="draft-notes">
          <summary>What code read in the sheet</summary>
          <ul>{draft.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </details>
      )}
      {draft.problems.length > 0 && <ul className="flags" data-testid="draft-problems">{draft.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      {asked.length > 0 && (
        <fieldset className="draft-form">
          <legend>The sheet does not say: give it here</legend>
          {asked.map((n) => (
            <div key={n} className="draft-need">
              <label htmlFor={id(n)}>{draft.labels[n] ?? n}</label>
              {CHOICES[n] ? (
                <select id={id(n)} value={values[n] ?? ""} onChange={(e) => set(n, e.target.value)} data-testid={`need-${n}`}>
                  <option value="" disabled>choose…</option>
                  {CHOICES[n].map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                </select>
              ) : (
                <input id={id(n)} value={values[n] ?? ""} onChange={(e) => set(n, e.target.value)} data-testid={`need-${n}`}
                       inputMode={NUMBERS.has(n) ? "decimal" : undefined} type={NUMBERS.has(n) ? "number" : "text"} min={0} step="any" />
              )}
              {(draft.offers[n] ?? []).map((o) => (
                <span key={o.label} className="draft-offer">
                  <button type="button" className="btn small" onClick={() => set(n, o.value)} data-testid={`offer-${n}`}>Use {o.label}</button>
                  <PeekButton projectId={projectId} source={o.source} label={o.label} />
                </span>
              ))}
            </div>
          ))}
        </fieldset>
      )}
      {onSheet.length > 0 && (
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>Code could not tell {onSheet.map((n) => draft.labels[n] ?? n).join(" and ")}:
          open this sheet under the client&apos;s files (“Read this sheet”) to set them.</p>
      )}
      {asked.length > 0 && (
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn primary" disabled={!ready} data-testid={`finish-${draft.sheet}`}
                  onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/client-review:finish", { project_id: projectId },
                                                     { file: draft.sid, sheet: draft.sheet, answers: values }),
                                          `${draft.sheet}: read. Its data are on the card, to confirm.`)}>
            Read these data
          </button>
          <span className="muted" style={{ fontSize: 12 }}>Nothing loads until the {draft.kind === "dissolution" ? "product" : "study"} is confirmed.</span>
        </div>
      )}
    </div>
  );
}
