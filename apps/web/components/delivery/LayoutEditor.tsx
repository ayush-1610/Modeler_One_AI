"use client";

// A table's layout as a form (plan 2026-11-14 §3 API 4; design "How the person fills what is missing"): what the table
// is, where its data rows are, and for each column what it holds (its role, its field with the field's unit class, its
// statistic, its spread, the value column it qualifies), every choice a select built only from the API's own words
// (`DeliveryMapping.vocabulary`, read from `modeler_intake`): nothing here is a name the web made up. Units are typed
// as the table writes them; code checks each against its header. What the form does not edit (row rules, label keys,
// constants read from the caption) is kept as it is, and the whole layout stays editable as text for experts. A layout
// the code refuses comes back with its findings, each shown beside the column or the setting it names.

import { useMemo, useState } from "react";

import type { Schema } from "@/lib/api";

import { Why, fieldText } from "./shared";

export type Vocabulary = Schema<"DeliveryMappingVocabulary">;
export type Finding = Schema<"DeliveryMappingFinding">;
type Spec = Record<string, unknown>;

/** A column as the form edits it; `rest` keeps what the form does not show (its cites). Role "" leaves it unread. */
type Column = { column: number; role: string; field: string; unit: string; statistic: string; spread_kind: string; of: string;
                cell_form: string; condition: string; reason: string; rest: Spec };
/** The table-wide settings the form edits. */
type Table = { kind: string; layout: string; header_rows: string; first_data_row: string; last_data_row: string; time_row: string;
               field: string; statistic: string; time_reference: string; time_unit: string; value_unit: string;
               below_lloq: string; missing: string; not_data_reason: string };

const TABLE_KEYS = ["kind", "layout", "header_rows", "first_data_row", "last_data_row", "time_row", "field", "statistic",
                    "time_reference", "time_unit", "value_unit", "below_lloq_tokens", "missing_tokens", "not_data_reason", "columns"];
const COLUMN_KEYS = ["column", "role", "field", "unit", "statistic", "spread_kind", "of", "cell_form", "condition", "reason"];
// the roles that qualify one value column (`of`), and those a value or a spread carries a statistic or spread with
// (modeler_intake.mapping.validate: QUALIFIERS)
const QUALIFIERS = new Set(["spread", "n", "lloq", "interval_low", "interval_high", "unit", "blq_flag", "spread_kind"]);
// what each layout is, as modeler_intake.mapping_spec says it
const LAYOUT_WORDS: Record<string, string> = {
  long: "one row per value", wide_series: "times down a column, one column per series",
  wide_times: "times across the header, one row per series", key_value: "a label column says what each row is",
};

const text = (x: unknown) => (x === null || x === undefined ? "" : String(x));
const tokens = (x: unknown) => (Array.isArray(x) ? x.map(String).join(", ") : "");
const list = (s: string) => s.split(",").map((t) => t.trim()).filter(Boolean);
const whole = (s: string) => (/^\d+$/.test(s.trim()) ? Number(s.trim()) : null);
/** A column's letters on its sheet, from the column the table starts at (1: A). */
const letters = (n: number) => { let s = ""; for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) s = String.fromCharCode(65 + ((x - 1) % 26)) + s; return s; };

function tableOf(spec: Spec): Table {
  return {
    kind: text(spec.kind), layout: text(spec.layout) || "long", header_rows: text(spec.header_rows ?? 1),
    first_data_row: text(spec.first_data_row ?? 2), last_data_row: text(spec.last_data_row), time_row: text(spec.time_row),
    field: text(spec.field), statistic: text(spec.statistic), time_reference: text(spec.time_reference),
    time_unit: text(spec.time_unit), value_unit: text(spec.value_unit), below_lloq: tokens(spec.below_lloq_tokens),
    missing: tokens(spec.missing_tokens), not_data_reason: text(spec.not_data_reason),
  };
}

