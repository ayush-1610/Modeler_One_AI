"use client";

// The facts of a study or product no file states, filled in on its card (plan 2026-11-14 slice 3; the design text's
// FactsForm): one row per fact, merged from the delivery's gaps and the checks that name a fact the study record needs
// (so the route is asked once, not as a gap and again as a check), each with a typed control: a choice from the API's
// own vocabularies (`study_options`: the study record's enums, the brief's purposes and the intake vocabulary's matrix
// words, never typed in the web), a number with its unit, or text. The sheet form's answers for the same fact are offered
// as suggestion chips the person still saves. One reason for all of them; each is entered through `:enter`, kept on the
// audit trail with that reason. The demographics a person has are entered the same way ("Enter them…").

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { send, type Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { fieldLabel, valueWord } from "@/lib/words";

import { Problem, Why, useDecide } from "./shared";

type Gap = Schema<"DeliveryGap">;
type Check = Schema<"DeliveryCheck">;
type Options = Schema<"InputsPage">["study_options"];
type Params = { project_id: string; type: string; subject: string };
/** What the sheet form read for a fact, by the intake field it is entered under: offered, never saved for the person. */
export type Suggestions = Record<string, { value: string; from: string }[]>;

const ENTER = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}:enter" as const;
// the intake field a choice is offered from: the Inputs page's `study_options` names (`intended_use` is the study's
// purpose, from the same five words)
const CHOICE_OF: Record<string, string> = {
  route: "route", formulation: "formulation", food_state: "food_state", intended_use: "purpose", purpose: "purpose", matrix: "matrix",
};
const INTEGER = new Set(["n", "n_evaluable", "n_doses", "n_female"]);
const NUMBER = new Set(["dose", "lloq", "infusion_time_min", "dosing_interval_h", "age_mean", "age_min", "age_max", "weight_mean_kg",
                        "height_mean_cm", "percent_female", "strength_mg"]);
// the unit a number is entered with, when the field has one the person states (a dose in mg or mg/kg, an LLOQ in its
// concentration unit); the others carry their unit in their name
const UNIT_OF: Record<string, string> = { dose: "mg", lloq: "" };

type Row = { field: string; anchor: string; testId: string; reason: string; code?: string };

/** The facts to fill, one row per field: the gaps first (their place is where To do opens), then a check's field no gap
 *  names. */
function rowsOf(gaps: Gap[], checks: Check[], field: (c: Check) => string | null): Row[] {
  const out = new Map<string, Row>();
  for (const g of gaps) {
    if (!out.has(g.tag)) out.set(g.tag, { field: g.tag, anchor: `delivery-gap-${g.tag}`, testId: `delivery-enter-gap-${g.tag}`, reason: g.reason });
  }
  for (const c of checks) {
    const f = field(c) ?? "";
    if (f && out.has(f)) continue;
    out.set(f || c.id, { field: f, anchor: `delivery-check-${c.id}`, testId: `delivery-enter-${c.id}`, reason: c.message ?? "", code: c.code });
  }
  return [...out.values()];
}

/** The typed control of one fact. */
function Control({ row, value, unit, options, onValue, onUnit }: {
  row: Row; value: string; unit: string; options: Options | null; onValue: (v: string) => void; onUnit: (u: string) => void;
}) {
  const choices = options?.[CHOICE_OF[row.field] ?? ""] ?? [];
  const label = fieldLabel(row.field || "fact");
  if (choices.length) {
    return (
      <select value={value} onChange={(e) => onValue(e.target.value)} aria-label={label} data-testid={`${row.testId}-value`}>
        <option value="">choose…</option>
        {choices.map((c) => <option key={c} value={c}>{valueWord(c)}</option>)}
      </select>
    );
  }
  const numeric = INTEGER.has(row.field) || NUMBER.has(row.field);
  return (
    <span className="facts-control">
      <input type={numeric ? "number" : "text"} inputMode={numeric ? "decimal" : undefined} min={numeric ? 0 : undefined}
             step={INTEGER.has(row.field) ? 1 : "any"} value={value} onChange={(e) => onValue(e.target.value)} aria-label={label}
             data-testid={`${row.testId}-value`} />
      {row.field in UNIT_OF && (
        <input type="text" className="facts-unit" value={unit} onChange={(e) => onUnit(e.target.value)} aria-label={`${label}: unit`}
               placeholder="unit" data-testid={`${row.testId}-unit`} />
      )}
    </span>
  );
}

