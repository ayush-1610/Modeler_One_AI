"use client";

// A table's layout as a form (plan 2026-11-14 §3 API 4; design "How the person fills what is missing"): what the table
// is, where its data rows are, and for each column what it holds (its role, its field with the field's unit class, its
// statistic, its spread, the value column it qualifies), every choice a select built only from the API's own words
// (`DeliveryMapping.vocabulary`, read from `modeler_intake`): nothing here is a name the web made up. Units are typed
// as the table writes them; code checks each against its header, or against the cell or caption line it is said to be
// stated in (a cite, `MappingSpec.Cite`; the time reference is always read from one). The rows told apart by a cell
// (Mean, SD, N rows: `row_rules`) are set in the form by the words the cell reads, and each fact read once for the table
// (`constants`) is kept where it is read from, read from another place, or no longer read (final review OWN-2, OWN-8: no
// one types JSON for these). What the form does not edit (label keys, a fact's pattern, a column's LLOQ or series cite)
// is kept as it is, and the whole layout stays editable as text for experts. A layout the code refuses comes back with
// its findings, each shown beside the column, the rule, the fact or the setting it names; one the form has no place for
// is said above it, so nothing the API says is lost. Fields, roles and statistics are said by their labels
// (`lib/words.ts`), never as the vocabulary's ids. A table no layout reads yet shows its first rows above the form
// (`DeliveryRegion.head`, masked as the API gives them), and each column is named by its header: the rows the form says
// are header rows.

import { useEffect, useMemo, useRef, useState } from "react";

import type { Schema } from "@/lib/api";
import { citeWords, escapePattern, layoutFieldText, layoutRoleText, patternWords, rowRoleText, tableKindText, valueWord } from "@/lib/words";

import { Why, fieldText, plural } from "./shared";

export type Vocabulary = Schema<"DeliveryMappingVocabulary">;
export type Finding = Schema<"DeliveryMappingFinding">;
/** A table's first rows, as the page gives them for a table no layout reads (`DeliveryRegion.head`). */
export type Head = Schema<"DeliveryRegionHead">;
type Spec = Record<string, unknown>;

/** Where the table states a thing read once (a unit, the time reference), as the form edits it: `at` "" (not cited: a
 *  unit is then read from the header), "cell" (its row and column in the table) or a line beside the table (a
 *  `vocabulary.cite_near` word, with its line, 1 to 3). */
type Place = { at: string; row: string; column: string; line: string };
/** A column as the form edits it; `rest` keeps what the form does not show (its other cites). Role "" leaves it unread. */
type Column = { column: number; role: string; field: string; unit: string; unit_at: Place; statistic: string; spread_kind: string;
                of: string; cell_form: string; condition: string; reason: string; rest: Spec };
/** A row rule as the form edits it: the column whose cell tells the rows apart, the words that cell reads (`words`;
 *  null for a rule written as a pattern, kept as it is), what the rows are, their spread and, left out, why. */
type Rule = { column: string; words: string | null; pattern: string; role: string; spread_kind: string; reason: string };
/** A fact read once for the table as the form edits it: where it is read from, and whether it is still read. */
type Fact = { field: string; at: Place; pattern: string | null; keep: boolean };
/** The table-wide settings the form edits. */
type Table = { kind: string; layout: string; header_rows: string; first_data_row: string; last_data_row: string; time_row: string;
               field: string; statistic: string; time_reference: string; time_reference_at: Place; time_unit: string;
               time_unit_at: Place; value_unit: string; value_unit_at: Place; below_lloq: string; missing: string;
               not_data_reason: string };

const TABLE_KEYS = ["kind", "layout", "header_rows", "first_data_row", "last_data_row", "time_row", "field", "statistic",
                    "time_reference", "time_reference_cite", "time_unit", "time_unit_cite", "value_unit", "value_unit_cite",
                    "below_lloq_tokens", "missing_tokens", "not_data_reason", "columns", "row_rules", "constants"];
const COLUMN_KEYS = ["column", "role", "field", "unit", "unit_cite", "statistic", "spread_kind", "of", "cell_form", "condition", "reason"];
// the place words of a cite beside the table (`vocabulary.cite_near`), said plainly
const NEAR_WORDS: Record<string, string> = { caption: "its caption", above: "the text above it", below: "the text below it" };
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

