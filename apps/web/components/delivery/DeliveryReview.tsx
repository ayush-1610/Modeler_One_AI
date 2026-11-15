"use client";

// A study, product or the compound as the delivery read it (contracts 2026-11-12 §8.10; plan 2026-11-14 slice 3), shown on
// its card in its area. Two modes. "confirm": the card is confirmed on the delivery, so everything a person settles on it
// is here, each with its decision and reason, in the order of the card (plan §2.1): what is to do on it, with the one line
// that says what of the delivery's clean-up holds its signature (the gate); its facts, stated or filled in (one typed
// form, with the sheet form's answers as suggestions); its values by the table they were read from; its checks, the
// values two files give differently, links between files and required items; what the loading would leave out; the
// decisions made on it so far (who, when, why); then the spot check and the signed confirmation. "read": the card is
// confirmed with the sheet form, and the delivery's reading is shown for reference, with no form. The numbers outside
// every table are settled with their file, in Client files, never here. A blinded study's values are withheld by the API
// (D-15).

import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { InlineIssue } from "@/components/kit";
import { SortHeader, TableFilter, TableMore } from "@/components/kit/SortableTable";
import { send, type Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { analyteChoices, normLabel, oneCheck } from "@/lib/inputsWork";
import { numericKey, useTableView } from "@/lib/tableView";
import {
  DISPOSITION_WORD, engineWords, fieldInText, fieldLabel, heldText, individualNeeds, individualText, landingText, placeText, rulesText, tableKindText,
  valueWord, whenText,
} from "@/lib/words";

import { ChangedSince, Decisions } from "./Decisions";
import { ConfirmDialog } from "./ConfirmDialog";
import { FactsForm, DemographicsForm, statedDemographics, type Suggestions } from "./FactsForm";
import {
  BLOCKER_LABEL, ChipFor, KIND_LABEL, MAPPING_STATE, Problem, TupleCells, WITHHELD, Why, fieldText, labelsText, levelText, plural,
  statisticText, typed, useDecide, valueText, when, type Subject, type SubjectRow, type Value,
} from "./shared";
import { SpotCheck } from "./SpotCheck";
import { ValueSource } from "./ValueSource";

type Check = Schema<"DeliveryCheck">;
type Table = Schema<"DeliveryTable">;
type Requirement = Schema<"DeliveryRequirement">;
type Link = Schema<"DeliveryLink">;
type Conflict = Schema<"DeliveryConflict">;
type Decide = ReturnType<typeof useDecide>["decide"];
export type Options = Schema<"InputsPage">["study_options"];
/** The path parameters of a card's routes. */
type CardParams = { project_id: string; type: string; subject: string };

export const SUBJECT = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;
const OVERRIDE = `${SUBJECT}:override` as const, DISPOSE = `${SUBJECT}:dispose` as const, CHOOSE = `${SUBJECT}:choose` as const;
const LINK = `${SUBJECT}:link` as const, ENTER = `${SUBJECT}:enter` as const;
const ASSIGN = "/api/v1/projects/{project_id}/delivery/values:assign" as const;
const NEW = "__new__";      // the select's "a new one" choice (never an entity's id)
// what a value is linked to besides its analyte: an assignment names them again, so only the analyte changes
const LINKED = ["study", "arm", "product", "batch"] as const;

/** The blockers of the delivery's clean-up (contracts §11.10): said once per card, as its gate line, never one by one. */
export const GATE_CODES = new Set(["SILENT_LOSS", "OUTSIDE_NUMBERS", "UNASSIGNED_VALUES"]);
// what holds a signature besides the clean-up, in a few words (the to-do rows under it say each item)
const BLOCKER_WORD: Record<string, string> = {
  SCHEMA_GAP: "facts not stated", CHECK_FAILED: "checks to decide", LINK_UNCONFIRMED: "a link between files",
  SPOT_CHECK: "the spot check", LOADED_ON_CLIENT_REVIEW: "confirmed with the sheet form already", BLINDED: "blinded until the plan is signed",
};
// the clean-up is the delivery's, not only the subject's own files (§11.10): its words say so (final review INT-8)
const GATE_WORD: Record<string, string> = {
  SILENT_LOSS: "numbers not read in the delivery's tables", OUTSIDE_NUMBERS: "loose numbers in the delivery's files",
  UNASSIGNED_VALUES: "values in the delivery's files not linked to a study or product",
};
// a check settled by its own form on the card, not by "Accept as is": a fact entered (the facts above), the item given
// its disposition (required items), a disagreement kept (the files disagree), a table layout checked (its table's head)
const FACT_CODES = new Set(["LANDING_FIELD_MISSING", "DOSE_MISSING", "MATRIX_MISSING"]);
const DISPOSED = "REQUIRED_ITEM_UNDISPOSED", MAPPED = "MAPPING_NOT_APPROVED", CONFLICT = "CONFLICT_OPEN";
const DEMOGRAPHICS = "REQ-sys.demographics";
const DISPOSITIONS: [Schema<"DeliveryDisposition">["disposition"], string][] = [
  ["ask_client", DISPOSITION_WORD.ask_client], ["literature", DISPOSITION_WORD.literature], ["not_needed", DISPOSITION_WORD.not_needed],
];
const SEVERITY = { fail: { label: "failed", tone: "high" }, warn: { label: "warning", tone: "neutral" }, info: { label: "note", tone: "neutral" } } as const;
const STATUS: Record<string, { label: string; tone: string }> = {
  confirmed: { label: "confirmed", tone: "low" }, superseded: { label: "corrected", tone: "neutral" },
  excluded: { label: "not used", tone: "neutral" },
};

type Entry = { field: string; supersedes?: string; value?: string; unit?: string };
const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const active = (v: Value) => v.status !== "superseded" && v.status !== "excluded";

/** The fact a check says the study record needs (LANDING_FIELD_MISSING "needs n, …", DOSE_MISSING, MATRIX_MISSING). */
export function checkField(c: { code: string; message: string | null }): string | null {
  if (c.code === "LANDING_FIELD_MISSING") return /needs (\w+)/.exec(c.message ?? "")?.[1] ?? null;
  return c.code === "DOSE_MISSING" ? "dose" : c.code === "MATRIX_MISSING" ? "matrix" : null;
}

/** A value a person corrects, or enters with no form (a fact no other row names), with the reason. A correction keeps
 *  the old value's time, labels and statistic. */
function Enter({ entry, busy, onSubmit, onCancel, testId }: {
  entry: Entry; busy: boolean;
  onSubmit: (body: Schema<"DeliveryEntry">) => void | Promise<unknown>; onCancel: () => void; testId: string;
}) {
  const [field, setField] = useState(entry.field);
  const [value, setValue] = useState(entry.value ?? "");
  const [unit, setUnit] = useState(entry.unit ?? "");
  return (
    <Why action={entry.supersedes ? "Correct the value" : "Enter the value"} label="Where the value comes from" busy={busy}
         placeholder="where it comes from (kept on the audit trail)" onCancel={onCancel} testId={testId}
         disabled={!value.trim() || (!entry.supersedes && !field.trim())}
         onSubmit={(why) => onSubmit({ ...(entry.supersedes ? { supersedes: entry.supersedes } : { field: field.trim() }),
                                       value: typed(value), ...(unit.trim() ? { unit: unit.trim() } : {}), why })}>
      {!entry.supersedes && (
        <label className="delivery-pick">Fact
          <input type="text" value={field} onChange={(e) => setField(e.target.value)} data-testid={`${testId}-field`} />
        </label>
      )}
      <label className="delivery-pick">Value
        <input type="text" value={value} onChange={(e) => setValue(e.target.value)} data-testid={`${testId}-value`} />
      </label>
      <label className="delivery-pick">Unit
        <input type="text" className="delivery-unit" value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="if it has one"
               data-testid={`${testId}-unit`} />
      </label>
    </Why>
  );
}

const VALUE_KEYS = {
  field: (v: Value) => v.field,
  value: (v: Value) => (v.blinded ? null : numericKey(v.value)),
  time: (v: Value) => v.time,
  level: (v: Value) => v.level,
};
const valueWords = (v: Value) => [v.field, labelsText(v), statisticText(v), v.unit ?? "", v.level, v.blinded ? "" : v.verbatim ?? ""].join(" ");

/** The subject's values of one table, with the table's layout said on its head (a layout no person approved is checked
 *  from there: its rows are not marked one by one). `oneCheck`: the one check every row needing the person comes from,
 *  when that check has its own row in Checks: the table stays folded to a line naming it (final review OWN-9). */
function ValueTable({ projectId, params, table, flagged, decide, busy, onMapping, read, oneCheck, onCheck }: {
  projectId: string; params: CardParams; table: Table; flagged: Map<string, string>; decide: Decide; busy: boolean;
  onMapping: (mappingId: string) => void; read: boolean;
  oneCheck: Check | null;
  /** go to the check's row in Checks (and open its "State it…" when it has one) */
  onCheck: (checkId: string) => void;
}) {
  const [source, setSource] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<string | null>(null);
  const marked = table.values.filter((v) => flagged.has(v.id)).length;
  // a table is folded to its one line unless one of its rows needs the person, and that need is not one check's that
  // is decided in Checks (one decision for all its rows)
  const [open, setOpen] = useState(marked > 0 && !oneCheck);
  // the subject's own label ("study 230-23") is the card's name: not said again on each of its rows
  const rows = useMemo(() => table.values.map((v) => {
    const labels = Object.fromEntries(Object.entries(v.labels).filter(([role]) => role !== params.type));
    return Object.keys(labels).length === Object.keys(v.labels).length ? v : { ...v, labels };
  }), [table.values, params.type]);
  const view = useTableView({ rows, keys: VALUE_KEYS, text: valueWords, keep: (v) => flagged.has(v.id), pageSize: 8 });
  const columns = 9;
  const title = table.kind === "facts" ? (table.file ? `Facts of ${table.file}` : "Entered by a person") : capitalized(tableKindText(table.table_kind));
  return (
    <section className="delivery-table" data-testid={`delivery-table-${table.id}`}>
      <div className="delivery-block-head">
        <button type="button" className="table-toggle" aria-expanded={open} onClick={() => setOpen(!open)} data-testid={`delivery-table-toggle-${table.id}`}
                aria-label={`${open ? "Hide" : "Show"} the ${plural(table.values.length, "value")} of the ${title.toLowerCase()}${table.file ? ` in ${table.file}` : ""}`}>
          <strong>{title}</strong></button>
        {table.kind === "table" && <span className="muted">{table.file}</span>}
        <span className="muted">{plural(table.values.length, "value")}</span>
        {marked > 0 && <span className="chip medium">{marked} to decide</span>}
        {table.mapping_id && table.mapping_status && (
          <button type="button" className="delivery-chip-btn" onClick={() => onMapping(table.mapping_id as string)}
                  data-testid={`delivery-table-mapping-${table.id}`}
                  aria-label={`Check the layout of the ${tableKindText(table.table_kind)} in ${table.file ?? "a file"}`}>
            <ChipFor state={table.mapping_status} table={MAPPING_STATE} /> table layout, version {table.mapping_version}
          </button>
        )}
        {table.waiting && <span className="chip neutral" data-testid={`delivery-table-waiting-${table.id}`}>Reading…</span>}
      </div>
      {table.mapping_status === "rejected" && (
        <InlineIssue severity="warn">Its layout was rejected: these are the values read before. They stay until the table is
          marked as not data or read with another layout.</InlineIssue>
      )}
      {oneCheck && !open && (
        <p className="table-marked-by m-0 fs-13" data-testid={`delivery-table-marked-${table.id}`}>
          {marked === table.values.length ? `All ${plural(marked, "value")}` : plural(marked, "value")} marked by one check:{" "}
          {engineWords(oneCheck.message ?? WITHHELD)}.{" "}
          {!read && <button type="button" className="link-btn" onClick={() => onCheck(oneCheck.id)} data-testid={`delivery-table-check-${table.id}`}>
            {oneCheck.code === "ANALYTE_MISSING" ? "State it…" : "Decide it in Checks"}</button>}
        </p>
      )}
      {open && <>
      {table.values.length > 8 && <TableFilter view={view} placeholder="Filter: field, label, statistic…" label="Filter these values" />}
      <div className="table-scroll">
        <table className="delivery-values">
          <caption className="sr-only">Values of {table.file ?? "a person's entries"}</caption>
          <colgroup>
            <col className="c-field" /><col className="c-value" /><col className="c-unit" /><col className="c-time" /><col />
            <col className="c-stat" /><col className="c-verbatim" /><col className="c-level" /><col className="c-source" />
          </colgroup>
          <thead><tr>
            <SortHeader view={view} col="field" label="Field" /><SortHeader view={view} col="value" label="Value" numeric /><th>Unit</th>
            <SortHeader view={view} col="time" label="Time" numeric /><th>Labels</th><th>Statistic</th><th>As written</th>
            <SortHeader view={view} col="level" label="Read by" /><th>Source</th>
          </tr></thead>
          <tbody>
            {view.visible.map((v) => (
              <Fragment key={v.id}>
                <tr data-testid={`delivery-value-${v.id}`} className={[flagged.has(v.id) ? "delivery-flagged" : "", active(v) ? "" : "delivery-set-aside"].join(" ").trim() || undefined}>
                  <td>{fieldText(v.field)}{flagged.has(v.id) && <div><span className="chip neutral" data-testid={`delivery-flag-${v.id}`}>{flagged.get(v.id)}</span></div>}</td>
                  <TupleCells v={v} />
                  <td className="delivery-verbatim">{v.blinded ? "" : v.verbatim ?? ""}</td>
                  <td>{levelText(v.level)}{v.cross_file && <div className="muted fs-12">from another file</div>}
                    {STATUS[v.status] && <div><ChipFor state={v.status} table={STATUS} /></div>}</td>
                  <td>
                    {v.anchor ? (
                      <button type="button" className="link-btn" aria-expanded={source === v.id} data-testid={`delivery-source-open-${v.id}`}
                              aria-label={`${source === v.id ? "Hide" : "Show"} the source of ${fieldText(v.field)}${v.time !== null ? ` at ${v.time}` : ""}`}
                              onClick={() => setSource(source === v.id ? null : v.id)}>{source === v.id ? "Hide" : "Show"}</button>
                    ) : <span className="muted fs-12">{v.method === "person" ? "entered" : "computed"}</span>}
                    {!read && !v.blinded && active(v) && (
                      <button type="button" className="link-btn" data-testid={`delivery-correct-${v.id}`}
                              aria-label={`Correct ${fieldText(v.field)}${v.time !== null ? ` at ${v.time}` : ""}`}
                              onClick={() => setCorrecting(correcting === v.id ? null : v.id)}>Correct</button>
                    )}
                  </td>
                </tr>
                {correcting === v.id && (
                  <tr className="delivery-source-row"><td colSpan={columns}>
                    <Enter entry={{ field: v.field, supersedes: v.id, value: v.value === null ? "" : String(v.value), unit: v.unit ?? "" }}
                           busy={busy} onCancel={() => setCorrecting(null)} testId={`correct-${v.id}`}
                           onSubmit={async (body) => { const { data } = await decide(() => send("post", ENTER, params, body)); if (data) setCorrecting(null); }} />
                  </td></tr>
                )}
                {source === v.id && (
                  <tr className="delivery-source-row"><td colSpan={columns}><ValueSource projectId={projectId} valueId={v.id} onClose={() => setSource(null)} /></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <TableMore view={view} noun="values" testId={`delivery-table-more-${table.id}`} />
      </>}
    </section>
  );
}

/** "State it…" for concentrations that name no analyte (ANALYTE_MISSING): the analyte chosen from the delivery's
 *  analytes, or a new one the person names, given to the check's values by linking them again (`values:assign`) with
 *  what they are linked to now (their study and arm, their product and batch), so that only the analyte changes and
 *  the values keep their file as their source. One link per set of values that share those; one reason for all. */
function StateAnalyte({ projectId, check, values, onDone }: {
  projectId: string; check: Check; values: Map<string, Value>; onDone: () => void;
}) {
  const page = useResource("/api/v1/projects/{project_id}/delivery", { project_id: projectId });
  const all = page.data?.enabled ? page.data.analytes : [];
  // one option per name (review OWN-11): of two analytes both called "Exampleamide", the one the study's values carry
  const used = [...new Set([...values.values()].map((v) => v.entity.analyte).filter((x): x is string => Boolean(x)))];
  const analytes = analyteChoices(all, null, used);
  const theirs = analytes.filter((a) => used.includes(a.id));
  const [picked, setAnalyte] = useState<string | null>(null);
  // the one analyte the study already uses, chosen to begin with
  const analyte = picked ?? (theirs.length === 1 ? theirs[0].id : "");
  const [named, setNamed] = useState("");
  const { decide, busy, problem } = useDecide();
  const mine = check.values.map((id) => values.get(id)).filter((v): v is Value => Boolean(v));
  const sets = new Map<string, Value[]>();
  for (const v of mine) { const k = LINKED.map((r) => v.entity[r] ?? "").join("|"); sets.set(k, [...(sets.get(k) ?? []), v]); }
  // a new analyte is never one of a name that exists (the ledger refuses it too): pick that one
  const exists = analyte === NEW ? all.find((a) => normLabel(a.label) === normLabel(named)) : undefined;
  const ready = mine.length > 0 && Boolean(analyte) && (analyte !== NEW || Boolean(named.trim()));
  async function state(why: string) {
    let chosen = analyte === NEW ? null : analyte;
    const list = [...sets.values()];
    for (const [i, group] of list.entries()) {
      const linked = Object.fromEntries(LINKED.filter((r) => group[0].entity[r]).map((r) => [r, group[0].entity[r]]));
      const { data } = await decide(() => send("post", ASSIGN, { project_id: projectId }, {
        targets: group.map((v) => v.id), why, ...linked, ...(chosen ? { analyte: chosen } : { new_analyte: named.trim() }),
      }), { refresh: i === list.length - 1 });
      if (!data) return;
      // a new analyte is named once: the next links name it by the id the delivery gave it
      chosen ??= (data as { analytes: { id: string; label: string }[] }).analytes.find((a) => a.label.trim().toLowerCase() === named.trim().toLowerCase())?.id ?? null;
      if (!chosen && i < list.length - 1) return;
    }
    onDone();
  }
  return (
    <>
      <Why action="State the analyte" label={`Why the ${plural(mine.length, "value")} are of this analyte`} busy={busy} disabled={!ready}
           missing={exists ? `An analyte named ${exists.label} exists already: pick it` : null} testId={`delivery-analyte-${check.id}`} onCancel={onDone} placeholder="where it comes from, e.g. the bioanalytical report (kept on the audit trail)"
           onSubmit={state}>
        <label className="delivery-pick">Analyte
          <select value={analyte} onChange={(e) => setAnalyte(e.target.value)} data-testid={`delivery-analyte-${check.id}-choice`}>
            <option value="">choose…</option>
            {analytes.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
            <option value={NEW}>A new analyte…</option>
          </select>
        </label>
        {analyte === NEW && (
          <input type="text" maxLength={80} value={named} onChange={(e) => setNamed(e.target.value)} placeholder="the analyte's name, as the client writes it"
                 aria-label="The new analyte's name" data-testid={`delivery-analyte-${check.id}-new`} />
        )}
      </Why>
      <Problem text={problem} testId={`delivery-analyte-problem-${check.id}`} />
    </>
  );
}

function CheckRow({ check, subject, decide, busy, onMapping, params, read, values, start }: {
  check: Check; subject: Subject; decide: Decide; busy: boolean; onMapping: (id: string) => void; params: CardParams; read: boolean;
  values: Map<string, Value>;
  /** asked from a folded table's line ("State it…"): a new number each time it is asked */
  start?: number;
}) {
  const [acting, setActing] = useState(false);
  const [stating, setStating] = useState(false);
  const row = useRef<HTMLLIElement>(null);
  // the analyte is stated by linking the values again; not while the study is blinded (its values are withheld)
  const analyte = check.code === "ANALYTE_MISSING" && !subject.blinded && check.values.some((id) => values.has(id));
  useEffect(() => {
    if (!start) return;
    if (analyte) setStating(true);
    row.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    window.setTimeout(() => row.current?.querySelector<HTMLElement>("select, input, button")?.focus(), 80);
  }, [start]); // eslint-disable-line react-hooks/exhaustive-deps
  const open = check.severity === "fail" && !check.overridden;
  const message = check.message ?? WITHHELD;
  const mapping = check.code === MAPPED ? subject.mappings.find((m) => check.message?.includes(m.mapping_id)) : undefined;
  return (
    <li ref={row} className={open ? "delivery-check open" : "delivery-check"} data-testid={`delivery-check-${check.id}`} data-code={check.code}>
      <div className="delivery-check-line">
        <span className={`chip ${check.overridden ? "neutral" : SEVERITY[check.severity].tone}`}>{check.overridden ? "accepted as is" : SEVERITY[check.severity].label}</span>
        <span className="delivery-check-text">{engineWords(message)}</span>
        {check.values.length > 0 && <span className="muted fs-12">{plural(check.values.length, "value")}, marked in the tables</span>}
        {!read && open && !acting && !stating && (
          check.code === MAPPED ? (mapping
            ? <button type="button" className="btn small" onClick={() => onMapping(mapping.mapping_id)} data-testid={`delivery-check-mapping-${check.id}`}>Check layout…</button>
            : <span className="muted fs-12">checked with its table&apos;s layout</span>)
            : <>
              {analyte && <button type="button" className="btn small" onClick={() => setStating(true)} data-testid={`delivery-analyte-open-${check.id}`}
                                  aria-label={`State the analyte: ${message}`}>State it…</button>}
              <button type="button" className="btn small" onClick={() => setActing(true)} data-testid={`delivery-override-open-${check.id}`}
                      aria-label={`Accept as is: ${message}`}>Accept as is…</button>
            </>
        )}
      </div>
      {!read && open && stating && <StateAnalyte projectId={params.project_id} check={check} values={values} onDone={() => setStating(false)} />}
      {!read && open && acting && (
        <Why action="Accept as is" label={`Why "${message}" holds as it is`} busy={busy} onCancel={() => setActing(false)}
             testId={`delivery-override-${check.id}`} placeholder="why it holds as it is (kept on the audit trail)" autoFocus
             onSubmit={async (why) => { const { data } = await decide(() => send("post", OVERRIDE, params, { check_id: check.id, why })); if (data) setActing(false); }} />
      )}
    </li>
  );
}

function ConflictRow({ conflict, values, decide, busy, params, read }: {
  conflict: Conflict; values: Map<string, Value>; decide: Decide; busy: boolean; params: CardParams; read: boolean;
}) {
  const [keep, setKeep] = useState("");
  const where = [fieldText(conflict.field), conflict.time !== null ? `at ${conflict.time}` : "", Object.entries(conflict.labels).map(([r, l]) => `${r} ${l}`).join(" · ")].filter(Boolean).join(" · ");
  return (
    <li className="delivery-check open" data-testid={`delivery-conflict-${conflict.id}`}>
      <div className="delivery-check-line">
        <span className="chip medium">To decide</span>
        <span className="delivery-check-text">{where}: the files give {conflict.kind === "unit" ? "different units" : "different values"}.{read ? "" : " Choose the one to keep; the others are not used."}</span>
      </div>
      <fieldset className="delivery-options" disabled={read}>
        <legend className="sr-only">The value to keep for {where}</legend>
        {conflict.values.map((id) => {
          const v = values.get(id);
          return (
            <label key={id}>
              <input type="radio" name={`conflict-${conflict.id}`} checked={keep === id} onChange={() => setKeep(id)} data-testid={`delivery-conflict-keep-${id}`} />
              {" "}{v ? `${valueText(v)}${v.unit ? ` ${v.unit}` : ""} · ${v.file ?? "entered by a person"}${v.blinded || !v.verbatim ? "" : ` · as written: ${v.verbatim}`}` : id}
            </label>
          );
        })}
      </fieldset>
      {!read && (
        <Why action="Keep this value" label="Why this value is kept" busy={busy} disabled={!keep} testId={`delivery-choose-${conflict.id}`}
             onSubmit={(why) => decide(() => send("post", CHOOSE, params, { conflict_id: conflict.id, keep, why }))} />
      )}
    </li>
  );
}

function LinkRow({ link, subject, decide, busy, params, read }: {
  link: Link; subject: Subject; decide: Decide; busy: boolean; params: CardParams; read: boolean;
}) {
  const [refusing, setRefusing] = useState(false);
  const [study, setStudy] = useState(link.study ?? "");
  const body = (confirmed: boolean, why: string) => ({
    file_sha256: link.file_sha256, confirmed, why, ...(link.link_fact ? { link_fact: link.link_fact } : {}), ...(study ? { study } : {}),
  });
  const key = link.id.replace(/[^A-Za-z0-9-]/g, "-");
  return (
    <li className={link.state === "refused" ? "delivery-check" : "delivery-check open"} data-testid={`delivery-link-${key}`}>
      <div className="delivery-check-line">
        <span className={`chip ${link.state === "refused" ? "neutral" : "medium"}`}>{link.state === "refused" ? "not the same study" : "To decide"}</span>
        <span className="delivery-check-text">
          <strong>{link.file}</strong> names {link.study_label ? `study ${link.study_label}` : "a study"} in its text and gives{" "}
          {subject.blinded ? "values" : plural(link.values, "value")} for it. Is it the same study as {subject.label}?
        </span>
      </div>
      {!read && link.state !== "refused" && (
        refusing ? (
          <Why action="Not the same study" label="Why the file is not about this study" busy={busy} onCancel={() => setRefusing(false)}
               testId={`delivery-link-refuse-${key}`} onSubmit={(why) => decide(() => send("post", LINK, params, body(false, why)))} />
        ) : (
          <Why action="Yes, the same study" label="A note on the link" busy={busy} optional testId={`delivery-link-confirm-${key}`}
               disabled={link.state === "ambiguous" && !study}
               onSubmit={(why) => decide(() => send("post", LINK, params, body(true, why)))}>
            {link.state === "ambiguous" && (
              <label className="delivery-pick">Study
                <select value={study} onChange={(e) => setStudy(e.target.value)} data-testid={`delivery-link-study-${key}`}>
                  <option value="">choose the study</option>
                  {link.candidates.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                </select>
              </label>
            )}
            <button type="button" className="btn small" disabled={busy} onClick={() => setRefusing(true)} data-testid={`delivery-link-refuse-open-${key}`}>No…</button>
          </Why>
        )
      )}
    </li>
  );
}

/** A required item no file gives: recorded as asked of the client, taken from the literature or not needed; the
 *  demographics a person has can be entered instead ("Enter them…", through `:enter`). Found demographics say the
 *  study's individual they make (D-29), or what it still needs, with "Choose the individual…": one truth with what
 *  loads and with Populations and individuals (`DeliverySubject.individual`). */
function RequirementRow({ item, decide, busy, params, read, projectId, vocabulary, stated, individual, options }: {
  item: Requirement; decide: Decide; busy: boolean; params: CardParams; read: boolean; projectId: string;
  vocabulary: { mapping: string | null };
  /** the demographics stated already (a person's corrected, never entered twice; a file's shown as read) */
  stated: Record<string, Value>;
  individual: Schema<"DeliveryIndividual"> | null;
  options: { population: string[]; sex: string[] } | null;
}) {
  const [disposition, setDisposition] = useState<Schema<"DeliveryDisposition">["disposition"]>("ask_client");
  const [entering, setEntering] = useState(false);
  // a disposition is the item's status ("ask_client"); `disposition` is the decision's id
  const said = DISPOSITION_WORD[item.status];
  const open = item.status === "missing" && !item.disposition;
  const demographics = item.req_id === DEMOGRAPHICS;
  const unset = demographics && !open && individual !== null && !individual.demographics && individual.stated.length > 0;
  return (
    <li className={open ? "delivery-check open" : "delivery-check"} data-testid={`delivery-requirement-${item.req_id}`}>
      <div className="delivery-check-line">
        <span className={`chip ${open ? "high" : item.status === "found" ? "low" : "neutral"}`}>
          {open ? "Missing" : said ? "Settled" : item.status === "found" ? "Done" : valueWord(item.status)}</span>
        <span className="delivery-check-text">{item.label}</span>
        <span className="muted fs-12">{item.criticality.toLowerCase()}{said ? ` · ${said}` : ""}</span>
        {!read && open && item.req_id === DEMOGRAPHICS && !entering && (
          <button type="button" className="btn small" onClick={() => setEntering(true)} data-testid={`delivery-demographics-open-${params.subject}`}>Enter them…</button>
        )}
      </div>
      {demographics && individual?.demographics && (
        <p className="m-4-0-0 fs-13" data-testid={`delivery-individual-${params.subject}`}>
          <span className="muted">The study&apos;s individual, which loads with it:</span> {individualText(individual.demographics)}
          {individual.kept.length > 0 && <span className="muted"> · {individual.kept.map(fieldInText).join(", ")} kept, not simulated</span>}
          {!read && !open && !entering && <> <button type="button" className="link-btn" onClick={() => setEntering(true)}
                                                     data-testid={`delivery-demographics-open-${params.subject}`}
                                                     aria-label="Correct the demographics or the individual">Correct…</button></>}
        </p>
      )}
      {unset && individual && (
        <p className="m-4-0-0 fs-13" data-testid={`delivery-individual-${params.subject}`}>
          <span className="chip high">Not simulated yet</span> {capitalized(individualNeeds(individual.needs, individual.why))}.
          {!read && !entering && <> <button type="button" className="btn small" onClick={() => setEntering(true)}
                                            data-testid={`delivery-demographics-open-${params.subject}`}>Choose the individual…</button></>}
        </p>
      )}
      {!read && (open || (demographics && individual !== null)) && entering && (
        <DemographicsForm projectId={projectId} params={params} vocabulary={vocabulary} options={options} onDone={() => setEntering(false)}
                          testId={`delivery-demographics-${params.subject}`} stated={stated} />
      )}
      {!read && open && !entering && (
        <Why action="Record it" label={`Why ${item.label} is settled this way`} busy={busy} testId={`delivery-dispose-${item.req_id}`}
             onSubmit={(why) => decide(() => send("post", DISPOSE, params, { req_id: item.req_id, disposition, why }))}>
          <label className="delivery-pick">It is
            <select value={disposition} onChange={(e) => setDisposition(e.target.value as typeof disposition)} data-testid={`delivery-dispose-${item.req_id}-choice`}>
              {DISPOSITIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
        </Why>
      )}
    </li>
  );
}

// the labels a fact is stated for that are said bare (the thing itself); the others with their role ("period 2")
const BARE = new Set(["analyte", "matrix", "arm", "product", "batch"]);
/** What a fact is stated for, besides the subject itself, as its files write it: "Exampleamide-M1, plasma" for an LLOQ. */
function factLabels(v: Value, own: string): string {
  // the subject's own label and the fact's own (an analyte fact's analyte) are not said again
  return Object.entries(v.labels).filter(([role]) => role !== own && role !== v.field)
    .map(([role, label]) => (BARE.has(role) ? label : `${role} ${label}`)).join(", ");
}

/** The facts stated for the subject, one row per fact (its files' facts and a person's entries), each correctable. */
function StatedFacts({ projectId, params, values: all, flagged, decide, busy, read }: {
  projectId: string; params: CardParams; values: Value[]; flagged: Map<string, string>; decide: Decide; busy: boolean; read: boolean;
}) {
  const [source, setSource] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<string | null>(null);
  // each fact once: two files that state the same value of the same thing (its analyte, matrix, arm…) are one row; the
  // subject's own name (its id, its label) is the card's title, not said again
  const own = params.type === "study" ? "study_id" : params.type;
  const seen = new Set<string>();
  const values = all.filter((v) => {
    if (v.field === own) return false;
    const key = `${v.field}|${factLabels(v, params.type)}|${v.blinded ? v.id : `${String(v.value)}|${v.unit ?? ""}`}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  // the facts of one field together (two analytes, then their two LLOQs), in the order the fields first appear
  const order = [...new Set(values.map((v) => v.field))];
  values.sort((a, b) => order.indexOf(a.field) - order.indexOf(b.field));
  if (!values.length) return null;
  return (
    <dl className="delivery-facts subject-facts">
      {values.map((v, i) => (
        <Fragment key={v.id}>
          <dt>{i > 0 && values[i - 1].field === v.field ? "" : fieldLabel(v.field)}</dt>
          <dd data-testid={`delivery-fact-${v.id}`}>
            <span className={v.blinded ? "delivery-withheld-cell" : undefined}>
              {v.blinded ? WITHHELD : typeof v.value === "string" ? valueWord(v.value) : valueText(v)}{v.unit ? ` ${v.unit}` : ""}</span>
            {factLabels(v, params.type) && <span className="fact-labels"> · {factLabels(v, params.type)}</span>}
            {" "}<span className="muted fs-12">{v.method === "person" ? "entered by a person" : v.file ? `from ${v.file}` : ""}</span>
            {flagged.has(v.id) && <> <span className="chip neutral">{flagged.get(v.id)}</span></>}
            {v.anchor && (
              <button type="button" className="link-btn" aria-expanded={source === v.id} onClick={() => setSource(source === v.id ? null : v.id)}
                      data-testid={`delivery-source-open-${v.id}`} aria-label={`${source === v.id ? "Hide" : "Show"} the source of ${fieldLabel(v.field)}`}>
                {source === v.id ? "Hide the source" : "Source"}</button>
            )}
            {!read && !v.blinded && (
              <button type="button" className="link-btn" onClick={() => setCorrecting(correcting === v.id ? null : v.id)}
                      data-testid={`delivery-correct-${v.id}`} aria-label={`Correct ${fieldLabel(v.field)}`}>Correct</button>
            )}
            {correcting === v.id && (
              <Enter entry={{ field: v.field, supersedes: v.id, value: v.value === null ? "" : String(v.value), unit: v.unit ?? "" }}
                     busy={busy} onCancel={() => setCorrecting(null)} testId={`correct-${v.id}`}
                     onSubmit={async (body) => { const { data } = await decide(() => send("post", ENTER, params, body)); if (data) setCorrecting(null); }} />
            )}
            {source === v.id && <ValueSource projectId={projectId} valueId={v.id} onClose={() => setSource(null)} />}
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}

/** A section of the card, its heading in the card's words. */
function Section({ title, testId, children, aside }: { title: string; testId?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="delivery-block card-section" data-testid={testId}>
      <div className="delivery-block-head"><h3>{title}</h3>{aside}</div>
      {children}
    </section>
  );
}

export type Gate = {
  /** what of the delivery's clean-up holds the signature, counted from the one list of work ("10 table layouts to
   *  check · 6 files to link"), or null when the list has not counted it */
  text: string | null;
  /** open To do on the clean-up */
  onOpen: () => void;
};

/** The card of the delivery subject `row`: its own review (`mode` "confirm") or the delivery's reading shown for
 *  reference (`mode` "read"). The card frame passes what is its own: what is to do on it (`todo`), the sheet form's
 *  answers as suggestions, the observed data, the other confirm path and the other reader's view. */
export function DeliveryReview({ projectId, row, mode, gate, onMapping, todo, suggestions, observed, sheetPath, howRead }: {
  projectId: string; row: SubjectRow; mode: "confirm" | "read"; gate?: Gate | null;
  onMapping: (mappingId: string) => void;
  /** the open items of the card in the one list of work, as links into the card */
  todo?: ReactNode;
  suggestions?: Suggestions;
  observed?: ReactNode;
  /** "Confirm now with the sheet form" and its warning, beside "Confirm and sign" (plan 2026-11-14 §2.2.1); `gated`:
   *  the delivery's clean-up holds the signature now */
  sheetPath?: (gated: boolean) => ReactNode;
  /** the other reader's view of the same data, folded and read-only */
  howRead?: ReactNode;
}) {
  const params = { project_id: projectId, type: row.subject_type, subject: row.subject };
  const read = useResource(SUBJECT, params, { poll: (d) => d.tables.some((t) => t.waiting) || d.mappings.some((m) => m.waiting) });
  const inputs = useResource("/api/v1/projects/{project_id}/inputs", { project_id: projectId });
  const { decide, busy, problem } = useDecide();
  const [confirming, setConfirming] = useState(false);
  const [entering, setEntering] = useState(false);
  const [notes, setNotes] = useState(false);
  // a check asked from a folded table's line, and when (each ask opens it again)
  const [asked, setAsked] = useState<{ id: string; at: number } | null>(null);
  const s = read.data;
  const looking = mode === "read";

  const values = useMemo(() => new Map((s?.tables ?? []).flatMap((t) => t.values).map((v) => [v.id, v] as const)), [s]);
  // the rows that need the person: named by a failed check not accepted as is, or by an open conflict; a table layout no
  // person approved is said on its table's head, never on each of its rows
  const flagged = useMemo(() => {
    const out = new Map<string, string>();
    for (const c of s?.checks ?? []) {
      if (c.severity === "fail" && !c.overridden && c.code !== MAPPED) for (const id of c.values) out.set(id, "a check failed");
    }
    for (const c of s?.conflicts ?? []) for (const id of c.values) out.set(id, "differs between files");
    return out;
  }, [s]);

  if (read.problem) return <Problem text={read.problem} />;
  if (!s) return <p className="muted m-0" data-testid={`delivery-card-reading-${row.subject}`}>Reading the card…</p>;

  const options = inputs.data?.study_options ?? null;
  const failing = s.checks.filter((c) => c.severity === "fail" && !c.overridden);
  const factChecks = failing.filter((c) => FACT_CODES.has(c.code));
  const layoutsWaiting = new Set(s.mappings.filter((m) => m.status === "proposed").map((m) => m.mapping_id));
  // the failed checks said in their own section: not a fact (above), a required item or a disagreement (their own
  // forms), nor a layout still to approve (its table's head)
  const own = (c: Check) => !FACT_CODES.has(c.code) && c.code !== DISPOSED && c.code !== CONFLICT
    && !(c.code === MAPPED && [...layoutsWaiting].some((id) => c.message?.includes(id)));
  const checks = failing.filter(own);
  const others = s.checks.filter((c) => !(c.severity === "fail" && !c.overridden));
  const c = s.confirmation;
  const done = Boolean(c && c.current && c.landed);
  const levels = Object.entries(s.by_level).map(([level, n]) => `${n} ${levelText(level)}`).join(", ");
  const gated = s.blockers.filter((b) => GATE_CODES.has(b.code));
  const blockers = s.blockers.filter((b) => !GATE_CODES.has(b.code));
  const facts = s.tables.filter((t) => t.kind === "facts").flatMap((t) => t.values).filter(active);
  const tables = s.tables.filter((t) => t.kind === "table");
  // the one check every row of a table that needs the person comes from, when it has its own row in Checks: the table
  // stays one line naming it (OWN-9)
  const oneCheckOf = (t: Table): Check | null => oneCheck(t.values, (id) => flagged.has(id), checks, s.conflicts);
  // a table layout is checked from its table's head; listed apart only when no table on the card shows it
  const unheaded = s.mappings.filter((m) => !tables.some((t) => t.mapping_id === m.mapping_id && t.mapping_version === m.version && t.mapping_status));
  const vocabulary = { mapping: s.tables.find((t) => t.mapping_id)?.mapping_id ?? s.mappings[0]?.mapping_id ?? null };
  const gateLine = gated.length > 0 && (
    <p className="card-gate" data-testid={`delivery-gate-${s.subject}`} data-codes={gated.map((b) => b.code).join(" ")}>
      <strong>Waits for the delivery clean-up:</strong>{" "}
      {gate?.text || gated.map((b) => GATE_WORD[b.code]).join(" · ")}.{" "}
      {gate && <button type="button" className="link-btn" onClick={gate.onOpen} data-testid={`delivery-gate-open-${s.subject}`}>Open in To do</button>}
    </p>
  );

  return (
    <div className={`delivery-card${looking ? " reading" : ""}`} data-testid={`delivery-card-${s.subject}`} data-mode={mode}>
      <p className="muted m-0 fs-13" data-testid={`delivery-card-counts-${s.subject}`}>
        {KIND_LABEL[s.subject_type]} {s.label}: {plural(s.values, "value")} read from the files{levels ? ` (${levels})` : ""}
        {s.silent_loss ? ` · ${plural(s.silent_loss, "number")} in the delivery's files not read` : ""} · {rulesText(s.rules)}
      </p>
      {s.blinded && <p className="delivery-withheld" data-testid={`delivery-blinded-${s.subject}`}>{WITHHELD}: this study is blinded until
        the plan is signed. Its values, their spread and what is below the LLOQ are not shown, and it waits to be confirmed until then.</p>}
      {looking && s.confirm_on === "client-review" && <InlineIssue severity="note" testId={`delivery-confirm-on-${s.subject}`}>A filled
        client-data template: it is confirmed with the sheet form, on this card. What the delivery read is shown here for reference.</InlineIssue>}
      {/* the same source read with the sheet form: confirmed there (in the model), or only read there, not confirmed yet */}
      {s.loaded_elsewhere.length > 0 && <InlineIssue severity="note" testId={`delivery-loaded-elsewhere-${s.subject}`}>
        {plural(s.loaded_elsewhere.length, "dataset")} of the same source {s.loaded_elsewhere.length === 1 ? "is" : "are"} in the model
        already, confirmed with the sheet form. Nothing is loaded twice.</InlineIssue>}
      {s.proposed_elsewhere.length > 0 && <InlineIssue severity="note" testId={`delivery-proposed-elsewhere-${s.subject}`}>
        {plural(s.proposed_elsewhere.length, "dataset")} of the same source {s.proposed_elsewhere.length === 1 ? "was" : "were"} read with
        the sheet form, not confirmed yet: whichever is confirmed first is what loads.</InlineIssue>}

      {!looking && (
        <Section title={`To do on this ${KIND_LABEL[s.subject_type].toLowerCase()}`} testId={`delivery-todo-${s.subject}`}>
          {gateLine}
          {blockers.length > 0 ? (
            <p className="card-blockers m-0" data-testid={`delivery-blockers-${s.subject}`}>
              <span className="muted">Before it can be signed: </span>
              {blockers.map((b, i) => (
                <Fragment key={`${b.code}-${i}`}>{i > 0 && " · "}
                  <span data-testid={`delivery-blocker-${b.code}`} title={engineWords(b.detail)}>{BLOCKER_WORD[b.code] ?? BLOCKER_LABEL[b.code] ?? valueWord(b.code)}</span>
                </Fragment>
              ))}
            </p>
          ) : !done && !gated.length && <p className="banner ok" data-testid={`delivery-ready-${s.subject}`}>Nothing holds its confirmation.</p>}
          {todo ?? (blockers.length > 0 && <ul className="plain-list">{blockers.map((b, i) => <li key={`${b.code}-${i}`}>{engineWords(b.detail)}</li>)}</ul>)}
        </Section>
      )}
      <Problem text={problem} testId={`delivery-card-problem-${s.subject}`} />

      <Section title="Facts" testId={`delivery-facts-${s.subject}`}
               aside={!looking && !entering && !s.blinded ? <button type="button" className="link-btn" onClick={() => setEntering(true)}
                                                                    data-testid={`delivery-enter-open-${s.subject}`}>Enter another fact…</button> : null}>
        <StatedFacts projectId={projectId} params={params} values={facts} flagged={flagged} decide={decide} busy={busy} read={looking} />
        {facts.length === 0 && !s.gaps.length && !factChecks.length && <p className="muted m-0">No fact of the {KIND_LABEL[s.subject_type].toLowerCase()} is stated in its files.</p>}
        {(s.gaps.length > 0 || factChecks.length > 0) && (
          <FactsForm params={params} gaps={s.gaps} checks={factChecks} options={options} suggestions={suggestions}
                     read={looking} testId={`delivery-facts-form-${s.subject}`}
                     stated={new Set([...values.values()].filter((v) => active(v) && v.value !== null).map((v) => v.field))} />
        )}
        {entering && (
          <Enter entry={{ field: "" }} busy={busy} onCancel={() => setEntering(false)} testId={`delivery-enter-${s.subject}`}
                 onSubmit={async (body) => { const { data } = await decide(() => send("post", ENTER, params, body)); if (data) setEntering(false); }} />
        )}
      </Section>

      {observed}

      <Section title="Files and tables" testId={`delivery-values-${s.subject}`}>
        {unheaded.length > 0 && (
          <ul className="delivery-plain" data-testid={`delivery-card-mappings-${s.subject}`}>
            {unheaded.map((m) => (
              <li key={`${m.mapping_id}-${m.version}`} className={m.status === "proposed" && !looking ? "delivery-check open" : "delivery-check"}>
                <div className="delivery-check-line">
                  <ChipFor state={m.status} table={MAPPING_STATE} />
                  <span className="delivery-check-text">{capitalized(tableKindText(m.kind))}, version {m.version}: {m.used_in.map((u) => `${u.file} (${placeText(u.where)})`).join("; ")}</span>
                  {m.waiting && <span className="chip neutral">Reading…</span>}
                  <button type="button" className="btn small" onClick={() => onMapping(m.mapping_id)} data-testid={`delivery-card-mapping-${m.mapping_id}`}
                          aria-label={`Check the layout of the ${tableKindText(m.kind)} in ${m.used_in[0]?.file ?? "no file"}`}>Check layout…</button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {tables.length === 0 && <p className="muted m-0">No table of its files gave a value yet.</p>}
        {tables.map((t) => <ValueTable key={t.id} projectId={projectId} params={params} table={t} flagged={flagged} decide={decide} busy={busy}
                                       onMapping={onMapping} read={looking} oneCheck={oneCheckOf(t)}
                                       onCheck={(id) => setAsked({ id, at: Date.now() })} />)}
      </Section>

      {(s.checks.length > 0 || s.conflicts.length > 0 || s.links.length > 0 || s.requirements.length > 0) && (
        <Section title="Checks" testId={`delivery-checks-${s.subject}`}
                 aside={<span className="muted fs-13">{checks.length + s.conflicts.length ? `${checks.length + s.conflicts.length} to decide` : "none failed"}</span>}>
          {checks.length > 0 && (
            <ul className="delivery-plain">
              {checks.map((check) => <CheckRow key={check.id} check={check} subject={s} decide={decide} busy={busy} onMapping={onMapping} params={params}
                                               read={looking} values={values} start={asked?.id === check.id ? asked.at : undefined} />)}
            </ul>
          )}
          {s.conflicts.length > 0 && (
            <div data-testid={`delivery-conflicts-${s.subject}`}>
              <h4 className="delivery-sub">The files disagree</h4>
              <ul className="delivery-plain">{s.conflicts.map((x) => <ConflictRow key={x.id} conflict={x} values={values} decide={decide} busy={busy} params={params} read={looking} />)}</ul>
            </div>
          )}
          {s.links.length > 0 && (
            <div data-testid={`delivery-links-${s.subject}`}>
              <h4 className="delivery-sub">Links between files</h4>
              <ul className="delivery-plain">{s.links.map((x) => <LinkRow key={x.id} link={x} subject={s} decide={decide} busy={busy} params={params} read={looking} />)}</ul>
            </div>
          )}
          {s.requirements.length > 0 && (
            <div data-testid={`delivery-requirements-${s.subject}`}>
              <h4 className="delivery-sub">What the data plan needs from this {KIND_LABEL[s.subject_type].toLowerCase()}</h4>
              <ul className="delivery-plain">{s.requirements.map((x) => <RequirementRow key={x.req_id} item={x} decide={decide} busy={busy} params={params}
                                                                                     read={looking} projectId={projectId} vocabulary={vocabulary}
                                                                                     stated={statedDemographics([...values.values()])}
                                                                                     individual={s.individual ?? null}
                                                                                     options={options ? { population: options.population ?? [], sex: options.sex ?? [] } : null} />)}</ul>
            </div>
          )}
          {others.length > 0 && (
            <>
              <button type="button" className="link-btn" aria-expanded={notes} onClick={() => setNotes(!notes)} data-testid={`delivery-checks-more-${s.subject}`}>
                {notes ? "Hide" : "Show"} {plural(others.length, "more check")} (warnings, notes and checks accepted as is)</button>
              {notes && <ul className="delivery-plain">{others.map((check) => <CheckRow key={check.id} check={check} subject={s} decide={decide} busy={busy}
                                                                                         onMapping={onMapping} params={params} read values={values} />)}</ul>}
            </>
          )}
        </Section>
      )}

      <Section title={`Not loaded with this ${KIND_LABEL[s.subject_type].toLowerCase()}`} testId={`delivery-held-${s.subject}`}>
        {/* why the delivery's reading cannot be loaded matters only where it is confirmed on the delivery */}
        {s.landing_problem && !looking && <InlineIssue severity="error" testId={`delivery-landing-problem-${s.subject}`}>It cannot be loaded yet: {landingText(s.landing_problem, s.label)} (fill in the facts above).</InlineIssue>}
        {s.held === null ? <p className="delivery-withheld">{WITHHELD}</p>
          : s.held.length === 0 ? ((looking || !s.landing_problem) && <p className="muted m-0">Nothing: every value that can be loaded is loaded.</p>)
            : <ul className="flags">{s.held.map((h) => <li key={h}>{heldText(h, s.label)}</li>)}</ul>}
      </Section>

      {!looking && <Decisions subject={s} />}

      {!looking && <SpotCheck projectId={projectId} subject={s} />}

      {!looking && (
        <section className="delivery-block delivery-confirmation card-section" data-testid={`delivery-confirmation-${s.subject}`}>
          <div className="delivery-block-head">
            <h3>Confirm and sign</h3>
            {c && <span className={`chip ${done ? "low" : "medium"}`}>{!c.current ? "Changed since signed: confirm again" : c.landed ? "Done" : "signed, not loaded yet"}</span>}
          </div>
          {c ? (
            <>
              <p className="m-0">Signed by {c.printed_name || c.by}, {whenText(c.at)}: <strong data-testid={`delivery-manifestation-${s.subject}`}>{c.manifestation}</strong></p>
              <p className="muted fs-12 m-4-0-0">
                {c.landed ? `In the model since ${when(c.landed.at)}: ${plural(c.landed.datasets.length, "dataset")}, ${plural(c.landed.evidence.length, "value")}`
                  + (c.landed.dissolution_records ? `, ${plural(c.landed.dissolution_records, "dissolution record")}` : "")
                  + (c.landed.rejected_legacy.length ? ` · ${plural(c.landed.rejected_legacy.length, "earlier reading")} of the same source not used` : "") : "Not loaded yet."}
                {" "}· record {c.record_sha256.slice(0, 12)}{c.rules ? ` · ${rulesText(c.rules)}` : ""}
              </p>
              {c.held && c.held.length > 0 && <ul className="flags">{c.held.map((h) => <li key={h}>{heldText(h, s.label)}</li>)}</ul>}
              <ChangedSince subject={s} />
            </>
          ) : <p className="muted m-0">Not confirmed yet. Your signature binds what this card shows, and its values are then loaded into the model.</p>}
          {s.confirm_on === "delivery" && !done && (
            <div className="confirm-paths">
              <button type="button" className="btn primary" onClick={() => setConfirming(true)} data-testid={`delivery-confirm-${s.subject}`}
                      disabled={gated.length > 0 && !(c && c.current && !c.landed)}
                      aria-describedby={gated.length ? `delivery-gate-why-${s.subject}` : undefined}>
                {c && !c.landed && c.current ? "Finish the loading…" : c ? "Confirm again and sign…" : "Confirm and sign…"}</button>
              {gated.length > 0 && <span className="muted fs-13" id={`delivery-gate-why-${s.subject}`}>Waits for the delivery clean-up (above).</span>}
              {sheetPath?.(gated.length > 0)}
            </div>
          )}
        </section>
      )}
      {howRead}
      {confirming && <ConfirmDialog projectId={projectId} subject={s} onClose={() => setConfirming(false)} />}
    </div>
  );
}
