"use client";

// The facts of a study or product no file states, filled in on its card (plan 2026-11-14 slice 3; the design text's
// FactsForm): one row per fact, merged from the delivery's gaps and the checks that name a fact the study record needs
// (so the route is asked once, not as a gap and again as a check), each with a typed control: a choice from the API's
// own vocabularies (`study_options`: the study record's enums, the brief's purposes and the intake vocabulary's matrix
// words, never typed in the web), a number with its unit, or text. The sheet form's answers for the same fact are offered
// as suggestion chips the person still saves. One reason for all of them; each is entered through `:enter`, kept on the
// audit trail with that reason. A check that may stand as written (no dose stated, no matrix stated) keeps "Accept as
// is…" beside its fact, with its own reason (`:override`), as the card's other checks do. The demographics a person has
// are entered the same way ("Enter them…"). Each label names its control; a chosen suggestion is pressed (aria-pressed);
// the button stays enabled and says what is missing when pressed (final review A11Y-10, CODE-6).

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { focusSoon } from "@/components/kit/focus";

import { send, type Schema } from "@/lib/api";
import { readAgain, useResource } from "@/lib/hooks";
import { cardPlace, checkField } from "@/lib/inputsWork";
import { engineWords, fieldLabel, redrawText, valueWord, type RedrawWhy } from "@/lib/words";

import { Problem, Why, useCardDecide, useDecide, type Value } from "./shared";
import { cardAfter } from "./writes";

type Gap = Schema<"DeliveryGap">;
type SpotState = Schema<"DeliverySpotState">;
type Check = Schema<"DeliveryCheck">;
type Options = Schema<"InputsPage">["study_options"];
type Params = { project_id: string; type: string; subject: string };
/** What the sheet form read for a fact, by the intake field it is entered under: offered, never saved for the person. */
export type Suggestions = Record<string, { value: string; from: string }[]>;

const ENTER = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}:enter" as const;
const OVERRIDE = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}:override" as const;
const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
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
 *  names; a check whose fact has a row already is kept on that row (its "Accept as is…"). Each place is the subject's
 *  own (`subject`), so two cards open at once never share one (final review CODE-1). */
function rowsOf(gaps: Gap[], checks: Check[], field: (c: Check) => string | null, subject: string): Row[] {
  const out = new Map<string, Row>();
  for (const g of gaps) {
    if (!out.has(g.tag)) {
      out.set(g.tag, { field: g.tag, anchor: cardPlace("gap", subject, g.tag), testId: cardPlace("enter-gap", subject, g.tag), written: g.value, checks: [] });
    }
  }
  for (const c of checks) {
    const f = field(c) ?? "";
    const known = f ? out.get(f) : undefined;
    if (known) { known.checks.push(c); continue; }
    out.set(f || c.id, { field: f, anchor: `delivery-check-${c.id}`, testId: `delivery-enter-${c.id}`, written: "", code: c.code, checks: [c] });
  }
  return [...out.values()];
}

/** What saving a person's entry does to a spot check drawn already, said before Save (`redrawText`: drawn again, the
 *  values always checked with their ticks). Nothing when no spot check is drawn, or it is stale already. */
export function SpotRedraw({ spot, testId, why }: { spot?: SpotState | null; testId: string; why?: RedrawWhy }) {
  const text = spot ? redrawText(spot, why) : null;
  if (!text) return null;
  return <p className="inline-issue warn m-0 fs-13" data-testid={`${testId}-redraw`}>{text}</p>;
}

/** "Accept as is…" for a check that may stand as written (no dose, no matrix stated), with the reason. Accepted as is,
 *  its values are always checked: a value of it that the spot check drawn now does not hold draws it again, said before
 *  Save (`DeliveryCheck.outside_draw`, final review round 4). */