/** A cite of the spec as the form edits it. */
function placeOf(cite: unknown): Place {
  const c = (cite && typeof cite === "object" ? cite : {}) as Spec;
  if (c.near) return { at: text(c.near), row: "", column: "", line: text(c.line ?? 1) };
  if (c.row !== undefined && c.column !== undefined) return { at: "cell", row: text(c.row), column: text(c.column), line: "1" };
  return { at: "", row: "", column: "", line: "1" };
}

/** The cite the form says, or null: not cited, or not said in full (a cell needs its row and column). */
function citeOf(p: Place): Spec | null {
  if (p.at === "cell") {
    const row = whole(p.row), column = whole(p.column);
    return row && column ? { row, column } : null;
  }
  return p.at ? { near: p.at, line: whole(p.line) ?? 1 } : null;
}
/** A column's letters on its sheet, from the column the table starts at (1: A). */
const letters = (n: number) => { let s = ""; for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) s = String.fromCharCode(65 + ((x - 1) % 26)) + s; return s; };

/** Each column's header, by column number: the non-empty texts of the first `n` rows, joined as the API joins a
 *  mapping's headers ("Conc / (ng/mL)"). */
function headersFrom(rows: string[][], n: number): Record<number, string> {
  const out: Record<number, string> = {};
  for (const row of rows.slice(0, n)) {
    row.forEach((text, i) => { if (text.trim()) out[i + 1] = out[i + 1] && out[i + 1] !== text ? `${out[i + 1]} / ${text}` : text; });
  }
  return out;
}

/** The table's first rows above the form: its header rows (as the form says them) set apart from the rows under them,
 *  each column numbered as the form numbers it, and a merged cell drawn once over the columns it covers
 *  (`head.spans`), as the file draws it. A blinded file's: its header only, as the API gives it. */