function columnsOf(spec: Spec, count: number): Column[] {
  const mapped = new Map<number, Spec>();
  for (const c of (Array.isArray(spec.columns) ? spec.columns : []) as Spec[]) mapped.set(Number(c.column), c);
  const n = Math.max(count, ...mapped.keys(), 0);
  return Array.from({ length: n }, (_, i) => {
    const c = mapped.get(i + 1) ?? {};
    const rest = Object.fromEntries(Object.entries(c).filter(([k]) => !COLUMN_KEYS.includes(k)));
    return { column: i + 1, role: text(c.role), field: text(c.field), unit: text(c.unit), statistic: text(c.statistic),
             spread_kind: text(c.spread_kind), of: text(c.of), cell_form: c.cell_form === "value" ? "" : text(c.cell_form),
             condition: text(c.condition), reason: text(c.reason), rest };
  });
}

/** The spec the form says: the spec it started from, with every setting the form edits written from the form. */
function build(base: Spec, t: Table, columns: Column[]): Spec {
  const out: Spec = Object.fromEntries(Object.entries(base).filter(([k]) => !TABLE_KEYS.includes(k)));
  out.schema = base.schema ?? "mapping/2";
  out.kind = t.kind;
  out.layout = t.layout;
  out.header_rows = whole(t.header_rows) ?? t.header_rows;
  out.first_data_row = whole(t.first_data_row) ?? t.first_data_row;
  if (t.last_data_row.trim()) out.last_data_row = whole(t.last_data_row) ?? t.last_data_row;
  if (t.time_row.trim()) out.time_row = whole(t.time_row) ?? t.time_row;
  for (const key of ["field", "statistic", "time_reference", "time_unit", "value_unit", "not_data_reason"] as const) {
    if (t[key].trim()) out[key] = t[key].trim();
  }
  if (list(t.below_lloq).length) out.below_lloq_tokens = list(t.below_lloq);
  if (list(t.missing).length) out.missing_tokens = list(t.missing);
  out.columns = columns.filter((c) => c.role).map((c) => {
    const col: Spec = { column: c.column, role: c.role, ...c.rest };
    for (const key of ["field", "unit", "statistic", "spread_kind", "cell_form", "condition", "reason"] as const) {
      if (c[key].trim()) col[key] = c[key].trim();
    }
    if (c.of) col.of = Number(c.of);
    return col;
  });
  return out;
}

/** Where a finding stands: a column of the form (its number), a table-wide setting (its key), or neither (""). */
function placeOf(location: string, sent: number[]): { column: number | null; key: string } {
  const col = /^columns\[(\d+)\]/.exec(location);
  if (col) return { column: sent[Number(col[1])] ?? null, key: "" };
  const key = (/^[a-z_]+/.exec(location)?.[0] ?? "").replace(/_cite$/, "");
  return { column: null, key: TABLE_KEYS.includes(key) || key === "below_lloq_tokens" ? key : "" };
}

function Said({ findings, testId }: { findings: Finding[]; testId?: string }) {
  if (!findings.length) return null;
  return (
    <ul className="delivery-findings layout-said" data-testid={testId}>
      {findings.map((f, i) => (
        <li key={`${f.code}-${i}`} className={f.severity === "error" ? "error" : undefined}>
          <span className={`chip ${f.severity === "error" ? "high" : "medium"}`}>{f.severity === "error" ? "to fix" : "note"}</span> {f.message}
        </li>
      ))}
    </ul>
  );
}

function Pick({ label, value, onChange, words, none, testId, describe }: {
  label: string; value: string; onChange: (v: string) => void; words: string[];
  /** the empty choice's words; left out, a choice is required */
  none?: string; testId?: string; describe?: (word: string) => string;
}) {
  return (
    <label className="delivery-pick">{label}
      <select value={value} onChange={(e) => onChange(e.target.value)} data-testid={testId}>
        {none !== undefined ? <option value="">{none}</option> : !value && <option value="">choose…</option>}
        {words.map((w) => <option key={w} value={w}>{describe ? describe(w) : fieldText(w)}</option>)}
      </select>
    </label>
  );
}