function AcceptAsIs({ params, check, whose, spot }: {
  params: Params; check: Check;
  /** the subject in words ("study 230-23"): the same check is on every card */
  whose: string;
  spot?: SpotState | null;
}) {
  const [acting, setActing] = useState(false);
  const { decide, busy, problem } = useCardDecide(params.project_id);
  const message = engineWords(check.message ?? "the check");
  if (!acting) {
    return <button type="button" className="link-btn" onClick={() => setActing(true)} data-testid={`delivery-override-open-${check.id}`}
                   aria-label={`Accept as is: ${message} (${whose})`}>Accept as is…</button>;
  }
  return (
    <div className="facts-accept">
      {check.outside_draw > 0 && <SpotRedraw spot={spot} testId={`delivery-override-${check.id}`} why={{ kind: "accepted", values: check.outside_draw }} />}
      <Why action="Accept as is" actionLabel={`Accept as is: ${message} (${whose})`} label={`Why "${message}" holds as it is (${whose})`} busy={busy}
           autoFocus kind="accepted as is"
           onCancel={() => { setActing(false); focusSoon(`delivery-override-open-${check.id}`); }}
           testId={`delivery-override-${check.id}`} placeholder="why it holds as it is (kept on the audit trail)"
           onSubmit={async (why) => {
             const { data } = await decide(() => send("post", OVERRIDE, params, { check_id: check.id, why }));
             if (data) setActing(false);
             return Boolean(data);
           }} />
      <Problem text={problem} testId={`delivery-override-problem-${check.id}`} />
    </div>
  );
}

/** The typed control of one fact, named with its subject (the same form is on every study's card). */
function Control({ row, value, unit, options, onValue, onUnit, whose }: {
  row: Row; value: string; unit: string; options: Options | null; onValue: (v: string) => void; onUnit: (u: string) => void; whose: string;
}) {
  const choices = options?.[CHOICE_OF[row.field] ?? ""] ?? [];
  const label = `${fieldLabel(row.field || "fact")} of ${whose}`;
  if (choices.length) {
    return (
      <select id={`${row.testId}-value`} value={value} onChange={(e) => onValue(e.target.value)} aria-label={label} data-testid={`${row.testId}-value`}>
        <option value="">choose…</option>
        {choices.map((c) => <option key={c} value={c}>{valueWord(c)}</option>)}
      </select>
    );
  }
  const numeric = INTEGER.has(row.field) || NUMBER.has(row.field);
  return (
    <span className="facts-control">
      <input id={`${row.testId}-value`} type={numeric ? "number" : "text"} inputMode={numeric ? "decimal" : undefined} min={numeric ? 0 : undefined}
             step={INTEGER.has(row.field) ? 1 : "any"} value={value} onChange={(e) => onValue(e.target.value)} aria-label={label}
             data-testid={`${row.testId}-value`} />
      {row.field in UNIT_OF && (
        <input type="text" className="facts-unit" value={unit} onChange={(e) => onUnit(e.target.value)} aria-label={`${fieldLabel(row.field || "fact")}: unit, ${whose}`}
               placeholder="unit" data-testid={`${row.testId}-unit`} />
      )}
    </span>
  );
}

const typedValue = (field: string, text: string): string | number => {
  const t = text.trim();
  return (INTEGER.has(field) || NUMBER.has(field)) && /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : t;
};

/** Enter every filled fact with one reason, one `:enter` each. Each answer is the card, written into the page; the
 *  delivery page (the subject's row: its values and how they were read) is read again once, after the last (final
 *  review CODE-4: nothing else on the page changed). */
function useEnterAll(params: Params) {
  const { decide, busy, problem } = useDecide();
  const client = useQueryClient();
  const enter = async (entries: Schema<"DeliveryEntry">[]): Promise<boolean> => {
    let ok = true;
    let entered = false;
    for (const body of entries) {
      const { data } = await decide(() => send("post", ENTER, params, body), cardAfter(params.project_id, []));
      if (!data) { ok = false; break; }
      entered = true;
    }
    if (entered) await readAgain(client, [DELIVERY]);
    return ok;
  };
  return { enter, busy, problem };
}

/** The facts no file states, filled in with one reason (`read`: listed, with no form). `stated`: the fields the card
 *  has an active value of (not asked again when the route makes them needed). */