function FirstRows({ head, headerRows, start, testId }: { head: Head; headerRows: number; start?: number | null; testId: string }) {
  const width = head.rows[0]?.length ?? 0;
  const columns = Array.from({ length: width }, (_, i) => i + 1);
  const said = head.blinded ? "Its header only, every digit masked: the file holds a blinded study's values."
    : `Its first ${plural(head.rows.length, "row")} of ${head.n_rows}${head.n_cols > width ? `, the first ${width} of its ${head.n_cols} columns` : ""}, as written.`;
  return (
    <>
      <p className="muted fs-12 m-0" data-testid={`${testId}-said`}>{said}</p>
      <div className="delivery-source-grid" role="region" aria-label="The table's first rows" tabIndex={0} data-testid={testId}>
        <table>
          <thead>
            <tr><th scope="col">Row</th>{columns.map((c) => <th key={c} scope="col">{start ? `${c} (${letters(start + c - 1)})` : c}</th>)}</tr>
          </thead>
          <tbody>
            {head.rows.map((row, i) => (
              <tr key={i}>
                <th scope="row">{i + 1}{i < headerRows ? " · header" : ""}</th>
                {row.map((text, k) => {
                  const span = head.spans[i]?.[k] ?? 1;
                  if (span === 0) return null;                  // a merged cell to its left covers this column
                  const wide = span > 1 ? span : undefined;
                  return i < headerRows ? <th key={k} colSpan={wide} title={text}>{text}</th> : <td key={k} colSpan={wide} title={text}>{text}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function tableOf(spec: Spec): Table {
  return {
    kind: text(spec.kind), layout: text(spec.layout) || "long", header_rows: text(spec.header_rows ?? 1),
    first_data_row: text(spec.first_data_row ?? 2), last_data_row: text(spec.last_data_row), time_row: text(spec.time_row),
    field: text(spec.field), statistic: text(spec.statistic), time_reference: text(spec.time_reference),
    time_reference_at: placeOf(spec.time_reference_cite), time_unit: text(spec.time_unit), time_unit_at: placeOf(spec.time_unit_cite),
    value_unit: text(spec.value_unit), value_unit_at: placeOf(spec.value_unit_cite), below_lloq: tokens(spec.below_lloq_tokens),
    missing: tokens(spec.missing_tokens), not_data_reason: text(spec.not_data_reason),
  };
}

function rulesOf(spec: Spec): Rule[] {
  return ((Array.isArray(spec.row_rules) ? spec.row_rules : []) as Spec[]).map((r) => ({
    column: text(r.column), words: patternWords(text(r.pattern)), pattern: text(r.pattern), role: text(r.role),
    spread_kind: text(r.spread_kind), reason: text(r.reason),
  }));
}

function factsOf(spec: Spec): Fact[] {
  return ((Array.isArray(spec.constants) ? spec.constants : []) as Spec[]).map((c) => ({
    field: text(c.field), at: placeOf(c.cite), pattern: c.pattern ? text(c.pattern) : null, keep: true,
  }));
}

function columnsOf(spec: Spec, count: number): Column[] {
  const mapped = new Map<number, Spec>();
  for (const c of (Array.isArray(spec.columns) ? spec.columns : []) as Spec[]) mapped.set(Number(c.column), c);
  const n = Math.max(count, ...mapped.keys(), 0);
  return Array.from({ length: n }, (_, i) => {
    const c = mapped.get(i + 1) ?? {};
    const rest = Object.fromEntries(Object.entries(c).filter(([k]) => !COLUMN_KEYS.includes(k)));
    return { column: i + 1, role: text(c.role), field: text(c.field), unit: text(c.unit), unit_at: placeOf(c.unit_cite),
             statistic: text(c.statistic), spread_kind: text(c.spread_kind), of: text(c.of), cell_form: c.cell_form === "value" ? "" : text(c.cell_form),
             condition: text(c.condition), reason: text(c.reason), rest };
  });
}

/** The spec the form says: the spec it started from, with every setting the form edits written from the form. */
function build(base: Spec, t: Table, columns: Column[], rules: Rule[], facts: Fact[]): Spec {
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
  const cites = [["time_reference", t.time_reference_at], ["time_unit", t.time_unit_at], ["value_unit", t.value_unit_at]] as const;
  for (const [key, place] of cites) {
    const cite = citeOf(place);
    if (t[key].trim() && cite) out[`${key}_cite`] = cite;
  }
  if (list(t.below_lloq).length) out.below_lloq_tokens = list(t.below_lloq);
  if (list(t.missing).length) out.missing_tokens = list(t.missing);
  out.columns = columns.filter((c) => c.role).map((c) => {
    const col: Spec = { column: c.column, role: c.role, ...c.rest };
    for (const key of ["field", "unit", "statistic", "spread_kind", "cell_form", "condition", "reason"] as const) {
      if (c[key].trim()) col[key] = c[key].trim();
    }
    if (c.of) col.of = Number(c.of);
    const cite = citeOf(c.unit_at);
    if (c.unit.trim() && cite) col.unit_cite = cite;
    return col;
  });
  // a rule written as words matches the cell whole, as written (upper or lower case alike): its words escaped
  const ruled = rules.map((r) => {
    const rule: Spec = { column: whole(r.column) ?? r.column, pattern: r.words !== null ? escapePattern(r.words.trim()) : r.pattern, role: r.role };
    if (r.role === "spread" && r.spread_kind) rule.spread_kind = r.spread_kind;
    if (r.reason.trim()) rule.reason = r.reason.trim();
    return rule;
  });
  if (ruled.length || Array.isArray(base.row_rules)) out.row_rules = ruled;
  const kept = facts.filter((f) => f.keep).map((f) => ({ field: f.field, cite: citeOf(f.at) ?? {},
                                                        ...(f.pattern ? { pattern: f.pattern } : {}) }));
  if (kept.length || Array.isArray(base.constants)) out.constants = kept;
  return out;
}

/** Where a finding stands: a column of the form (its number), a row rule or a fact of the form (`rule-<i>`, `fact-<field>`),
 *  a table-wide setting (its key), or neither (""). */
function standsAt(location: string, sent: number[]): { column: number | null; key: string } {
  const col = /^columns\[(\d+)\]/.exec(location);
  if (col) return { column: sent[Number(col[1])] ?? null, key: "" };
  const rule = /^row_rules\[(\d+)\]/.exec(location);
  if (rule) return { column: null, key: `rule-${rule[1]}` };
  const fact = /^constants\[\d+\] \(([^)]+)\)/.exec(location);
  if (fact) return { column: null, key: `fact-${fact[1]}` };
  const key = (/^[a-z_]+/.exec(location)?.[0] ?? "").replace(/_cite$/, "");
  return { column: null, key: TABLE_KEYS.includes(key) || key === "below_lloq_tokens" ? key : "" };
}

function Said({ findings, testId }: { findings: Finding[]; testId?: string }) {
  if (!findings.length) return null;
  // each finding can take focus: the first is focused when a layout comes back refused
  return (
    <ul className="delivery-findings layout-said" data-testid={testId}>
      {findings.map((f, i) => (
        <li key={`${f.code}-${i}`} className={f.severity === "error" ? "error" : undefined} tabIndex={-1}>
          <span className={`chip ${f.severity === "error" ? "high" : "medium"}`}>{f.severity === "error" ? "to fix" : "note"}</span> {f.message}
        </li>
      ))}
    </ul>
  );
}

function Pick({ label, value, onChange, words, none, testId, describe, name }: {
  label: string; value: string; onChange: (v: string) => void; words: string[];
  /** the empty choice's words; left out, a choice is required */
  none?: string; testId?: string; describe?: (word: string) => string;
  /** the accessible name, where the visible label repeats (each column's "Holds" names its column) */
  name?: string;
}) {
  return (
    <label className="delivery-pick">{label}
      <select value={value} onChange={(e) => onChange(e.target.value)} data-testid={testId} aria-label={name}>
        {none !== undefined ? <option value="">{none}</option> : !value && <option value="">choose…</option>}
        {words.map((w) => <option key={w} value={w}>{describe ? describe(w) : fieldText(w)}</option>)}
      </select>
    </label>
  );
}

function Typed({ label, value, onChange, testId, width = "delivery-unit", placeholder, name }: {
  label: string; value: string; onChange: (v: string) => void; testId?: string; width?: string; placeholder?: string; name?: string;
}) {
  return (
    <label className="delivery-pick">{label}
      <input type="text" className={width} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
             aria-label={name} data-testid={testId} />
    </label>
  );
}

/** Where the table states a thing: a cell of the table (row and column, counted in the table) or a line beside it
 *  (`near`: the vocabulary's words). `none`: the empty choice ("the header" for a unit; left out, a place is required). */
function StatedIn({ label, place, onChange, near, none, name, testId }: {
  label: string; place: Place; onChange: (p: Place) => void; near: string[]; none?: string; name: string; testId?: string;
}) {
  const set = (key: keyof Place) => (v: string) => onChange({ ...place, [key]: v });
  return (
    <span className="layout-place">
      <Pick label={label} value={place.at} onChange={set("at")} none={none} name={name} testId={testId}
            words={["cell", ...near]} describe={(w) => (w === "cell" ? "a cell of the table" : NEAR_WORDS[w] ?? fieldText(w))} />
      {place.at === "cell" && <>
        <Typed label="row" value={place.row} onChange={set("row")} width="layout-num" name={`${name}: the cell's row`} />
        <Typed label="column" value={place.column} onChange={set("column")} width="layout-num" name={`${name}: the cell's column`} />
      </>}
      {place.at && place.at !== "cell" && (
        <Pick label="line" value={place.line} onChange={set("line")} words={["1", "2", "3"]} describe={(w) => w} name={`${name}: its line`} />
      )}
    </span>
  );
}

/** The layout form and its reason. `spec`: the layout it starts from (an existing version, or a new table's first
 *  guess). `columns`: how many columns the table has (0: not known, the person says); `headers`: each column's header
 *  text, when known; `head`: the table's first rows, shown above the form, which name the columns when `headers` is not
 *  given; `start`: the sheet column the table's first column is, for its letters (0: not a sheet).
 *  `findings`: what code found wrong on the last layout sent (`sent`: that layout's column numbers, in its order).
 *  `onSubmit` gets the layout written (from the form, or the text parsed) and the reason. */
export function LayoutEditor({ vocabulary, spec, columns: count, headers, head, start, findings, sent, busy, action, whyLabel, onSubmit,
                               onCancel, testId, whyTestId = `${testId}-save` }: {
  vocabulary: Vocabulary | null; spec: Spec; columns: number; headers?: Record<number, string>; head?: Head | null; start?: number | null;
  findings: Finding[]; sent: number[]; busy: boolean; action: string; whyLabel: string;
  onSubmit: (spec: Spec, why: string) => void | Promise<unknown>; onCancel: () => void; testId: string; whyTestId?: string;
}) {
  const [base, setBase] = useState<Spec>(spec);     // what the form does not edit comes from here
  const [table, setTable] = useState<Table>(() => tableOf(spec));
  const [cols, setCols] = useState<Column[]>(() => columnsOf(spec, count));
  const [rules, setRules] = useState<Rule[]>(() => rulesOf(spec));
  const [facts, setFacts] = useState<Fact[]>(() => factsOf(spec));
  const [asText, setAsText] = useState<string | null>(vocabulary ? null : JSON.stringify(spec, null, 2));
  const [textProblem, setTextProblem] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);

  // a layout refused: its first finding takes the focus, so it is read and the dialog keeps the keyboard
  useEffect(() => {
    if (findings.length) root.current?.querySelector<HTMLElement>(".layout-said li")?.focus();
  }, [findings]);

  const form = asText === null && vocabulary !== null;
  const notData = table.kind === "not_data";
  const headerRows = whole(table.header_rows) ?? 0;
  // each column named by its header: the one given, else the table's first rows above its data (as the form says them)
  const named = headers ?? (head ? headersFrom(head.rows, headerRows) : {});
  const placed = useMemo(() => findings.map((f) => ({ f, ...standsAt(f.location, sent) })), [findings, sent]);
  const at = (key: string) => placed.filter((p) => p.key === key).map((p) => p.f);
  const atColumn = (n: number) => placed.filter((p) => p.column === n).map((p) => p.f);
  // the settings and columns the form, as it stands now, says findings beside; every other finding (all of them while
  // the layout is edited as text) is said in one list above, a column's with its number
  const beside = !form ? [] : notData ? ["kind", "layout", "not_data_reason"]
    : ["kind", "layout", "header_rows", "first_data_row", "last_data_row", "time_row", "field", "statistic", "time_reference",
       "time_unit", "value_unit", "below_lloq_tokens", "missing_tokens", "columns",
       ...rules.map((_, i) => `rule-${i}`), ...facts.filter((f) => f.keep).map((f) => `fact-${f.field}`)];
  const shownColumns = new Set(form && !notData ? cols.map((c) => c.column) : []);
  const loose = placed.filter((p) => (p.column !== null ? !shownColumns.has(p.column) : !beside.includes(p.key)))
    .map((p) => (p.column !== null ? { ...p.f, message: `Column ${p.column}: ${p.f.message}` } : p.f));

  const setT = (key: keyof Table) => (v: string) => setTable({ ...table, [key]: v });
  const setPlace = (key: "time_reference_at" | "time_unit_at" | "value_unit_at") => (p: Place) => setTable({ ...table, [key]: p });
  const setC = (n: number, key: keyof Column) => (v: string | Place) => setCols(cols.map((x) => (x.column === n ? { ...x, [key]: v } : x)));
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
    setBase(p); setTable(tableOf(p)); setCols(columnsOf(p, count)); setRules(rulesOf(p)); setFacts(factsOf(p)); setAsText(null);
  }
  async function submit(why: string) {
    const out = asText !== null ? parsed() : build(base, table, cols, rules, facts);
    if (out) await onSubmit(out, why);
  }
  const setRule = (i: number, key: keyof Rule) => (v: string) => setRules(rules.map((r, n) => (n === i ? { ...r, [key]: v } : r)));

  const fields = vocabulary?.fields ?? [];
  const fieldWords = fields.map((f) => f.name);
  const near = vocabulary?.cite_near ?? [];
  // a field by its label, with the kind of unit it takes where that helps choose one ("Dose (a mass)")
  const UNIT_CLASS: Record<string, string> = { mass: "a mass", concentration: "a concentration", time: "a time", percentage: "a percentage" };
  const describeField = (name: string) => {
    const f = fields.find((x) => x.name === name);
    const unit = f && f.unit_class !== name ? UNIT_CLASS[f.unit_class] : undefined;
    return unit ? `${layoutFieldText(name)} (${unit})` : layoutFieldText(name);
  };
  const columnName = (n: string) => `column ${n}${named[Number(n)] ? ` “${named[Number(n)]}”` : ""}`;
  const values = cols.filter((c) => c.role === "value");
  // the columns whose LLOQ, confidence level or series name the layout reads from a cell or a line (kept, not edited here)
  const cited = cols.filter((c) => ["lloq", "level", "series"].some((k) => c.rest[k])).length;
  const kept = [
    Array.isArray(base.keys) && base.keys.length ? `${base.keys.length} row labels` : "",
    base.lloq ? "where the table states its LLOQ" : "",
    cited ? `where ${cited === 1 ? "a column states its" : `${cited} columns state their`} LLOQ, confidence level or series name` : "",
  ].filter(Boolean);
  // what the form still needs before the layout is sent (the API would refuse it): said above the reason
  const needs = !form ? [] : [
    !table.kind ? "Choose what the table holds." : "",
    !notData && rules.some((r) => r.words !== null && !r.words.trim()) ? "Say the words each row rule's cell reads." : "",
    !notData && rules.some((r) => r.role === "exclude" && !r.reason.trim()) ? "Say why the rows a rule leaves out are not data." : "",
    !notData && facts.some((f) => f.keep && !citeOf(f.at)) ? "Say the cell, or the caption or the line beside the table, each fact is read from." : "",
    !notData && table.time_reference && !citeOf(table.time_reference_at)
      ? "Say where the table states when its times are counted from: a cell of the table, or its caption or the text beside it." : "",
  ].filter(Boolean);

  return (
    <div className="layout-editor" data-testid={testId} ref={root}>
      <Said findings={loose} testId={`${testId}-findings`} />
      {head && head.rows.length > 0 && <FirstRows head={head} headerRows={headerRows} start={start} testId={`${testId}-head`} />}
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
              <Pick label="What it holds" value={table.kind} onChange={setT("kind")} words={vocabulary.kinds} testId={`${testId}-kind`}
                    describe={(w) => tableKindText(w)} />
              <Pick label="Layout" value={table.layout} onChange={setT("layout")} words={vocabulary.layouts} testId={`${testId}-layout`}
                    describe={(w) => (LAYOUT_WORDS[w] ? `${fieldText(w)}: ${LAYOUT_WORDS[w]}` : fieldText(w))} />
            </div>
            <Said findings={[...at("kind"), ...at("layout")]} />
            {notData ? (
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
                        testId={`${testId}-statistic`} describe={valueWord} />
                </div>
                <Said findings={[...at("field"), ...at("statistic")]} />
                <div className="layout-line">
                  <Pick label="Times counted from" value={table.time_reference} onChange={setT("time_reference")}
                        words={vocabulary.time_references} none="not stated" testId={`${testId}-time-reference`}
                        describe={(w) => ({ first_dose: "the first dose", last_dose: "the last dose", occasion_dose: "each occasion's dose" })[w] ?? fieldText(w)} />
                  {table.time_reference && (
                    <StatedIn label="stated in" place={table.time_reference_at} onChange={setPlace("time_reference_at")} near={near}
                              name="Where the table states when its times are counted from" testId={`${testId}-time-reference-at`} />
                  )}
                </div>
                {table.time_reference && (
                  <p className="muted fs-12 m-0">Code reads when the times are counted from in the table itself: say the cell, or the
                    caption line or the line beside the table, that states it.</p>
                )}
                <Said findings={at("time_reference")} />
                <div className="layout-line">
                  <Typed label="Unit of the times" value={table.time_unit} onChange={setT("time_unit")} placeholder="as written"
                         testId={`${testId}-time-unit`} />
                  {table.time_unit.trim() && (
                    <StatedIn label="written in" place={table.time_unit_at} onChange={setPlace("time_unit_at")} near={near} none="the header"
                              name="Where the table writes the unit of the times" />
                  )}
                </div>
                <div className="layout-line">
                  <Typed label="Unit of the values" value={table.value_unit} onChange={setT("value_unit")} placeholder="as written"
                         testId={`${testId}-value-unit`} />
                  {table.value_unit.trim() && (
                    <StatedIn label="written in" place={table.value_unit_at} onChange={setPlace("value_unit_at")} near={near} none="the header"
                              name="Where the table writes the unit of the values" />
                  )}
                </div>
                <Said findings={[...at("time_unit"), ...at("value_unit")]} />
                <div className="layout-line">
                  <Typed label="Below the LLOQ written as" value={table.below_lloq} onChange={setT("below_lloq")} placeholder="e.g. BLQ"
                         testId={`${testId}-below-lloq`} />
                  <Typed label="Missing written as" value={table.missing} onChange={setT("missing")} placeholder="e.g. NA"
                         testId={`${testId}-missing`} />
                </div>
                <Said findings={[...at("below_lloq_tokens"), ...at("missing_tokens")]} />
              </>
            )}
          </fieldset>

          {!notData && (
            <fieldset className="layout-columns">
              <legend>Each column</legend>
              <Said findings={at("columns")} testId={`${testId}-columns-findings`} />
              {count === 0 && (
                <Typed label="Columns in the table" value={String(cols.length)} onChange={resize} width="layout-num" testId={`${testId}-count`} />
              )}
              <ol className="layout-cols">
                {cols.map((c) => {
                  const said = atColumn(c.column);
                  const header = named[c.column];
                  const n = `column ${c.column}`;
                  return (
                    <li key={c.column} className={said.some((f) => f.severity === "error") ? "layout-col wrong" : "layout-col"}
                        data-testid={`${testId}-col-${c.column}`}>
                      <div className="layout-col-name">
                        <strong>Column {c.column}{start ? ` (${letters(start + c.column - 1)})` : ""}</strong>
                        {header ? <span className="muted"> “{header}”</span> : null}
                      </div>
                      <div className="layout-line">
                        <Pick label="Holds" name={`What ${n} holds`} value={c.role} onChange={setC(c.column, "role")} words={vocabulary.roles}
                              none="not read" testId={`${testId}-role-${c.column}`} describe={layoutRoleText} />
                        {c.role === "value" && (
                          <>
                            <Pick label="Field" name={`Field of ${n}`} value={c.field} onChange={setC(c.column, "field")} words={fieldWords}
                                  none={table.field ? `the table's (${layoutFieldText(table.field)})` : "choose…"} describe={describeField}
                                  testId={`${testId}-field-${c.column}`} />
                            <Pick label="Statistic" name={`Statistic of ${n}`} value={c.statistic} onChange={setC(c.column, "statistic")}
                                  words={vocabulary.statistics} none={table.statistic ? "the table's" : "not stated"} describe={valueWord} />
                            {/* the empty choice is the value alone (the spec's default cell form, "value") */}
                            <Pick label="Written as" name={`How ${n} writes its values`} value={c.cell_form} onChange={setC(c.column, "cell_form")}
                                  words={vocabulary.cell_forms.filter((w) => w !== "value")} none="the value alone" describe={(w) => w} />
                          </>
                        )}
                        {(c.role === "value" || c.role === "time" || c.role === "lloq") && (
                          <Typed label="Unit" name={`Unit of ${n}`} value={c.unit} onChange={setC(c.column, "unit")} placeholder="as written" />
                        )}
                        {(c.role === "value" || c.role === "time" || c.role === "lloq") && c.unit.trim() && (
                          <StatedIn label="written in" place={c.unit_at} onChange={setC(c.column, "unit_at")} near={near} none="the header"
                                    name={`Where the table writes the unit of ${n}`} />
                        )}
                        {(c.role === "spread" || (c.role === "value" && c.cell_form.includes("spread"))) && (
                          <Pick label="Spread" name={`Spread of ${n}`} value={c.spread_kind} onChange={setC(c.column, "spread_kind")}
                                words={vocabulary.spread_kinds} none="not stated" describe={(w) => w} testId={`${testId}-spread-${c.column}`} />
                        )}
                        {QUALIFIERS.has(c.role) && (
                          <Pick label="Of the values in" name={`The value column ${n} qualifies`} value={c.of} onChange={setC(c.column, "of")}
                                words={values.map((v) => String(v.column))} none={values.length > 1 ? "choose…" : "the value column"}
                                describe={(w) => `column ${w}`} />
                        )}
                        {c.role === "condition" && (
                          <Pick label="Condition" name={`Condition ${n} states`} value={c.condition} onChange={setC(c.column, "condition")}
                                words={vocabulary.conditions} describe={layoutFieldText} />
                        )}
                        {c.role === "ignore" && (
                          <Typed label="Why it is not data" name={`Why ${n} is not data`} value={c.reason} onChange={setC(c.column, "reason")}
                                 width="layout-wide" testId={`${testId}-reason-${c.column}`} />
                        )}
                      </div>
                      <Said findings={said} testId={`${testId}-col-${c.column}-findings`} />
                    </li>
                  );
                })}
              </ol>
            </fieldset>
          )}
          {!notData && (
            <fieldset className="layout-rules" data-testid={`${testId}-rules`}>
              <legend>Rows told apart by a cell</legend>
              <p className="muted fs-12 m-0">Rows such as Mean, SD or N: say the column whose cell tells them apart and the words it reads
                (the whole cell, upper or lower case alike).</p>
              <ol className="layout-cols">
                {rules.map((r, i) => {
                  const said = at(`rule-${i}`);
                  const n = `row rule ${i + 1}`;
                  return (
                    <li key={i} className={said.some((f) => f.severity === "error") ? "layout-col wrong" : "layout-col"} data-testid={`${testId}-rule-${i}`}>
                      <div className="layout-line">
                        <Pick label="Rows whose cell in" name={`The column ${n} reads`} value={r.column} onChange={setRule(i, "column")}
                              words={cols.map((c) => String(c.column))} describe={columnName} testId={`${testId}-rule-${i}-column`} />
                        {r.words !== null ? (
                          <Typed label="reads" name={`The words ${n} matches`} value={r.words} onChange={setRule(i, "words")} placeholder="e.g. Mean"
                                 testId={`${testId}-rule-${i}-words`} />
                        ) : <span className="muted fs-12">matches a pattern (kept as it is; edit it as text)</span>}
                        <Pick label="are" name={`What the rows of ${n} are`} value={r.role} onChange={setRule(i, "role")} words={vocabulary.row_roles}
                              describe={rowRoleText} testId={`${testId}-rule-${i}-role`} />
                        {r.role === "spread" && (
                          <Pick label="Spread" name={`The spread of ${n}`} value={r.spread_kind} onChange={setRule(i, "spread_kind")}
                                words={vocabulary.spread_kinds} none="not stated" describe={(w) => w} testId={`${testId}-rule-${i}-spread`} />
                        )}
                        {r.role === "exclude" && (
                          <Typed label="Why they are not data" name={`Why the rows of ${n} are not data`} value={r.reason} onChange={setRule(i, "reason")}
                                 width="layout-wide" testId={`${testId}-rule-${i}-reason`} />
                        )}
                        <button type="button" className="link-btn" onClick={() => setRules(rules.filter((_, k) => k !== i))}
                                aria-label={`Remove ${n}`} data-testid={`${testId}-rule-${i}-remove`}>Remove</button>
                      </div>
                      <Said findings={said} testId={`${testId}-rule-${i}-findings`} />
                    </li>
                  );
                })}
              </ol>
              <button type="button" className="btn small" data-testid={`${testId}-rule-add`}
                      onClick={() => setRules([...rules, { column: "1", words: "", pattern: "", role: vocabulary.row_roles[0] ?? "exclude", spread_kind: "", reason: "" }])}>
                Add a row rule</button>
            </fieldset>
          )}
          {!notData && facts.length > 0 && (
            <fieldset className="layout-facts" data-testid={`${testId}-facts`}>
              <legend>Read once for the whole table</legend>
              <ul className="layout-cols">
                {facts.map((f, i) => {
                  const said = f.keep ? at(`fact-${f.field}`) : [];
                  const name = layoutFieldText(f.field);
                  return (
                    <li key={`${f.field}-${i}`} className={said.some((x) => x.severity === "error") ? "layout-col wrong" : "layout-col"}
                        data-testid={`${testId}-fact-${f.field}`}>
                      <div className="layout-line">
                        <label className="delivery-pick">
                          <input type="checkbox" checked={f.keep} data-testid={`${testId}-fact-${f.field}-keep`}
                                 onChange={(e) => setFacts(facts.map((x, n) => (n === i ? { ...x, keep: e.target.checked } : x)))} />
                          {name}, read from
                        </label>
                        {f.keep ? (
                          <StatedIn label="" place={f.at} near={near} name={`Where the table states ${name.toLowerCase()}`}
                                    onChange={(p) => setFacts(facts.map((x, n) => (n === i ? { ...x, at: p } : x)))} testId={`${testId}-fact-${f.field}-at`} />
                        ) : <span className="muted fs-12">not read: {citeWords(f.at.at === "cell" ? { row: f.at.row, column: f.at.column } : { near: f.at.at, line: f.at.line })} no longer gives it</span>}
                      </div>
                      <Said findings={said} testId={`${testId}-fact-${f.field}-findings`} />
                    </li>
                  );
                })}
              </ul>
            </fieldset>
          )}
          {kept.length > 0 && <p className="muted fs-12 m-0">Kept as they are: {kept.join(", ")}. Edit them as text.</p>}
        </>
      )}
      {asText === null && vocabulary && (
        <button type="button" className="link-btn" data-testid={`${testId}-text`}
                onClick={() => setAsText(JSON.stringify(build(base, table, cols, rules, facts), null, 2))}>Edit as text</button>
      )}
      {needs.map((x) => <p key={x} className="muted fs-12 m-0" data-testid={`${testId}-needs`}>{x}</p>)}
      <Why action={action} label={whyLabel} busy={busy} onSubmit={submit} onCancel={onCancel} testId={whyTestId} disabled={needs.length > 0} />
    </div>
  );
}

/** The column numbers of a spec, in its order: where the findings of `columns[i]` stand. */
export const columnsSent = (spec: Spec | null): number[] =>
  (Array.isArray(spec?.columns) ? (spec.columns as Spec[]) : []).map((c) => Number(c.column));
