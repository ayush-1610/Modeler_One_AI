"use client";

// The facts of a study or product no file states, filled in on its card (plan 2026-11-14 slice 3; the design text's
// FactsForm): one row per fact, merged from the delivery's gaps and the checks that name a fact the study record needs
// (so the route is asked once, not as a gap and again as a check), each with a typed control: a choice from the API's
// own vocabularies (`study_options`: the study record's enums, the brief's purposes and the intake vocabulary's matrix
// words, never typed in the web), a number with its unit, or text. The sheet form's answers for the same fact are offered
// as suggestion chips the person still saves. One reason for all of them; each is entered through `:enter`, kept on the
// audit trail with that reason. A check that may stand as written (no dose stated, no matrix stated) keeps "Accept as
// is…" beside its fact, with its own reason (`:override`), as the card's other checks do. The demographics a person has
// are entered the same way ("Enter them…").

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { send, type Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { engineWords, fieldLabel, valueWord } from "@/lib/words";

import { Problem, Why, useDecide, type Value } from "./shared";

type Gap = Schema<"DeliveryGap">;
type Check = Schema<"DeliveryCheck">;
type Options = Schema<"InputsPage">["study_options"];
type Params = { project_id: string; type: string; subject: string };
/** What the sheet form read for a fact, by the intake field it is entered under: offered, never saved for the person. */
export type Suggestions = Record<string, { value: string; from: string }[]>;

const ENTER = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}:enter" as const;
const OVERRIDE = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}:override" as const;
// the check that names a fact the study record needs is settled only by entering it (the landing cannot load the study
// without it); the others (no dose, no matrix stated) may also be accepted as is, with the reason
const ENTER_ONLY = "LANDING_FIELD_MISSING";
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
// what the study record asks once the route is known (the landing's `intake_landing._Record.read`): an oral study's
// dosage form and its fasted or fed state, an infusion's time. Offered as soon as the route is chosen, so the facts go
// in one submission with one reason (final review, owner-job gap 7); a fact a file states already is not asked, and
// the landing still checks them all
const AFTER_ROUTE: Record<string, string[]> = { oral: ["formulation", "food_state"], iv_infusion: ["infusion_time_min"] };

type Row = {
  field: string; anchor: string; testId: string;
  /** what the file writes for the fact, which the intake rules do not read (a gap's value), if anything */
  written: string;
  code?: string;
  /** the failed checks that name this fact (one row per fact, however many name it) */
  checks: Check[];
};

/** The facts to fill, one row per field: the gaps first (their place is where To do opens), then a check's field no gap
 *  names; a check whose fact has a row already is kept on that row (its "Accept as is…"). */
function rowsOf(gaps: Gap[], checks: Check[], field: (c: Check) => string | null): Row[] {
  const out = new Map<string, Row>();
  for (const g of gaps) {
    if (!out.has(g.tag)) out.set(g.tag, { field: g.tag, anchor: `delivery-gap-${g.tag}`, testId: `delivery-enter-gap-${g.tag}`, written: g.value, checks: [] });
  }
  for (const c of checks) {
    const f = field(c) ?? "";
    const known = f ? out.get(f) : undefined;
    if (known) { known.checks.push(c); continue; }
    out.set(f || c.id, { field: f, anchor: `delivery-check-${c.id}`, testId: `delivery-enter-${c.id}`, written: "", code: c.code, checks: [c] });
  }
  return [...out.values()];
}