export function FactsForm({ params, gaps, checks, options, suggestions = {}, read = false, testId, stated = new Set<string>(), spot, whose }: {
  params: Params; gaps: Gap[]; checks: Check[]; options: Options | null; suggestions?: Suggestions;
  read?: boolean; testId: string; stated?: Set<string>;
  /** the card's spot check: drawn already, saving draws it again (said before Save) */
  spot?: SpotState | null;
  /** the subject in words ("study 230-23"), on the form's fields and button: every card has this form (final review
   *  round 4, A11Y-7) */
  whose: string;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [units, setUnits] = useState<Record<string, string>>({});
  const [fields, setFields] = useState<Record<string, string>>({});
  const { enter, busy, problem } = useEnterAll(params);
  // a row is keyed by its fact, so what is typed in it stays when the card is read again and the row comes back from
  // another gap or check (the dosage form offered with the route, then asked by the landing's check)
  const key = (r: Row) => (r.field ? `field:${r.field}` : r.anchor);
  const rows = rowsOf(gaps, checks, checkField, params.subject);
  const route = rows.find((r) => r.field === "route");
  for (const f of route && !read ? AFTER_ROUTE[values[key(route)] ?? ""] ?? [] : []) {
    if (!rows.some((r) => r.field === f) && !stated.has(f)) {
      rows.push({ field: f, anchor: cardPlace("after-route", params.subject, f), testId: cardPlace("enter-after-route", params.subject, f),
                  written: "", checks: [] });
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
              {/* the label names the control it is for (the fact's name, where a person names it) */}
              <label className="facts-label" htmlFor={r.field ? `${r.testId}-value` : `${r.testId}-field`}>{r.field ? fieldLabel(r.field) : "A fact the study needs"}</label>
              <span className="facts-input">
                {!r.field && (
                  <input id={`${r.testId}-field`} type="text" value={fields[k] ?? ""} onChange={(e) => { const t = e.target.value; setFields((p) => ({ ...p, [k]: t })); }}
                         placeholder="the fact" aria-label={`A fact the study needs (${whose})`} data-testid={`${r.testId}-field`} />
                )}
                <Control row={r} value={values[k] ?? ""} unit={units[k] ?? UNIT_OF[r.field] ?? ""} options={options} whose={whose}
                         onValue={(v) => setValues((p) => ({ ...p, [k]: v }))} onUnit={(u) => setUnits((p) => ({ ...p, [k]: u }))} />
                {offered.map((o, i) => (
                  <button key={`${o.value}-${i}`} type="button" className={`chip-btn${values[k] === o.value ? " on" : ""}`}
                          onClick={() => setValues((p) => ({ ...p, [k]: o.value }))} data-testid={`${r.testId}-suggest-${i}`}
                          aria-pressed={values[k] === o.value}
                          aria-label={`${valueWord(o.value)} · the sheet form's answer for ${fieldLabel(r.field || "fact").toLowerCase()} of ${whose} (${o.from})`}
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
                      {c.code !== ENTER_ONLY && <> <AcceptAsIs params={params} check={c} whose={whose} spot={spot} /></>}</div>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {filled.length > 0 && <SpotRedraw spot={spot} testId={testId} />}
      <Why action={filled.length > 1 ? `Save these ${filled.length} facts` : "Save this fact"}
           actionLabel={`${filled.length > 1 ? `Save these ${filled.length} facts` : "Save this fact"} of ${whose}`}
           label={`Where the facts of ${whose} come from`} busy={busy}
           kind="fact entered" missing={filled.length ? null : rows.length > 1 ? "Choose or type at least one of the facts" : "Choose or type the fact"}
           testId={testId} formTestId={`${testId}-reason`} placeholder="where they come from, e.g. the protocol (kept on the audit trail)"
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
             return ok;
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
export function DemographicsForm({ projectId, params, vocabulary, options, onDone, testId, stated = {}, spot, label, focusOn = "first", asked = 0 }: {
  projectId: string; params: Params;
  /** a table layout to read the intake vocabulary from (the population's words), if any */
  vocabulary: { mapping: string | null };
  options: IndividualOptions; onDone: () => void; testId: string;
  stated?: Record<string, Value>;
  /** the study's spot check: drawn already, choosing the individual (or any of these facts) draws it again, said before
   *  Save (final review round 3) */
  spot?: SpotState | null;
  /** the study's label, on the form's button (the same form is on every study's card) */
  label?: string;
  /** where the focus goes when the form opens: its first field a person fills, or the individual's PK-Sim population
   *  (opened by "Choose the individual…") */
  focusOn?: "first" | "individual";
  /** a new number each time the form is asked for again while it is open (the spot check's "Choose the individual…"
   *  pressed again): the focus goes to its field again, as on its first opening (final review round 5) */
  asked?: number;
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
  // what the save still needs, said when pressed (final review CODE-6: the button was disabled with no word on why)
  const lacking = !has("population") && !FOUND_BY.some(has)
    ? "Choose the population and give at least one of the mean age, the age range, the mean weight or the share of women"
    : !has("population") ? "Choose the population" : !FOUND_BY.some(has) ? "Give at least one of the mean age, the age range, the mean weight or the share of women"
      : !changed.length ? (correcting ? "Change a value to save a correction" : "Give a value to save") : null;
  // the form opens on its first field a person fills (it is opened by a button that then goes away), or on the
  // individual's population when it is opened to choose the individual. The population is drawn disabled while its words
  // are read and React keeps that element once they arrive, so an autoFocus never ran on a first open: the focus is
  // moved once the field can take it, once per opening (final review round 4, A11Y-5), and again each time the form is
  // asked for while it is open (`asked`, round 5: a second press of the spot check's link only scrolled). `took` is the
  // opening the focus was given for: what a save writes into the card while the form is open moves nothing
  const first = fromFile("population") ? NUMBERS.find((f) => !fromFile(f)) ?? "individual_population" : "population";
  const target = focusOn === "individual" ? "individual_population" : first;
  const box = useRef<HTMLDivElement>(null);
  const took = useRef<number | null>(null);
  useEffect(() => {
    if (took.current === asked || loading) return;
    const field = box.current?.querySelector<HTMLElement>(`[data-testid="${CSS.escape(`${testId}-${target}`)}"]`);
    if (!field || field.matches(":disabled")) return;
    took.current = asked;
    field.focus();
  }, [loading, target, testId, asked]);
  const read = (f: string) => (
    <span className="facts-read" data-testid={`${testId}-${f}`}>{valueWord(String(stated[f].value))}
      <span className="muted"> · from its file</span></span>
  );
  // each field named with its study, the words on the page first (the same form opens on every study's card)
  const named = (f: string) => (label ? `${fieldLabel(f)} of ${params.type} ${label}` : undefined);
  const women = has("percent_female") ?`${fromFile("percent_female") ? String(stated.percent_female.value) : d.percent_female} % women` : "";
  return (
    <div className="facts-form" data-testid={testId} ref={box}>
      <div className="facts-grid">
        <label className="facts-field">{fieldLabel("population")}
          {fromFile("population") ? read("population")
            : loading ? <select disabled data-testid={`${testId}-population`} aria-busy="true" aria-label={named("population")}><option>loading the words…</option></select>
            : populations.length ? (
              <select value={d.population ?? ""} onChange={set("population")} data-testid={`${testId}-population`} aria-label={named("population")}>
                <option value="">choose…</option>
                {populations.map((p) => <option key={p} value={p}>{valueWord(p)}</option>)}
              </select>
            ) : <input type="text" value={d.population ?? ""} onChange={set("population")} data-testid={`${testId}-population`} aria-label={named("population")} />}
        </label>
        {NUMBERS.map((f) => (
          <label key={f} className="facts-field">{fieldLabel(f)}
            {fromFile(f) ? read(f)
              : <input type="number" inputMode="decimal" min={0} step="any" value={d[f] ?? ""} onChange={set(f)} data-testid={`${testId}-${f}`}
                       aria-label={named(f)} />}
          </label>
        ))}
      </div>
      <fieldset className="facts-individual" data-testid={`${testId}-individual`}>
        <legend>The study&apos;s individual, as PK-Sim simulates it</legend>
        <div className="facts-grid">
          <label className="facts-field">{fieldLabel("individual_population")}
            <select value={d.individual_population ?? ""} onChange={set("individual_population")} data-testid={`${testId}-individual_population`}
                    aria-label={named("individual_population")}>
              <option value="">choose…</option>
              {(options?.population ?? []).map((p) => <option key={p} value={p}>{valueWord(p)}</option>)}
            </select>
          </label>
          <label className="facts-field">{fieldLabel("individual_sex")}{women && <span className="muted fs-12"> ({women})</span>}
            <select value={d.individual_sex ?? ""} onChange={set("individual_sex")} data-testid={`${testId}-individual_sex`}
                    aria-label={named("individual_sex")}>
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
      <SpotRedraw spot={spot} testId={testId} />
      <Why action={correcting ? "Save the corrections" : "Save the demographics"}
           actionLabel={label ? `${correcting ? "Save the corrections of" : "Save the demographics of"} ${label}` : undefined}
           label={label ? `Where the demographics of ${label} come from` : "Where the demographics come from"} busy={busy}
           kind="demographics entered" missing={lacking}
           testId={testId} formTestId={`${testId}-reason`} onCancel={onDone} placeholder="where they come from, e.g. the clinical study report (kept on the audit trail)"
           onSubmit={async (why) => {
             const body = (field: string) => ({ value: typedValue(field, d[field]), why,
                                               ...(entered[field] ? { supersedes: entered[field].id } : { field }) });
             const ok = await enter(changed.map(body));
             if (ok) onDone();
             return ok;
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
