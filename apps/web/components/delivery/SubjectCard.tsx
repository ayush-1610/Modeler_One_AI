"use client";

// One subject of a delivery, reviewed by exception (contracts 2026-11-12 §8.10): what blocks its confirmation first
// (numbers outside every table, facts not stated, failed checks, values two files give differently, links between
// files, required items, mappings no person approved), each with the decision that settles it and the reason the
// decision needs; then its values by the table they were read from, each opening its source; what the landing would
// hold back; the spot check; and the signed confirmation. Rows a failed check or an open conflict names are never paged
// or filtered out of their table (`useTableView`'s `keep`). A blinded study's values are withheld by the API (D-15).

import { Fragment, useMemo, useState } from "react";

import { InlineIssue } from "@/components/kit";
import { SortHeader, TableFilter, TableMore } from "@/components/kit/SortableTable";
import { send, type Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { numericKey, useTableView } from "@/lib/tableView";

import { ConfirmDialog } from "./ConfirmDialog";
import {
  BLOCKER_LABEL, ChipFor, KIND_LABEL, MAPPING_STATE, Problem, TupleCells, WITHHELD, Why, fieldText, labelsText, levelText, plural,
  statisticText, timeText, typed, useDecide, valueText, when, type Page, type Subject, type SubjectRow, type Value,
} from "./shared";
import { SpotCheck } from "./SpotCheck";
import { ValueSource } from "./ValueSource";

type Check = Schema<"DeliveryCheck">;
type Table = Schema<"DeliveryTable">;
type Requirement = Schema<"DeliveryRequirement">;
type Link = Schema<"DeliveryLink">;
type Conflict = Schema<"DeliveryConflict">;
type Decide = ReturnType<typeof useDecide>["decide"];
type Options = Schema<"InputsPage">["study_options"];
/** The path parameters of a card's routes. */
type CardParams = { project_id: string; type: string; subject: string };

const SUBJECT = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;
const OVERRIDE = `${SUBJECT}:override` as const, DISPOSE = `${SUBJECT}:dispose` as const, CHOOSE = `${SUBJECT}:choose` as const;
const LINK = `${SUBJECT}:link` as const, ENTER = `${SUBJECT}:enter` as const;
const EXCLUDE = "/api/v1/projects/{project_id}/delivery/regions:exclude" as const;

// a check that is settled by its own decision, not by an override: the value is entered, the item is given its
// disposition, the mapping is reviewed
const ENTERED = "LANDING_FIELD_MISSING", DISPOSED = "REQUIRED_ITEM_UNDISPOSED", MAPPED = "MAPPING_NOT_APPROVED";
// the Inputs page's choices for a study's facts, offered as suggestions for the same facts entered here
const SUGGEST: Record<string, string> = { route: "route", formulation: "formulation", food_state: "food_state", intended_use: "purpose" };
const DISPOSITIONS: [Schema<"DeliveryDisposition">["disposition"], string][] = [
  ["ask_client", "asked of the client"], ["literature", "taken from the literature"], ["not_needed", "not needed for this model"],
];
const SEVERITY = { fail: { label: "failed", tone: "high" }, warn: { label: "warning", tone: "medium" }, info: { label: "note", tone: "neutral" } } as const;
const STATUS: Record<string, { label: string; tone: string }> = {
  confirmed: { label: "confirmed", tone: "low" }, superseded: { label: "superseded", tone: "neutral" },
  excluded: { label: "set aside", tone: "neutral" },
};

type Entry = { field: string; supersedes?: string; value?: string; unit?: string };

/** A value a person enters or corrects, with the reason. A correction keeps the old value's time, labels and statistic. */
function Enter({ entry, options, busy, onSubmit, onCancel, testId }: {
  entry: Entry; options: Options | null; busy: boolean;
  onSubmit: (body: Schema<"DeliveryEntry">) => void | Promise<unknown>; onCancel: () => void; testId: string;
}) {
  const [field, setField] = useState(entry.field);
  const [value, setValue] = useState(entry.value ?? "");
  const [unit, setUnit] = useState(entry.unit ?? "");
  const choices = options?.[SUGGEST[field] ?? ""] ?? [];
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
        <input type="text" value={value} onChange={(e) => setValue(e.target.value)} list={choices.length ? `${testId}-choices` : undefined}
               data-testid={`${testId}-value`} />
      </label>
      {choices.length > 0 && <datalist id={`${testId}-choices`}>{choices.map((c) => <option key={c} value={c} />)}</datalist>}
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

/** The subject's values of one table, or its facts of one file. */
function ValueTable({ projectId, params, table, flagged, options, decide, busy, onMapping }: {
  projectId: string; params: CardParams; table: Table; flagged: Map<string, string>; options: Options | null; decide: Decide;
  busy: boolean; onMapping: (mappingId: string) => void;
}) {
  const [source, setSource] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<string | null>(null);
  const view = useTableView({ rows: table.values, keys: VALUE_KEYS, text: valueWords, keep: (v) => flagged.has(v.id), pageSize: 8 });
  return (
    <section className="delivery-table" data-testid={`delivery-table-${table.id}`}>
      <div className="delivery-block-head">
        <strong>{table.kind === "facts" ? (table.file ? `Facts of ${table.file}` : "Entered by a person") : `${fieldText(table.table_kind ?? "table")} table`}</strong>
        {table.kind === "table" && <span className="muted">{table.file}</span>}
        <span className="muted">{plural(table.values.length, "value")}</span>
        {table.mapping_id && table.mapping_status && (
          <button type="button" className="delivery-chip-btn" onClick={() => onMapping(table.mapping_id as string)}
                  data-testid={`delivery-table-mapping-${table.id}`} title="Review how this table is read">
            <ChipFor state={table.mapping_status} table={MAPPING_STATE} /> mapping v{table.mapping_version}
          </button>
        )}
        {table.waiting && <span className="chip medium" data-testid={`delivery-table-waiting-${table.id}`}>being read again</span>}
      </div>
      {table.mapping_status === "rejected" && (
        <InlineIssue severity="warn">Its mapping was rejected: these are the values read before. They stay until the table is
          set aside as not data or read with another mapping.</InlineIssue>
      )}
      {table.values.length > 8 && <TableFilter view={view} placeholder="Filter: field, label, statistic…" label="Filter these values" />}
      <div className="table-scroll">
        <table className="delivery-values">
          <caption className="sr-only">Values of {table.file ?? "a person's entries"}</caption>
          <thead><tr>
            <SortHeader view={view} col="field" label="Field" /><SortHeader view={view} col="value" label="Value" numeric /><th>Unit</th>
            <SortHeader view={view} col="time" label="Time" numeric /><th>Labels</th><th>Statistic</th><th>As written</th>
            <SortHeader view={view} col="level" label="Read by" /><th>Source</th>
          </tr></thead>
          <tbody>
            {view.visible.map((v) => (
              <Fragment key={v.id}>
                <tr data-testid={`delivery-value-${v.id}`} className={[flagged.has(v.id) ? "delivery-flagged" : "", v.status === "superseded" || v.status === "excluded" ? "delivery-set-aside" : ""].join(" ").trim() || undefined}>
                  <td>{fieldText(v.field)}{flagged.has(v.id) && <div><span className="chip high" data-testid={`delivery-flag-${v.id}`}>{fieldText(flagged.get(v.id) as string).toLowerCase()}</span></div>}</td>
                  <TupleCells v={v} />
                  <td className="delivery-verbatim">{v.blinded ? "" : v.verbatim ?? ""}</td>
                  <td>{levelText(v.level)}{v.cross_file && <div className="muted fs-12">from another file</div>}
                    {STATUS[v.status] && <div><ChipFor state={v.status} table={STATUS} /></div>}</td>
                  <td>
                    {v.anchor ? (
                      <button type="button" className="link-btn" aria-expanded={source === v.id} data-testid={`delivery-source-open-${v.id}`}
                              onClick={() => setSource(source === v.id ? null : v.id)}>{source === v.id ? "Hide" : "Show"}</button>
                    ) : <span className="muted fs-12">{v.method === "person" ? "entered" : "computed"}</span>}
                    {!v.blinded && v.status !== "superseded" && v.status !== "excluded" && (
                      <button type="button" className="link-btn" data-testid={`delivery-correct-${v.id}`}
                              onClick={() => setCorrecting(correcting === v.id ? null : v.id)}>Correct</button>
                    )}
                  </td>
                </tr>
                {correcting === v.id && (
                  <tr className="delivery-source-row"><td colSpan={9}>
                    <Enter entry={{ field: v.field, supersedes: v.id, value: v.value === null ? "" : String(v.value), unit: v.unit ?? "" }}
                           options={options} busy={busy} onCancel={() => setCorrecting(null)} testId={`correct-${v.id}`}
                           onSubmit={async (body) => { const { data } = await decide(() => send("post", ENTER, params, body)); if (data) setCorrecting(null); }} />
                  </td></tr>
                )}
                {source === v.id && (
                  <tr className="delivery-source-row"><td colSpan={9}><ValueSource projectId={projectId} valueId={v.id} onClose={() => setSource(null)} /></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <TableMore view={view} noun="values" testId={`delivery-table-more-${table.id}`} />
    </section>
  );
}

function CheckRow({ check, subject, options, decide, busy, onMapping, params }: {
  check: Check; subject: Subject; options: Options | null; decide: Decide; busy: boolean; onMapping: (id: string) => void;
  params: CardParams;
}) {
  const [acting, setActing] = useState(false);
  const open = check.severity === "fail" && !check.overridden;
  const message = check.message ?? WITHHELD;
  const mapping = check.code === MAPPED ? subject.mappings.find((m) => check.message?.includes(m.mapping_id)) : undefined;
  // the fact the study record lacks, as its message names it: only to start the form, which the person can change
  const lacking = check.code === ENTERED ? (/needs (\w+)/.exec(check.message ?? "")?.[1] ?? "") : "";
  return (
    <li className={open ? "delivery-check open" : "delivery-check"} data-testid={`delivery-check-${check.id}`} data-code={check.code}>
      <div className="delivery-check-line">
        <span className={`chip ${check.overridden ? "neutral" : SEVERITY[check.severity].tone}`}>{check.overridden ? "overridden" : SEVERITY[check.severity].label}</span>
        <span className="delivery-check-text">{message}</span>
        {check.values.length > 0 && <span className="muted fs-12">{plural(check.values.length, "value")}, marked in the tables below</span>}
        {open && !acting && (
          check.code === ENTERED ? <button type="button" className="btn tiny" onClick={() => setActing(true)} data-testid={`delivery-enter-open-${check.id}`}>Enter it…</button>
            : check.code === DISPOSED ? <span className="muted fs-12">settle it under Required items</span>
              : check.code === MAPPED ? (mapping
                ? <button type="button" className="btn tiny" onClick={() => onMapping(mapping.mapping_id)} data-testid={`delivery-check-mapping-${check.id}`}>Review the mapping…</button>
                : <span className="muted fs-12">review it under Mappings</span>)
                : <button type="button" className="btn tiny" onClick={() => setActing(true)} data-testid={`delivery-override-open-${check.id}`}>Override…</button>
        )}
      </div>
      {open && acting && check.code === ENTERED && (
        <Enter entry={{ field: lacking }} options={options} busy={busy} onCancel={() => setActing(false)} testId={`delivery-enter-${check.id}`}
               onSubmit={async (body) => { const { data } = await decide(() => send("post", ENTER, params, body)); if (data) setActing(false); }} />
      )}
      {open && acting && check.code !== ENTERED && (
        <Why action="Override the check" label={`Why ${check.code} is overridden`} busy={busy} onCancel={() => setActing(false)}
             testId={`delivery-override-${check.id}`} placeholder="why it holds as it is (kept on the audit trail)"
             onSubmit={async (why) => { const { data } = await decide(() => send("post", OVERRIDE, params, { check_id: check.id, why })); if (data) setActing(false); }} />
      )}
    </li>
  );
}

function ConflictRow({ conflict, values, decide, busy, params }: {
  conflict: Conflict; values: Map<string, Value>; decide: Decide; busy: boolean; params: CardParams;
}) {
  const [keep, setKeep] = useState("");
  const where = [fieldText(conflict.field), conflict.time !== null ? `at ${conflict.time}` : "", Object.entries(conflict.labels).map(([r, l]) => `${r} ${l}`).join(" · ")].filter(Boolean).join(" · ");
  return (
    <li className="delivery-check open" data-testid={`delivery-conflict-${conflict.id}`}>
      <div className="delivery-check-line">
        <span className="chip high">differs</span>
        <span className="delivery-check-text">{where}: the files give {conflict.kind === "unit" ? "different units" : "different values"}. Choose the one to keep; the others are set aside.</span>
      </div>
      <fieldset className="delivery-options">
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
      <Why action="Keep this value" label="Why this value is kept" busy={busy} disabled={!keep} testId={`delivery-choose-${conflict.id}`}
           onSubmit={(why) => decide(() => send("post", CHOOSE, params, { conflict_id: conflict.id, keep, why }))} />
    </li>
  );
}

function LinkRow({ link, subject, decide, busy, params }: {
  link: Link; subject: Subject; decide: Decide; busy: boolean; params: CardParams;
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
        <span className={`chip ${link.state === "refused" ? "neutral" : "medium"}`}>{link.state === "refused" ? "refused" : link.state === "ambiguous" ? "which study?" : "to confirm"}</span>
        <span className="delivery-check-text">
          <strong>{link.file}</strong> names {link.study_label ? `study ${link.study_label}` : "a study"} in its text and gives{" "}
          {subject.blinded ? "values" : plural(link.values, "value")} for it. Is it the same study as {subject.label}?
        </span>
      </div>
      {link.state !== "refused" && (
        refusing ? (
          <Why action="Refuse the link" label="Why the file is not about this study" busy={busy} onCancel={() => setRefusing(false)}
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

function RequirementRow({ item, decide, busy, params }: {
  item: Requirement; decide: Decide; busy: boolean; params: CardParams;
}) {
  const [disposition, setDisposition] = useState<Schema<"DeliveryDisposition">["disposition"]>("ask_client");
  const missing = item.status === "missing";
  const said = DISPOSITIONS.find(([id]) => id === item.disposition)?.[1];
  return (
    <li className={missing && !item.disposition ? "delivery-check open" : "delivery-check"} data-testid={`delivery-requirement-${item.req_id}`}>
      <div className="delivery-check-line">
        <span className={`chip ${missing ? (item.disposition ? "neutral" : "high") : "low"}`}>{missing ? (item.disposition ? "missing, settled" : "missing") : fieldText(item.status)}</span>
        <span className="delivery-check-text">{item.label}</span>
        <span className="muted fs-12">{item.criticality.toLowerCase()}{said ? ` · ${said}` : ""}</span>
      </div>
      {missing && !item.disposition && (
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

/** The card of the subject `row`, opened on the Delivery section. `deliveries` are the page's, for the numbers outside
 *  every table of the subject's own deliveries. */
export function SubjectCard({ projectId, row, deliveries, onMapping }: {
  projectId: string; row: SubjectRow; deliveries: Page["deliveries"]; onMapping: (mappingId: string) => void;
}) {
  const params = { project_id: projectId, type: row.subject_type, subject: row.subject };
  const read = useResource(SUBJECT, params, { poll: (d) => d.tables.some((t) => t.waiting) || d.mappings.some((m) => m.waiting) });
  const inputs = useResource("/api/v1/projects/{project_id}/inputs", { project_id: projectId });
  const { decide, busy, problem } = useDecide();
  const [confirming, setConfirming] = useState(false);
  const [entering, setEntering] = useState<string | null>(null);
  const [notes, setNotes] = useState(false);
  const s = read.data;

  const values = useMemo(() => new Map((s?.tables ?? []).flatMap((t) => t.values).map((v) => [v.id, v] as const)), [s]);
  // the rows that need the person: named by a failed check not overridden, or by an open conflict
  const flagged = useMemo(() => {
    const out = new Map<string, string>();
    for (const c of s?.checks ?? []) if (c.severity === "fail" && !c.overridden) for (const id of c.values) out.set(id, c.code);
    for (const c of s?.conflicts ?? []) for (const id of c.values) out.set(id, "differs between files");
    return out;
  }, [s]);

  if (read.problem) return <Problem text={read.problem} />;
  if (!s) return <p className="muted m-0">Reading the card…</p>;

  const options = inputs.data?.study_options ?? null;
  const outside = deliveries.filter((d) => row.deliveries.includes(d.id)).flatMap((d) => d.files)
    .flatMap((f) => f.outside.filter((o) => o.counted).map((o) => ({ file: f, item: o })));
  const failing = s.checks.filter((c) => c.severity === "fail" && !c.overridden);
  const others = s.checks.filter((c) => !(c.severity === "fail" && !c.overridden));
  const c = s.confirmation;
  const done = Boolean(c && c.current && c.landed);
  const levels = Object.entries(s.by_level).map(([level, n]) => `${n} ${levelText(level)}`).join(", ");

  return (
    <div className="delivery-card" data-testid={`delivery-card-${s.subject}`}>
      <p className="muted m-0" data-testid={`delivery-card-counts-${s.subject}`}>
        {KIND_LABEL[s.subject_type]} {s.label}: {plural(s.values, "value")}{levels ? ` (${levels})` : ""} · silent loss {s.silent_loss} ·
        {" "}rules {s.rules.status} v{s.rules.version}
      </p>
      {s.blinded && <p className="delivery-withheld" data-testid={`delivery-blinded-${s.subject}`}>{WITHHELD}: this study is blinded until
        the MAP is signed. Its values, their spread and what is below the LLOQ are not shown, and it cannot be confirmed yet.</p>}
      {s.confirm_on === "client-review" && <InlineIssue severity="note" testId={`delivery-confirm-on-${s.subject}`}>A filled client-data
        template: it is confirmed on its own card in the area of its data. Its coverage and values are shown here to read.</InlineIssue>}
      {s.loaded_elsewhere.length > 0 && <InlineIssue severity="note" testId={`delivery-loaded-elsewhere-${s.subject}`}>
        {plural(s.loaded_elsewhere.length, "dataset")} of the same source {s.loaded_elsewhere.length === 1 ? "is" : "are"} in the project from
        its own card already. Nothing is loaded twice.</InlineIssue>}

      {s.blockers.length > 0 ? (
        <div className="delivery-blocked" data-testid={`delivery-blockers-${s.subject}`}>
          <strong>Before it can be confirmed</strong>
          <ul className="plain-list">
            {s.blockers.map((b, i) => <li key={`${b.code}-${i}`} data-testid={`delivery-blocker-${b.code}`}><strong>{BLOCKER_LABEL[b.code] ?? b.code}</strong>: {b.detail}</li>)}
          </ul>
        </div>
      ) : !done && <p className="banner ok" data-testid={`delivery-ready-${s.subject}`}>Nothing blocks its confirmation.</p>}
      <Problem text={problem} testId={`delivery-card-problem-${s.subject}`} />

      {outside.length > 0 && (
        <section className="delivery-block" data-testid={`delivery-outside-${s.subject}`}>
          <div className="delivery-block-head"><h3>Numbers outside every table</h3></div>
          <ul className="delivery-plain">
            {outside.map(({ file, item }, i) => (
              <li key={`${file.file_id}-${item.where}`} className="delivery-check open" data-testid={`delivery-outside-item-${i}`}>
                <div className="delivery-check-line">
                  <span className="chip high">not read</span>
                  <span className="delivery-check-text">“{item.text ?? WITHHELD}” <span className="muted">{file.name} · {item.where}</span></span>
                </div>
                <Why action="It is not data" label="Why this text is not data" busy={busy} testId={`delivery-outside-accept-${i}`}
                     onSubmit={(why) => decide(() => send("post", EXCLUDE, { project_id: projectId },
                                                          { file_sha256: file.sha256, regions: [item.where], scope: "outside", why }))} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {s.gaps.length > 0 && (
        <section className="delivery-block" data-testid={`delivery-gaps-${s.subject}`}>
          <div className="delivery-block-head"><h3>Not stated in any file</h3></div>
          <ul className="delivery-plain">
            {s.gaps.map((g) => (
              <li key={`${g.study}-${g.tag}`} className="delivery-check open" data-testid={`delivery-gap-${g.tag}`}>
                <div className="delivery-check-line">
                  <span className="chip high">missing</span>
                  <span className="delivery-check-text">{fieldText(g.tag)}: {g.reason}</span>
                  {entering !== g.tag && <button type="button" className="btn tiny" onClick={() => setEntering(g.tag)} data-testid={`delivery-gap-enter-${g.tag}`}>Enter it…</button>}
                </div>
                {entering === g.tag && (
                  <Enter entry={{ field: g.tag }} options={options} busy={busy} onCancel={() => setEntering(null)} testId={`delivery-enter-gap-${g.tag}`}
                         onSubmit={async (body) => { const { data } = await decide(() => send("post", ENTER, params, body)); if (data) setEntering(null); }} />
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {s.checks.length > 0 && (
        <section className="delivery-block" data-testid={`delivery-checks-${s.subject}`}>
          <div className="delivery-block-head">
            <h3>Checks</h3>
            <span className={`chip ${failing.length ? "high" : "low"}`}>{failing.length ? `${failing.length} failed` : "none failed"}</span>
          </div>
          <ul className="delivery-plain">
            {failing.map((check) => <CheckRow key={check.id} check={check} subject={s} options={options} decide={decide} busy={busy} onMapping={onMapping} params={params} />)}
          </ul>
          {others.length > 0 && (
            <>
              <button type="button" className="link-btn" aria-expanded={notes} onClick={() => setNotes(!notes)} data-testid={`delivery-checks-more-${s.subject}`}>
                {notes ? "Hide" : "Show"} the {plural(others.length, "other check")} (warnings, notes and overridden)</button>
              {notes && <ul className="delivery-plain">{others.map((check) => <CheckRow key={check.id} check={check} subject={s} options={options} decide={decide} busy={busy} onMapping={onMapping} params={params} />)}</ul>}
            </>
          )}
        </section>
      )}

      {s.conflicts.length > 0 && (
        <section className="delivery-block" data-testid={`delivery-conflicts-${s.subject}`}>
          <div className="delivery-block-head"><h3>The files disagree</h3></div>
          <ul className="delivery-plain">{s.conflicts.map((x) => <ConflictRow key={x.id} conflict={x} values={values} decide={decide} busy={busy} params={params} />)}</ul>
        </section>
      )}

      {s.links.length > 0 && (
        <section className="delivery-block" data-testid={`delivery-links-${s.subject}`}>
          <div className="delivery-block-head"><h3>Links between files</h3></div>
          <ul className="delivery-plain">{s.links.map((x) => <LinkRow key={x.id} link={x} subject={s} decide={decide} busy={busy} params={params} />)}</ul>
        </section>
      )}

      {s.requirements.length > 0 && (
        <section className="delivery-block" data-testid={`delivery-requirements-${s.subject}`}>
          <div className="delivery-block-head"><h3>Required items</h3></div>
          <ul className="delivery-plain">{s.requirements.map((x) => <RequirementRow key={x.req_id} item={x} decide={decide} busy={busy} params={params} />)}</ul>
        </section>
      )}

      {s.mappings.length > 0 && (
        <section className="delivery-block" data-testid={`delivery-card-mappings-${s.subject}`}>
          <div className="delivery-block-head"><h3>Mappings no person approved</h3></div>
          <ul className="delivery-plain">
            {s.mappings.map((m) => (
              <li key={`${m.mapping_id}-${m.version}`} className="delivery-check open">
                <div className="delivery-check-line">
                  <ChipFor state={m.status} table={MAPPING_STATE} />
                  <span className="delivery-check-text">{fieldText(m.kind)} table, version {m.version}: {m.used_in.map((u) => `${u.file} ${u.where}`).join("; ")}</span>
                  {m.waiting && <span className="chip medium">being read again</span>}
                  <button type="button" className="btn tiny" onClick={() => onMapping(m.mapping_id)} data-testid={`delivery-card-mapping-${m.mapping_id}`}>Review…</button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="delivery-block" data-testid={`delivery-values-${s.subject}`}>
        <div className="delivery-block-head">
          <h3>Values, by the table they were read from</h3>
          {entering !== "+" && !s.blinded && <button type="button" className="link-btn" onClick={() => setEntering("+")} data-testid={`delivery-enter-open-${s.subject}`}>Enter a value no file states…</button>}
        </div>
        {entering === "+" && (
          <Enter entry={{ field: "" }} options={options} busy={busy} onCancel={() => setEntering(null)} testId={`delivery-enter-${s.subject}`}
                 onSubmit={async (body) => { const { data } = await decide(() => send("post", ENTER, params, body)); if (data) setEntering(null); }} />
        )}
        {s.tables.length === 0 && <p className="muted m-0">No value yet.</p>}
        {s.tables.map((t) => <ValueTable key={t.id} projectId={projectId} params={params} table={t} flagged={flagged} options={options} decide={decide} busy={busy} onMapping={onMapping} />)}
      </section>

      <section className="delivery-block" data-testid={`delivery-held-${s.subject}`}>
        <div className="delivery-block-head"><h3>What the loading would hold back</h3></div>
        {s.landing_problem && <InlineIssue severity="error" testId={`delivery-landing-problem-${s.subject}`}>It cannot be loaded yet: {s.landing_problem}</InlineIssue>}
        {s.held === null ? <p className="delivery-withheld">{WITHHELD}</p>
          : s.held.length === 0 ? (!s.landing_problem && <p className="muted m-0">Nothing: every value that can be loaded is loaded.</p>)
            : <ul className="flags">{s.held.map((h) => <li key={h}>{h}</li>)}</ul>}
      </section>

      <SpotCheck projectId={projectId} subject={s} />

      <section className="delivery-block delivery-confirmation" data-testid={`delivery-confirmation-${s.subject}`}>
        <div className="delivery-block-head">
          <h3>Confirmation</h3>
          {c && <span className={`chip ${done ? "low" : "medium"}`}>{!c.current ? "the values changed since" : c.landed ? "confirmed and loaded" : "signed, not loaded yet"}</span>}
        </div>
        {c ? (
          <>
            <p className="m-0">Signed: <strong data-testid={`delivery-manifestation-${s.subject}`}>{c.manifestation}</strong></p>
            <p className="muted fs-12 m-4-0-0">
              {c.id} · record {c.record_sha256.slice(0, 12)}{c.rules ? ` · rules ${c.rules.status} v${c.rules.version}` : ""}
              {c.landed ? ` · loaded ${when(c.landed.at)}: ${plural(c.landed.datasets.length, "dataset")}, ${plural(c.landed.evidence.length, "value")}`
                + (c.landed.dissolution_records ? `, ${plural(c.landed.dissolution_records, "dissolution record")}` : "")
                + (c.landed.rejected_legacy.length ? ` · ${plural(c.landed.rejected_legacy.length, "earlier reading")} of the same source set aside` : "") : ""}
            </p>
            {c.held && c.held.length > 0 && <ul className="flags">{c.held.map((h) => <li key={h}>{h}</li>)}</ul>}
          </>
        ) : <p className="muted m-0">Not confirmed yet.</p>}
        {s.confirm_on === "delivery" && !done && (
          <div>
            <button type="button" className="btn primary" onClick={() => setConfirming(true)} data-testid={`delivery-confirm-${s.subject}`}>
              {c && !c.landed && c.current ? "Finish the loading…" : c ? "Confirm again…" : "Confirm and sign…"}</button>
          </div>
        )}
      </section>
      {confirming && <ConfirmDialog projectId={projectId} subject={s} onClose={() => setConfirming(false)} />}
    </div>
  );
}