/** "Accept as is…" for a check that may stand as written (no dose, no matrix stated), with the reason. */
function AcceptAsIs({ params, check }: { params: Params; check: Check }) {
  const [acting, setActing] = useState(false);
  const { decide, busy, problem } = useDecide();
  const message = engineWords(check.message ?? "the check");
  if (!acting) {
    return <button type="button" className="link-btn" onClick={() => setActing(true)} data-testid={`delivery-override-open-${check.id}`}
                   aria-label={`Accept as is: ${message}`}>Accept as is…</button>;
  }
  return (
    <div className="facts-accept">
      <Why action="Accept as is" label={`Why "${message}" holds as it is`} busy={busy} onCancel={() => setActing(false)} autoFocus
           testId={`delivery-override-${check.id}`} placeholder="why it holds as it is (kept on the audit trail)"
           onSubmit={async (why) => { const { data } = await decide(() => send("post", OVERRIDE, params, { check_id: check.id, why })); if (data) setActing(false); }} />
      <Problem text={problem} testId={`delivery-override-problem-${check.id}`} />
    </div>
  );
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

/** The facts no file states, filled in with one reason (`read`: listed, with no form). `stated`: the fields the card
 *  has an active value of (not asked again when the route makes them needed). */
export function FactsForm({ params, gaps, checks, options, suggestions = {}, read = false, testId, stated = new Set<string>() }: {
  params: Params; gaps: Gap[]; checks: Check[]; options: Options | null; suggestions?: Suggestions;
  read?: boolean; testId: string; stated?: Set<string>;
}) {
  const fieldOf = (c: Check) => (c.code === "LANDING_FIELD_MISSING" ? /needs (\w+)/.exec(c.message ?? "")?.[1] ?? null
    : c.code === "DOSE_MISSING" ? "dose" : c.code === "MATRIX_MISSING" ? "matrix" : null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [units, setUnits] = useState<Record<string, string>>({});
  const [fields, setFields] = useState<Record<string, string>>({});
  const { enter, busy, problem } = useEnterAll(params);
  // a row is keyed by its fact, so what is typed in it stays when the card is read again and the row comes back from
  // another gap or check (the dosage form offered with the route, then asked by the landing's check)
  const key = (r: Row) => (r.field ? `field:${r.field}` : r.anchor);
  const rows = rowsOf(gaps, checks, fieldOf);
  const route = rows.find((r) => r.field === "route");
  for (const f of route && !read ? AFTER_ROUTE[values[key(route)] ?? ""] ?? [] : []) {
    if (!rows.some((r) => r.field === f) && !stated.has(f)) {
      rows.push({ field: f, anchor: `delivery-after-route-${f}`, testId: `delivery-enter-after-route-${f}`, written: "", checks: [] });
    }
  }
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
                  <input type="text" value={fields[k] ?? ""} onChange={(e) => { const t = e.target.value; setFields((p) => ({ ...p, [k]: t })); }} placeholder="the fact"
                         aria-label="the fact" data-testid={`${r.testId}-field`} />
                )}
                <Control row={r} value={values[k] ?? ""} unit={units[k] ?? UNIT_OF[r.field] ?? ""} options={options}
                         onValue={(v) => setValues((p) => ({ ...p, [k]: v }))} onUnit={(u) => setUnits((p) => ({ ...p, [k]: u }))} />
                {offered.map((o, i) => (
                  <button key={`${o.value}-${i}`} type="button" className={`chip-btn${values[k] === o.value ? " on" : ""}`}
                          onClick={() => setValues((p) => ({ ...p, [k]: o.value }))} data-testid={`${r.testId}-suggest-${i}`}
                          title={`What the sheet form read: ${o.from}`}>
                    {valueWord(o.value)} <span className="muted">· the sheet form&apos;s answer</span>
                  </button>
                ))}
              </span>
              {(r.written || r.checks.some((c) => c.code !== ENTER_ONLY) || !r.field) && (
                <div className="muted fs-12 facts-why">
                  {r.written ? <div>as written in its file: “{r.written}”</div> : null}
                  {r.checks.filter((c) => c.code !== ENTER_ONLY || !r.field).map((c) => (
                    <div key={c.id} className="facts-check" data-testid={r.anchor === `delivery-check-${c.id}` ? undefined : `delivery-check-${c.id}`}
                         data-code={c.code}>{engineWords(c.message ?? "a check failed")}
                      {c.code !== ENTER_ONLY && <> <AcceptAsIs params={params} check={c} /></>}</div>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <Why action={filled.length > 1 ? `Save these ${filled.length} facts` : "Save this fact"} label="Where the facts come from" busy={busy}
           disabled={!filled.length} testId={testId} formTestId={`${testId}-reason`} placeholder="where they come from, e.g. the protocol (kept on the audit trail)"
           onSubmit={async (why) => {
             const sent = Object.fromEntries(filled.map((r) => [key(r), values[key(r)] ?? ""]));
             const ok = await enter(filled.map((r) => {
               const field = r.field || (fields[key(r)] ?? "").trim();
               const unit = (units[key(r)] ?? UNIT_OF[r.field] ?? "").trim();
               return { field, value: typedValue(field, values[key(r)] ?? ""), ...(unit ? { unit } : {}), why };
             }));
             // only what was saved is cleared: a fact typed while the card was read again (the rows a saved route
             // asks for next) is kept
             if (ok) setValues((p) => Object.fromEntries(Object.entries(p).filter(([k, v]) => sent[k] !== v)));
           }} />
      <Problem text={problem} testId={`${testId}-problem`} />
    </div>
  );
}

// the facts that make a study's demographics found (the intake rules' REQ-sys.demographics: the population, and one of
// the age, the weight or the share of women), entered under the intake vocabulary's names; with them, the study's
// simulated individual (D-29): the PK-Sim population database and the sex, a person's choice, which with the mean age,
// its range, the mean weight and height become the study's individual when it is confirmed
// (`intake_landing.study_individual`, the template's path's rule)
const FOUND_BY = ["age_mean", "age_min", "age_max", "weight_mean_kg", "percent_female"] as const;
const NUMBERS = ["age_mean", "age_min", "age_max", "weight_mean_kg", "height_mean_cm", "percent_female"] as const;
const INDIVIDUAL = ["individual_population", "individual_sex"] as const;
export const DEMOGRAPHICS = ["population", ...NUMBERS, ...INDIVIDUAL] as const;

/** The demographics stated on a study's card (active, newest kept per fact), a file's or a person's: a person's are
 *  corrected in the form (`supersedes`), a file's are shown as read. */
export function statedDemographics(values: Value[]): Record<string, Value> {
  const out: Record<string, Value> = {};
  for (const v of values) {
    if (v.status === "superseded" || v.status === "excluded" || v.value === null || !(DEMOGRAPHICS as readonly string[]).includes(v.field)) continue;
    if (out[v.field]?.method === "person" && v.method !== "person") continue;      // a person's entry is the one corrected
    out[v.field] = v;
  }
  return out;
}

/** The PK-Sim population databases and the sexes a study's individual may have (the API's `study_options`). */
type IndividualOptions = { population: string[]; sex: string[] } | null;

/** The demographics of a study, entered by a person who has them (instead of asking the client): its population (the
 *  intake vocabulary's words, read from a table layout's vocabulary; typed when no layout is there to read it from), the
 *  mean age or its range, the mean weight and height and the share of women; and the study's individual, which PK-Sim
 *  simulates: one PK-Sim population database and one sex, chosen by the person (as on the sheet form's path). Each is
 *  entered through `:enter` with one reason, and with the mean age they become the study's individual when it is
 *  confirmed. `stated`: what is stated already; a person's entry is shown and corrected (`supersedes`) where changed,
 *  never entered twice; a file's is shown as read. */
export function DemographicsForm({ projectId, params, vocabulary, options, onDone, testId, stated = {} }: {
  projectId: string; params: Params;
  /** a table layout to read the intake vocabulary from (the population's words), if any */
  vocabulary: { mapping: string | null };
  options: IndividualOptions; onDone: () => void; testId: string;
  stated?: Record<string, Value>;
}) {
  const layout = useResource("/api/v1/projects/{project_id}/delivery/mappings/{mapping_id}",
                             { project_id: projectId, mapping_id: vocabulary.mapping ?? "" }, { enabled: Boolean(vocabulary.mapping) });
  // the population's words are read before the field is offered, so what is typed is never lost to the list arriving
  const loading = Boolean(vocabulary.mapping) && !layout.data && !layout.problem;
  const populations = layout.data?.vocabulary.fields.find((f) => f.name === "population")?.choices ?? [];
  const fromFile = (f: string) => Boolean(stated[f]) && stated[f].method !== "person";
  const entered = Object.fromEntries(Object.entries(stated).filter(([f]) => !fromFile(f)));
  const [d, setD] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(entered)
    .map(([f, v]) => [f, v.value === null ? "" : String(v.value)])));
  const { enter, busy, problem } = useEnterAll(params);
  const set = (k: string) => (e: { target: { value: string } }) => { const t = e.target.value; setD((p) => ({ ...p, [k]: t })); };
  const has = (f: string) => fromFile(f) || Boolean((d[f] ?? "").trim());
  const changed = DEMOGRAPHICS.filter((f) => !fromFile(f) && (d[f] ?? "").trim() && (d[f] ?? "").trim() !== String(entered[f]?.value ?? ""));
  const correcting = Object.keys(entered).length > 0;
  const individual = has("individual_population") && has("individual_sex") && has("age_mean");
  const read = (f: string) => (
    <span className="facts-read" data-testid={`${testId}-${f}`}>{valueWord(String(stated[f].value))}
      <span className="muted"> · from its file</span></span>
  );
  const women = has("percent_female") ? `${fromFile("percent_female") ? String(stated.percent_female.value) : d.percent_female} % women` : "";
  return (
    <div className="facts-form" data-testid={testId}>
      <div className="facts-grid">
        <label className="facts-field">{fieldLabel("population")}
          {fromFile("population") ? read("population")
            : loading ? <select disabled data-testid={`${testId}-population`} aria-busy="true"><option>loading the words…</option></select>
            : populations.length ? (
              <select value={d.population ?? ""} onChange={set("population")} data-testid={`${testId}-population`}>
                <option value="">choose…</option>
                {populations.map((p) => <option key={p} value={p}>{valueWord(p)}</option>)}
              </select>
            ) : <input type="text" value={d.population ?? ""} onChange={set("population")} data-testid={`${testId}-population`} />}
        </label>
        {NUMBERS.map((f) => (
          <label key={f} className="facts-field">{fieldLabel(f)}
            {fromFile(f) ? read(f)
              : <input type="number" inputMode="decimal" min={0} step="any" value={d[f] ?? ""} onChange={set(f)} data-testid={`${testId}-${f}`} />}
          </label>
        ))}
      </div>
      <fieldset className="facts-individual" data-testid={`${testId}-individual`}>
        <legend>The study&apos;s individual, as PK-Sim simulates it</legend>
        <div className="facts-grid">
          <label className="facts-field">{fieldLabel("individual_population")}
            <select value={d.individual_population ?? ""} onChange={set("individual_population")} data-testid={`${testId}-individual_population`}>
              <option value="">choose…</option>
              {(options?.population ?? []).map((p) => <option key={p} value={p}>{valueWord(p)}</option>)}
            </select>
          </label>
          <label className="facts-field">{fieldLabel("individual_sex")}{women && <span className="muted fs-12"> ({women})</span>}
            <select value={d.individual_sex ?? ""} onChange={set("individual_sex")} data-testid={`${testId}-individual_sex`}>
              <option value="">choose…</option>
              {(options?.sex ?? []).map((v) => <option key={v} value={v}>{valueWord(v)}</option>)}
            </select>
          </label>
        </div>
        <p className="muted fs-12 m-4-0-0" data-testid={`${testId}-individual-note`}>
          {individual ? "With the mean age, its range and the mean weight, this is the individual the study is simulated with once it is confirmed."
            : "One PK-Sim population and one sex, with the mean age: without them the demographics are kept with the study, not simulated."}
        </p>
      </fieldset>
      <Why action={correcting ? "Save the corrections" : "Save the demographics"} label="Where the demographics come from" busy={busy}
           disabled={!has("population") || !FOUND_BY.some(has) || !changed.length}
           testId={testId} formTestId={`${testId}-reason`} onCancel={onDone} placeholder="where they come from, e.g. the clinical study report (kept on the audit trail)"
           onSubmit={async (why) => {
             const body = (field: string) => ({ value: typedValue(field, d[field]), why,
                                               ...(entered[field] ? { supersedes: entered[field].id } : { field }) });
             if (await enter(changed.map(body))) onDone();
           }} />
      <Problem text={problem} testId={`${testId}-problem`} />
    </div>
  );
}

/** The demographics stated, in a line: "Healthy · mean age (years) 34 · women (%) 50". */
export function demographicsText(stated: Record<string, Value>): string {
  return DEMOGRAPHICS.filter((f) => stated[f] && !(INDIVIDUAL as readonly string[]).includes(f)).map((f) => {
    const v = stated[f].value;
    return f === "population" ? valueWord(String(v)) : `${fieldLabel(f).toLowerCase()} ${String(v)}`;
  }).join(" · ");
}