const typedValue = (field: string, text: string): string | number => {
  const t = text.trim();
  return (INTEGER.has(field) || NUMBER.has(field)) && /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : t;
};

/** Enter every filled fact with one reason, one `:enter` each; the card is read again once, after the last. */
function useEnterAll(params: Params) {
  const { decide, busy, problem } = useDecide();
  const client = useQueryClient();
  const enter = async (entries: Schema<"DeliveryEntry">[]): Promise<boolean> => {
    let ok = true;
    for (const body of entries) {
      const { data } = await decide(() => send("post", ENTER, params, body), { refresh: false });
      if (!data) { ok = false; break; }
    }
    await client.invalidateQueries();
    return ok;
  };
  return { enter, busy, problem };
}

/** The facts no file states, filled in with one reason (`read`: listed, with no form). */
export function FactsForm({ params, gaps, checks, options, suggestions = {}, read = false, testId }: {
  params: Params; gaps: Gap[]; checks: Check[]; options: Options | null; suggestions?: Suggestions;
  read?: boolean; testId: string;
}) {
  const fieldOf = (c: Check) => (c.code === "LANDING_FIELD_MISSING" ? /needs (\w+)/.exec(c.message ?? "")?.[1] ?? null
    : c.code === "DOSE_MISSING" ? "dose" : c.code === "MATRIX_MISSING" ? "matrix" : null);
  const rows = rowsOf(gaps, checks, fieldOf);
  const [values, setValues] = useState<Record<string, string>>({});
  const [units, setUnits] = useState<Record<string, string>>({});
  const [fields, setFields] = useState<Record<string, string>>({});
  const { enter, busy, problem } = useEnterAll(params);
  const key = (r: Row) => r.anchor;
  const filled = rows.filter((r) => (values[key(r)] ?? "").trim() && (r.field || (fields[key(r)] ?? "").trim()));

  if (read) {
    return (
      <div className="facts-missing" data-testid={testId}>
        <p className="m-0 fs-13"><span className="chip high">Missing</span> Not stated in any file: {rows.map((r) => fieldLabel(r.field || "a fact").toLowerCase()).join(", ")}.</p>
      </div>
    );
  }
  return (
    <div className="facts-form" data-testid={testId}>
      <p className="facts-lede"><span className="chip high">Missing</span> No file states {rows.length === 1 ? "this fact" : "these facts"}: fill
        in what you know, with where it comes from.</p>
      <ul className="facts-rows">
        {rows.map((r) => {
          const k = key(r);
          const offered = suggestions[r.field] ?? [];
          return (
            <li key={k} className="facts-row" data-testid={r.anchor} data-code={r.code}>
              <label className="facts-label" htmlFor={`${r.testId}-control`}>{r.field ? fieldLabel(r.field) : "A fact the study needs"}</label>
              <span id={`${r.testId}-control`} className="facts-input">
                {!r.field && (
                  <input type="text" value={fields[k] ?? ""} onChange={(e) => setFields({ ...fields, [k]: e.target.value })} placeholder="the fact"
                         aria-label="the fact" data-testid={`${r.testId}-field`} />
                )}
                <Control row={r} value={values[k] ?? ""} unit={units[k] ?? UNIT_OF[r.field] ?? ""} options={options}
                         onValue={(v) => setValues({ ...values, [k]: v })} onUnit={(u) => setUnits({ ...units, [k]: u })} />
                {offered.map((o, i) => (
                  <button key={`${o.value}-${i}`} type="button" className={`chip-btn${values[k] === o.value ? " on" : ""}`}
                          onClick={() => setValues({ ...values, [k]: o.value })} data-testid={`${r.testId}-suggest-${i}`}
                          title={`What the sheet form read: ${o.from}`}>
                    {valueWord(o.value)} <span className="muted">· the sheet form&apos;s answer</span>
                  </button>
                ))}
              </span>
              {r.reason && <span className="muted fs-12 facts-why">{r.reason}</span>}
            </li>
          );
        })}
      </ul>
      <Why action={filled.length > 1 ? `Save these ${filled.length} facts` : "Save this fact"} label="Where the facts come from" busy={busy}
           disabled={!filled.length} testId={testId} placeholder="where they come from, e.g. the protocol (kept on the audit trail)"
           onSubmit={async (why) => {
             const ok = await enter(filled.map((r) => {
               const field = r.field || (fields[key(r)] ?? "").trim();
               const unit = (units[key(r)] ?? UNIT_OF[r.field] ?? "").trim();
               return { field, value: typedValue(field, values[key(r)] ?? ""), ...(unit ? { unit } : {}), why };
             }));
             if (ok) setValues({});
           }} />
      <Problem text={problem} testId={`${testId}-problem`} />
    </div>
  );
}