function Typed({ label, value, onChange, testId, width = "delivery-unit", placeholder }: {
  label: string; value: string; onChange: (v: string) => void; testId?: string; width?: string; placeholder?: string;
}) {
  return (
    <label className="delivery-pick">{label}
      <input type="text" className={width} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} data-testid={testId} />
    </label>
  );
}

/** The layout form and its reason. `spec`: the layout it starts from (an existing version, or a new table's first
 *  guess). `columns`: how many columns the table has (0: not known, the person says); `headers`: each column's header
 *  text, when known; `start`: the sheet column the table's first column is, for its letters (0: not a sheet).
 *  `findings`: what code found wrong on the last layout sent (`sent`: that layout's column numbers, in its order).
 *  `onSubmit` gets the layout written (from the form, or the text parsed) and the reason. */
export function LayoutEditor({ vocabulary, spec, columns: count, headers, start, findings, sent, busy, action, whyLabel, onSubmit,
                               onCancel, testId, whyTestId = `${testId}-save` }: {
  vocabulary: Vocabulary | null; spec: Spec; columns: number; headers?: Record<number, string>; start?: number | null;
  findings: Finding[]; sent: number[]; busy: boolean; action: string; whyLabel: string;
  onSubmit: (spec: Spec, why: string) => void | Promise<unknown>; onCancel: () => void; testId: string; whyTestId?: string;
}) {
  const [base, setBase] = useState<Spec>(spec);     // what the form does not edit comes from here
  const [table, setTable] = useState<Table>(() => tableOf(spec));
  const [cols, setCols] = useState<Column[]>(() => columnsOf(spec, count));
  const [asText, setAsText] = useState<string | null>(vocabulary ? null : JSON.stringify(spec, null, 2));
  const [textProblem, setTextProblem] = useState<string | null>(null);

  const placed = useMemo(() => findings.map((f) => ({ f, ...placeOf(f.location, sent) })), [findings, sent]);
  const at = (key: string) => placed.filter((p) => p.key === key).map((p) => p.f);
  const atColumn = (n: number) => placed.filter((p) => p.column === n).map((p) => p.f);
  const loose = placed.filter((p) => p.column === null && !p.key).map((p) => p.f);

  const setT = (key: keyof Table) => (v: string) => setTable({ ...table, [key]: v });
  const setC = (n: number, key: keyof Column) => (v: string) => setCols(cols.map((x) => (x.column === n ? { ...x, [key]: v } : x)));
  const resize = (v: string) => {
    const n = whole(v);
    if (n === null || n > 60) return;
    setCols(n > cols.length ? [...cols, ...columnsOf({}, n).slice(cols.length)] : cols.slice(0, n));
  };

  /** The text parsed, or its problem said beside it. */
  function parsed(): Spec | null {
    try {
      const out = JSON.parse(asText ?? "{}") as unknown;
      if (out && typeof out === "object" && !Array.isArray(out)) { setTextProblem(null); return out as Spec; }
      setTextProblem("The text is not a layout: write one JSON object.");
    } catch (e) {
      setTextProblem(`The text is not JSON: ${(e as Error).message}`);
    }
    return null;
  }
  function toForm() {
    const p = parsed();
    if (!p) return;
    setBase(p); setTable(tableOf(p)); setCols(columnsOf(p, count)); setAsText(null);
  }
  async function submit(why: string) {
    const out = asText !== null ? parsed() : build(base, table, cols);
    if (out) await onSubmit(out, why);
  }

  const fields = vocabulary?.fields ?? [];
  const fieldWords = fields.map((f) => f.name);
  const describeField = (name: string) => {
    const f = fields.find((x) => x.name === name);
    // its unit class beside it, unless the class is the field itself ("concentration")
    return f && f.unit_class !== "none" && f.unit_class !== name ? `${fieldText(name)} (${fieldText(f.unit_class)})` : fieldText(name);
  };
  const values = cols.filter((c) => c.role === "value");
  const kept = [
    Array.isArray(base.row_rules) && base.row_rules.length ? `${base.row_rules.length} row rules` : "",
    Array.isArray(base.keys) && base.keys.length ? `${base.keys.length} row labels` : "",
    Array.isArray(base.constants) && base.constants.length ? `${base.constants.length} facts read once for the table` : "",
  ].filter(Boolean);

  return (
    <div className="layout-editor" data-testid={testId}>
      <Said findings={loose} testId={`${testId}-findings`} />
      {asText !== null ? (
        <section>
          <textarea className="delivery-spec" aria-label="The layout as text (JSON)" value={asText} spellCheck={false} rows={14}
                    onChange={(e) => setAsText(e.target.value)}
                    data-testid="mapping-spec" />
          {textProblem && <p className="delivery-problem" role="alert">{textProblem}</p>}
          {vocabulary && <button type="button" className="link-btn" onClick={toForm} data-testid={`${testId}-form`}>Back to the form</button>}
        </section>
      ) : vocabulary && (
        <>
          <fieldset className="layout-table">
            <legend>The table</legend>
            <div className="layout-line">
              <Pick label="What it holds" value={table.kind} onChange={setT("kind")} words={vocabulary.kinds} testId={`${testId}-kind`} />
              <Pick label="Layout" value={table.layout} onChange={setT("layout")} words={vocabulary.layouts} testId={`${testId}-layout`}
                    describe={(w) => (LAYOUT_WORDS[w] ? `${fieldText(w)}: ${LAYOUT_WORDS[w]}` : fieldText(w))} />
            </div>
            <Said findings={[...at("kind"), ...at("layout")]} />
            {table.kind === "not_data" ? (
              <>
                <Typed label="Why it is not data" value={table.not_data_reason} onChange={setT("not_data_reason")} width="layout-wide"
                       testId={`${testId}-not-data`} />
                <Said findings={at("not_data_reason")} />
              </>
            ) : (
              <>
                <div className="layout-line">
                  <Typed label="Header rows" value={table.header_rows} onChange={setT("header_rows")} width="layout-num" testId={`${testId}-header-rows`} />
                  <Typed label="Data from row" value={table.first_data_row} onChange={setT("first_data_row")} width="layout-num" testId={`${testId}-first-row`} />
                  <Typed label="to row" value={table.last_data_row} onChange={setT("last_data_row")} width="layout-num" placeholder="end" />
                  {table.layout === "wide_times" && (
                    <Typed label="Times in row" value={table.time_row} onChange={setT("time_row")} width="layout-num" />
                  )}
                </div>
                <Said findings={[...at("header_rows"), ...at("first_data_row"), ...at("last_data_row"), ...at("time_row")]} />
                <div className="layout-line">
                  <Pick label="Field of the values" value={table.field} onChange={setT("field")} words={fieldWords} none="set per column"
                        describe={describeField} testId={`${testId}-field`} />
                  <Pick label="Statistic" value={table.statistic} onChange={setT("statistic")} words={vocabulary.statistics} none="not stated"
                        testId={`${testId}-statistic`} />
                  <Pick label="Times counted from" value={table.time_reference} onChange={setT("time_reference")}
                        words={vocabulary.time_references} none="not stated" />
                </div>
                <Said findings={[...at("field"), ...at("statistic"), ...at("time_reference")]} />
                <div className="layout-line">
                  <Typed label="Unit of the times" value={table.time_unit} onChange={setT("time_unit")} placeholder="as written"
                         testId={`${testId}-time-unit`} />
                  <Typed label="Unit of the values" value={table.value_unit} onChange={setT("value_unit")} placeholder="as written"
                         testId={`${testId}-value-unit`} />
                  <Typed label="Below the LLOQ written as" value={table.below_lloq} onChange={setT("below_lloq")} placeholder="e.g. BLQ" />
                  <Typed label="Missing written as" value={table.missing} onChange={setT("missing")} placeholder="e.g. NA" />
                </div>
                <Said findings={[...at("time_unit"), ...at("value_unit"), ...at("below_lloq_tokens")]} />
              </>
            )}
          </fieldset>

          {table.kind !== "not_data" && (
            <fieldset className="layout-columns">
              <legend>Each column</legend>
              <Said findings={at("columns")} testId={`${testId}-columns-findings`} />
              {count === 0 && (
                <Typed label="Columns in the table" value={String(cols.length)} onChange={resize} width="layout-num" testId={`${testId}-count`} />
              )}
              <ol className="layout-cols">
                {cols.map((c) => {
                  const said = atColumn(c.column);
                  const head = headers?.[c.column];
                  return (
                    <li key={c.column} className={said.some((f) => f.severity === "error") ? "layout-col wrong" : "layout-col"}
                        data-testid={`${testId}-col-${c.column}`}>
                      <div className="layout-col-name">
                        <strong>Column {c.column}{start ? ` (${letters(start + c.column - 1)})` : ""}</strong>
                        {head ? <span className="muted"> “{head}”</span> : null}
                      </div>
                      <div className="layout-line">
                        <Pick label="Holds" value={c.role} onChange={setC(c.column, "role")} words={vocabulary.roles} none="not read"
                              testId={`${testId}-role-${c.column}`} />
                        {c.role === "value" && (
                          <>
                            <Pick label="Field" value={c.field} onChange={setC(c.column, "field")} words={fieldWords}
                                  none={table.field ? `the table's (${fieldText(table.field)})` : "choose…"} describe={describeField}
                                  testId={`${testId}-field-${c.column}`} />
                            <Pick label="Statistic" value={c.statistic} onChange={setC(c.column, "statistic")} words={vocabulary.statistics}
                                  none={table.statistic ? "the table's" : "not stated"} />
                            <Pick label="Written as" value={c.cell_form} onChange={setC(c.column, "cell_form")} words={vocabulary.cell_forms}
                                  none="the value alone" describe={(w) => w} />
                          </>
                        )}
                        {(c.role === "value" || c.role === "time" || c.role === "lloq") && (
                          <Typed label="Unit" value={c.unit} onChange={setC(c.column, "unit")} placeholder="as written" />
                        )}
                        {(c.role === "spread" || (c.role === "value" && c.cell_form.includes("spread"))) && (
                          <Pick label="Spread" value={c.spread_kind} onChange={setC(c.column, "spread_kind")} words={vocabulary.spread_kinds}
                                none="not stated" describe={(w) => w} testId={`${testId}-spread-${c.column}`} />
                        )}
                        {QUALIFIERS.has(c.role) && (
                          <Pick label="Of the values in" value={c.of} onChange={setC(c.column, "of")} words={values.map((v) => String(v.column))}
                                none={values.length > 1 ? "choose…" : "the value column"} describe={(w) => `column ${w}`} />
                        )}
                        {c.role === "condition" && (
                          <Pick label="Condition" value={c.condition} onChange={setC(c.column, "condition")} words={vocabulary.conditions} />
                        )}
                        {c.role === "ignore" && (
                          <Typed label="Why it is not data" value={c.reason} onChange={setC(c.column, "reason")} width="layout-wide"
                                 testId={`${testId}-reason-${c.column}`} />
                        )}
                      </div>
                      <Said findings={said} testId={`${testId}-col-${c.column}-findings`} />
                    </li>
                  );
                })}
              </ol>
            </fieldset>
          )}
          {kept.length > 0 && <p className="muted fs-12 m-0">Kept as they are: {kept.join(", ")}. Edit them as text.</p>}
        </>
      )}
      {asText === null && vocabulary && (
        <button type="button" className="link-btn" data-testid={`${testId}-text`}
                onClick={() => setAsText(JSON.stringify(build(base, table, cols), null, 2))}>Edit as text</button>
      )}
      <Why action={action} label={whyLabel} busy={busy} onSubmit={submit} onCancel={onCancel} testId={whyTestId} />
    </div>
  );
}

/** The column numbers of a spec, in its order: where the findings of `columns[i]` stand. */
export const columnsSent = (spec: Spec | null): number[] =>
  (Array.isArray(spec?.columns) ? (spec.columns as Spec[]) : []).map((c) => Number(c.column));