// the facts that make a study's demographics found (the intake rules' REQ-sys.demographics: the population, and one of
// the age, the weight or the share of women), entered under the intake vocabulary's names
const DEMOGRAPHIC_FIELDS = ["age_mean", "age_min", "age_max", "weight_mean_kg", "percent_female"] as const;

/** The demographics of a study, entered by a person who has them (instead of asking the client): its population (the
 *  intake vocabulary's words, read from a table layout's vocabulary; typed when no layout is there to read it from), the
 *  mean age or its range, the mean weight and the share of women. Each is entered through `:enter` with one reason; the
 *  study is simulated with them once it is confirmed. */
export function DemographicsForm({ projectId, params, vocabulary, onDone, testId }: {
  projectId: string; params: Params;
  /** a table layout to read the intake vocabulary from (the population's words), if any */
  vocabulary: { mapping: string | null }; onDone: () => void; testId: string;
}) {
  const layout = useResource("/api/v1/projects/{project_id}/delivery/mappings/{mapping_id}",
                             { project_id: projectId, mapping_id: vocabulary.mapping ?? "" }, { enabled: Boolean(vocabulary.mapping) });
  const populations = layout.data?.vocabulary.fields.find((f) => f.name === "population")?.choices ?? [];
  const [d, setD] = useState<Record<string, string>>({});
  const { enter, busy, problem } = useEnterAll(params);
  const set = (k: string) => (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value });
  const any = DEMOGRAPHIC_FIELDS.some((f) => (d[f] ?? "").trim());
  return (
    <div className="facts-form" data-testid={testId}>
      <div className="facts-grid">
        <label className="facts-field">{fieldLabel("population")}
          {populations.length ? (
            <select value={d.population ?? ""} onChange={set("population")} data-testid={`${testId}-population`}>
              <option value="">choose…</option>
              {populations.map((p) => <option key={p} value={p}>{valueWord(p)}</option>)}
            </select>
          ) : <input type="text" value={d.population ?? ""} onChange={set("population")} data-testid={`${testId}-population`} />}
        </label>
        {DEMOGRAPHIC_FIELDS.map((f) => (
          <label key={f} className="facts-field">{fieldLabel(f)}
            <input type="number" inputMode="decimal" min={0} step="any" value={d[f] ?? ""} onChange={set(f)} data-testid={`${testId}-${f}`} />
          </label>
        ))}
      </div>
      <Why action="Save the demographics" label="Where the demographics come from" busy={busy} disabled={!(d.population ?? "").trim() || !any}
           testId={testId} onCancel={onDone} placeholder="where they come from, e.g. the clinical study report (kept on the audit trail)"
           onSubmit={async (why) => {
             const filled = ["population", ...DEMOGRAPHIC_FIELDS].filter((f) => (d[f] ?? "").trim());
             if (await enter(filled.map((field) => ({ field, value: typedValue(field, d[field]), why })))) onDone();
           }} />
      <Problem text={problem} testId={`${testId}-problem`} />
    </div>
  );
}
