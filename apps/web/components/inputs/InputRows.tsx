"use client";

import { useState, type ReactNode } from "react";

import { EmptyState } from "@/components/kit";
import { send, type Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";

import { PeekButton } from "@/components/kit/SourcePeek";

import { formulationLine, paramLabel, unitText } from "@/lib/words";

import { Decide, type Ev, fmt, PathwayPick, type Pathway, type Run, Source, TodoAction, TodoCard, type TodoItem, Value } from "./InputsTodo";

export type Row = Schema<"CompoundRow">;
type Alternative = Schema<"AlternativeView">;
// the evidence view's fields (EvidenceView) as the shared fix components read them
const ev = (x: Schema<"EvidenceView">) => x as unknown as Ev;

// what waits on a person first, then the values in the model
const FIRST: Row["state"][] = ["conflict", "held", "missing", "kept", "empty"];
const STATE: Record<Row["state"], [string, string]> = {
  kept: ["low", "in the model"], conflict: ["high", "keep one"], held: ["medium", "check it"], missing: ["high", "missing"],
  empty: ["neutral", "no value yet"],
};
// the sources a person may cite for a value typed into a row (modeler_project.evidence.SourceType)
const SOURCE_TYPES = [["PUBLICATION", "publication"], ["CLIENT_REPORT", "client report"], ["REGULATORY_REVIEW", "regulatory review"],
                      ["DATABASE", "database"], ["ASSUMPTION", "assumption (no source)"]] as const;
/** How a person gives a model input its value: typed with its unit as the source states it, except for the model ids
 *  (pbpk_domain/parameters/registry.yaml) whose value is a word or a document (`modeler_project.evidence.numeric_target`):
 *  one PK-Sim takes only by its names is chosen from the names the API gives on the row (`CompoundRow.allowed`, read from
 *  the model builder's own types, as `POST /evidence` checks them: the binding partner's), "neutral" is a statement about
 *  the pKa, and what this form cannot take (a table, a method's name, a rule) is not offered here. */
type Entry = { kind: "typed" | "choice" | "neutral" } | { kind: "elsewhere"; what: string };
const NOT_A_NUMBER: Record<string, Entry> = {
  "phys.pka.neutral": { kind: "neutral" },
  "phys.solubility.table": { kind: "elsewhere", what: "a table of solubility by pH" },
  "dist.partition_method": { kind: "elsewhere", what: "the name of a PK-Sim calculation method" },
  "dist.permeability_method": { kind: "elsewhere", what: "the name of a PK-Sim calculation method" },
  "alt.select": { kind: "elsewhere", what: "which alternative each product and food state uses" },
};
const entryOf = (row: Row): Entry => (row.allowed.length ? { kind: "choice" } : NOT_A_NUMBER[row.id] ?? { kind: "typed" });
// what a name chosen for the input is, said above its names
const CHOICE_HELP: Record<string, string> = { "bind.partner": "The plasma protein the compound binds to, by PK-Sim's name." };

/** A value with its source, typed into the row (p2-add): filed under the row's data-checklist item, cited. A value is
 *  typed with its unit as the source states it; a name (the binding partner) is chosen from PK-Sim's; a neutral compound
 *  is stated as such (phys.pka.neutral set to 1, as the CPF records it for a published model, `osp_import`). */
function AddValue({ row, name, projectId, run, pathways = [] }: {
  row: Row; name: string; projectId: string; run: Run;
  /** the data plan's "elim" (an elimination pathway): the pathways its value is filed under, chosen first (OWN-5) */
  pathways?: Pathway[];
}) {
  const entry = entryOf(row);
  const [value, setValue] = useState(entry.kind === "neutral" ? "1" : "");
  const [unit, setUnit] = useState(row.unit ?? "");
  const [pathway, setPathway] = useState("");
  // the parameter the value is filed under: the row's own, or the pathway chosen for the data plan's "elim" (never "elim")
  const target = pathways.length ? pathway : row.id;
  const [type, setType] = useState<(typeof SOURCE_TYPES)[number][0]>("PUBLICATION");
  const [title, setTitle] = useState("");
  const [link, setLink] = useState("");
  const [quote, setQuote] = useState("");
  const typed = entry.kind === "typed";
  const numeric = typed && value.trim() !== "" && !Number.isNaN(Number(value));
  const cited = type === "ASSUMPTION" || link.trim() !== "";
  if (!row.req_id) return <p className="muted fs-13 m-0">This input has no item on the data checklist to file a value under.</p>;
  if (entry.kind === "elsewhere") return null;
  const done = entry.kind === "neutral" ? `${name}: stated with its source.`
    : `${pathways.length ? paramLabel(target) : name}: value added with its source.`;
  // each field is named on screen (plan 2026-11-14, design "How the person fills what is missing"); its accessible name
  // keeps the row's id, so a field is never one of several with the same name
  return (
    <div className="add-value" data-testid={`add-${row.id}`}>
      <p className="muted fs-12 m-0">
        {typed ? <>Type the value and its unit as the source states them. A number in a unit PK-Sim does not use is converted
          where the unit allows; otherwise it is held for you to check.</>
          : entry.kind === "choice" ? <>{CHOICE_HELP[row.id] ?? "One of PK-Sim's names for it, as the model builder takes it."}</>
            : <>The source states that the compound is neutral: it has no pKa.</>}
        {" "}Cite the source by its DOI or URL, or call it an assumption.</p>
      {pathways.length > 0 && (
        <div className="row gap-6" data-testid={`add-pathway-${row.id}`}>
          <label className="add-field">Elimination pathway
            <PathwayPick pathways={pathways} value={pathway} label={`the elimination pathway of the value for ${name}`} testId={`pathway-for-${row.id}`}
                         onChange={(id) => { setPathway(id); setUnit(pathways.find((p) => p.id === id)?.unit ?? ""); }} /></label>
          <p className="muted fs-12 m-0 flex-1 minw-220">A value counts only for the pathway it belongs to: choose it first. Its unit is
            the one the model stores it in; another unit is converted where it can be.</p>
        </div>
      )}
      <div className="row gap-6">
        {typed && <>
          <label className="add-field">Value
            <input value={value} onChange={(e) => setValue(e.target.value)} className="w-110" aria-label={`value for ${row.id}`} /></label>
          <label className="add-field">Unit
            <input placeholder="as stated" value={unit} onChange={(e) => setUnit(e.target.value)} className="w-90" aria-label={`unit for ${row.id}`} /></label>
        </>}
        {entry.kind === "choice" && (
          <label className="add-field">PK-Sim&apos;s name
            <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={`value for ${row.id}`}>
              {!value && <option value="">choose…</option>}
              {row.allowed.map((p) => <option key={p} value={p}>{p}</option>)}
            </select></label>
        )}
        <label className="add-field">Source
          <select value={type} onChange={(e) => setType(e.target.value as typeof type)} aria-label={`source type for ${row.id}`}>
            {SOURCE_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select></label>
        <label className="add-field flex-1 minw-140">Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} aria-label={`title for ${row.id}`} /></label>
        <label className="add-field">DOI or URL
          <input value={link} onChange={(e) => setLink(e.target.value)} className="w-170" aria-label={`link for ${row.id}`} /></label>
      </div>
      <div className="row gap-6 mt-4">
        <label className="add-field flex-1 minw-220">The sentence that states it
          <input value={quote} onChange={(e) => setQuote(e.target.value)} aria-label={`quote for ${row.id}`} /></label>
        <button className="btn primary" disabled={!value.trim() || !cited || !target}
                title={!target ? "Choose the elimination pathway first" : undefined}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence", { project_id: projectId }, {
                  req_id: row.req_id as string, target, value: numeric || entry.kind === "neutral" ? Number(value) : value,
                  unit: typed ? unit || null : null, source_type: type, title, quote,
                  ...(link.startsWith("10.") ? { doi: link } : link ? { url: link } : {}),
                }), done)}>
          Add
        </button>
      </div>
    </div>
  );
}

/** A source the selection kept or agreed with, and how to exclude it (with a reason; the next best source takes over). */
function SourceLine({ e, projectId, run }: { e: Ev; projectId: string; run: Run }) {
  const [reason, setReason] = useState("");
  return (
    <li className="source-line">
      <div className="source-line-head">
        <Source e={e} />
        <PeekButton projectId={projectId} source={{ ...e.source, quote: e.quote }} label={paramLabel(e.target)}
                    testId={`peek-${e.id}`} />
      </div>
      <div className="row gap-6 mt-4">
        <input placeholder="why exclude it" value={reason} onChange={(x) => setReason(x.target.value)} className="flex-1 minw-160"
               aria-label={`reason to exclude ${e.id}`} />
        <button className="btn" disabled={!reason.trim()}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:decide",
                                                   { project_id: projectId, evidence_id: e.id }, { state: "REJECTED", reason }),
                                        `${paramLabel(e.target)} ${fmt(e.value)} excluded; the next best source is used.`)}>Exclude</button>
      </div>
    </li>
  );
}

function AlternativeLine({ a, projectId }: { a: Alternative; projectId: string }) {
  const e = ev(a);
  return (
    <li className="source-line">
      <div className="row gap-8">
        <Value e={e} />
        <PeekButton projectId={projectId} source={{ ...e.source, quote: e.quote }} label={paramLabel(e.target)}
                    testId={`peek-${e.id}`} />
        <span className={`chip ${a.relation === "conflicts" ? "high" : "medium"}`}>
          {a.relation === "conflicts" ? "more than 2-fold apart" : `differs by ${a.differs_pct} %`}
        </span>
      </div>
      <Source e={ev(a)} />
    </li>
  );
}

function ChooseProcess({ row, projectId, run }: { row: Row; projectId: string; run: Run }) {
  const [value, setValue] = useState(row.candidates[0] ?? "");
  const [reason, setReason] = useState("");
  return (
    <div className="row gap-4">
      <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={`process for ${row.id}`}>
        {row.candidates.map((c) => <option key={c}>{c}</option>)}
      </select>
      <input placeholder="why" value={reason} onChange={(e) => setReason(e.target.value)} className="w-150" />
      <button className="btn" disabled={!reason.trim()}
              onClick={() => void run(() => send("put", "/api/v1/projects/{project_id}/inputs/choices", { project_id: projectId },
                                                 { kind: "process", key: row.id.split(".").slice(0, -1).join("."), value, reason }),
                                      `${paramLabel(row.id)}: carried by the PK-Sim process ${value}.`)}>Choose</button>
    </div>
  );
}

/** One model input: its value in the PK-Sim unit, the source kept and the sources that agree (D-32), the alternatives
 *  beneath, and what settles it in place when it waits on a person. */
function InputRow({ row, name, items, projectId, run }: { row: Row; name: string; items: TodoItem[]; projectId: string; run: Run }) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  // a kept value the model builder cannot take (the API says why: a binding partner that is not one of PK-Sim's names,
  // kept before the check or let in by a signed delivery): never shown as "in the model"
  const refused = row.state === "kept" && row.message !== null;
  const [state, label] = refused ? ["high", row.allowed.length ? "not a PK-Sim name" : "check it"] : STATE[row.state];
  const entry = entryOf(row);
  const kept = row.sources.length ? ev(row.sources[0]) : undefined;
  const agree = row.sources.length - 1;
  return (
    <div className={`input-row ${row.state}`} data-testid={`record-${row.id}`} id={`row-${row.id}`}>
      <div className="input-head">
        <div className="input-name">
          {/* named in words only (final review OWN-8): the CPF id is not shown */}
          <strong>{name}</strong>
        </div>
        <div className="input-value">
          {row.value === null ? (row.state === "empty" ? null : <span className="muted">—</span>)
            : entry.kind === "neutral" ? <strong>neutral</strong> : <><strong>{typeof row.value === "number" ? +row.value.toPrecision(5) : row.value}</strong> {unitText(row.unit)}</>}
        </div>
        <div className="input-source">
          {kept ? <>
            {kept.source.title || kept.source_type.toLowerCase().replace(/_/g, " ")}{kept.source.year ? ` · ${kept.source.year}` : ""}
            <span className="muted"> · grade {kept.confidence}</span>
            {row.state === "kept" && agree > 0 && <span className="chip low" title="sources within 10 % of the kept value">+{agree} agree</span>}
          </> : row.state === "conflict" ? <span className="muted">{row.alternatives.length} sources disagree</span>
            : row.state === "empty" ? null : <span className="muted">no source yet</span>}
        </div>
        <div className="input-state">
          <span className={`chip ${state}`}>{label}</span>
          {row.binding && <div className="muted fs-12" title={row.binding.parameter ?? ""}>{row.binding.process ?? row.binding.parameter}</div>}
        </div>
        <div className="input-peek">
          {kept && <PeekButton projectId={projectId} source={{ ...kept.source, quote: kept.quote }} label={name}
                               testId={`peek-${row.id}`} />}
        </div>
      </div>
      {refused && (
        <p className="fs-13 m-2-0" data-testid={`record-refused-${row.id}`}>
          {row.allowed.length
            ? <>PK-Sim takes only {row.allowed.join(", ").replace(/, ([^,]*)$/, " or $1")}, written as shown, so the model cannot be built
              with “{String(row.value)}”. Add a value with one of these names, then open Sources and exclude this one.</>
            : row.message}
        </p>
      )}
      {row.candidates.length > 0 && !items.some((t) => t.kind === "process") && <ChooseProcess row={row} projectId={projectId} run={run} />}
      {items.map((t) => (
        <div key={`${t.kind}-${t.target}`} className="input-fix" data-testid={`todo-${t.kind}-${t.target}`} id={`todo-${t.kind}-${t.target}`}>
          <TodoAction t={t} projectId={projectId} run={run} />
          {t.kind === "process" && row.candidates.length > 0 && <ChooseProcess row={row} projectId={projectId} run={run} />}
        </div>
      ))}
      {row.state === "held" && items.length === 0 && row.sources.map(ev).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} />)}
      <div className="row gap-6">
        {(row.sources.length > 0 || row.alternatives.length > 0) && row.state === "kept" && (
          <button type="button" className="link-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide the sources" : `Sources (${row.sources.length + row.alternatives.length})`}
          </button>
        )}
        {entry.kind !== "elsewhere" && (
          <button type="button" className="link-btn" onClick={() => setAdding(!adding)} data-testid={`add-open-${row.id}`} aria-expanded={adding}
                  aria-label={adding ? `Cancel the value for ${name}` : entry.kind === "neutral" ? "State that the compound is neutral"
                    : `Add a value for ${name}`}>
            {adding ? "Cancel" : entry.kind === "neutral" ? "State it is neutral" : "Add a value"}</button>
        )}
      </div>
      {open && row.state === "kept" && (
        <ul className="sources">
          {row.sources.map(ev).map((e) => <SourceLine key={e.id} e={e} projectId={projectId} run={run} />)}
          {row.alternatives.length > 0 && <li className="muted fs-12">Not used (listed for the review):</li>}
          {row.alternatives.map((a) => <AlternativeLine key={a.id} a={a} projectId={projectId} />)}
        </ul>
      )}
      {adding && <AddValue row={row} name={name} projectId={projectId} run={run} pathways={items.find((t) => t.pathways?.length)?.pathways} />}
    </div>
  );
}

// The compound's building blocks (plan 2026-11-03 §3.2), by the CPF id's family; an id no family names is "Other". The
// data plan's bare "elim" (an elimination pathway, not yet filed under one) is an elimination row too (2026-11-14 audit).
const BLOCKS: [string, RegExp][] = [
  ["Identity and physico-chemistry", /^phys\./],
  ["Binding and partitioning", /^(bind|dist)\./],
  ["Permeability and absorption", /^(perm|abs|gi)\./],
  ["Elimination, by process", /^(elim|metab|clear)(\.|$)/],
  ["Transporters and interactions", /^(trans|ddi|inhib|induct)\./],
];
const blockOf = (id: string) => BLOCKS.find(([, rule]) => rule.test(id))?.[0] ?? "Other";

/** The rows to fill (state "empty": a model input the data plan owns that no source gives yet, and that nothing waits
 *  on), folded under "+ n more you can fill in" (plan 2026-11-14 §3 API 1). Each opens the form its value is given with
 *  (`AddValue`, `POST /evidence`, filed under the row's data-checklist item). `elsewhere`: the names of the inputs to fill
 *  this form cannot take, said once inside the fold. `name`: what they are of, for the toggle's label. */
function ToFill({ rows, elsewhere, name, one }: { rows: Row[]; elsewhere: string[]; name: string; one: (r: Row) => ReactNode }) {
  const [open, setOpen] = useState(false);
  if (!rows.length) return null;
  return (
    <div className="input-fill" data-testid={`fill-${name}`}>
      <button type="button" className="link-btn input-fill-toggle" aria-expanded={open} onClick={() => setOpen(!open)}
              aria-label={`${open ? "Hide" : "Show"} the ${rows.length} more ${name === "rows" ? "inputs" : `inputs of ${name}`} you can fill in`}
              data-testid={`fill-toggle-${name}`}>
        {open ? "Hide the inputs you can fill in" : `+ ${rows.length} more you can fill in`}</button>
      {open && <div className="input-fill-rows">{rows.map(one)}</div>}
      {open && elsewhere.length > 0 && (
        <p className="muted fs-12 m-0" data-testid={`fill-elsewhere-${name}`}>Not filled in on this page: {elsewhere.join("; ")}.</p>
      )}
    </div>
  );
}

/** The data checklist's names of its items, by id (`GET /evidence`'s coverage, which the Compound area reads already):
 *  a row no plain name is written for here is titled by the checklist item it is filed under. Read only when needed. */
function useChecklistNames(projectId: string, wanted: boolean): Map<string, string> {
  const read = useResource("/api/v1/projects/{project_id}/evidence", { project_id: projectId }, {
    enabled: wanted, select: (page) => new Map(page.coverage.map((c) => [c.req_id, c.label] as const)),
  });
  return read.data ?? new Map();
}

/** The model inputs of one tab, each in its row, with what waits on a person settled where it is. Items about no row
 *  of the tab (a placeholder parameter, a build) come first. `grouped`: the compound's rows under their building
 *  blocks, each block's open rows first. The rows to fill come last, folded, in each block. */
export function InputRows({ rows, todo, projectId, run, empty, emptyTitle = "Nothing on this tab yet", grouped }: {
  rows: Row[]; todo: TodoItem[]; projectId: string; run: Run; empty: ReactNode; emptyTitle?: string; grouped?: boolean;
}) {
  const known = (id: string) => paramLabel(id) !== id;
  const checklist = useChecklistNames(projectId, rows.some((r) => !known(r.id) && r.req_id));
  // a row's title: its plain name (lib/words.ts, a family's member by what its id says), else its checklist item's; the
  // CPF id is not shown (final review OWN-8)
  const nameOf = (r: Row) => (known(r.id) ? paramLabel(r.id) : (r.req_id ? checklist.get(r.req_id) : undefined) ?? paramLabel(r.id));
  const ids = new Set(rows.map((r) => r.id));
  const loose = todo.filter((t) => !ids.has(t.target));
  const sorted = [...rows].sort((a, b) => FIRST.indexOf(a.state) - FIRST.indexOf(b.state));
  const one = (r: Row) => <InputRow key={r.id} row={r} name={nameOf(r)} items={todo.filter((t) => t.target === r.id)} projectId={projectId} run={run} />;
  const blocks = [...BLOCKS.map(([name]) => name), "Other"]
    .map((name) => [name, sorted.filter((r) => blockOf(r.id) === name)] as const).filter(([, list]) => list.length);
  // "neutral" is the alternative to a pKa: offered only while the compound has none
  const pka = rows.some((r) => r.id.startsWith("phys.pka.") && r.id !== "phys.pka.neutral" && r.state !== "empty");
  const offered = (r: Row) => entryOf(r).kind !== "elsewhere" && !(r.id === "phys.pka.neutral" && pka);
  const filled = (list: Row[]) => list.filter((r) => r.state !== "empty");
  const toFill = (list: Row[]) => list.filter((r) => r.state === "empty" && offered(r));
  const elsewhere = (list: Row[]) => list.filter((r) => r.state === "empty" && entryOf(r).kind === "elsewhere")
    .map((r) => { const e = entryOf(r); return `${nameOf(r)} (${e.kind === "elsewhere" ? e.what : ""})`; });
  // what waits on a person: a value missing, in conflict or held; a row to fill is not open
  const open = (list: Row[]) => list.filter((r) => r.state !== "kept" && r.state !== "empty").length;
  // a formulation's values (form.<name>.*) are one formulation: one line, its values folded under it (final review OWN-8)
  const flat = (list: Row[]) => {
    const forms = new Map<string, Row[]>();
    const out: ReactNode[] = [];
    for (const r of list) {
      const m = FORM_ROW.exec(r.id);
      if (!m) { out.push(one(r)); continue; }
      if (!forms.has(m[1])) { forms.set(m[1], []); out.push(m[1]); }
      forms.get(m[1])!.push(r);
    }
    return out.map((x) => (typeof x === "string" ? <FormulationRow key={`form-${x}`} name={x} rows={forms.get(x)!} one={one} /> : x));
  };
  return (
    <>
      {loose.map((t, i) => <TodoCard key={`${t.kind}-${t.target}-${i}`} t={t} projectId={projectId} run={run} />)}
      {rows.length === 0 && loose.length === 0
        ? <EmptyState title={emptyTitle}>{empty}</EmptyState>
        : grouped ? blocks.map(([name, list]) => (
          <section key={name} className="input-block" aria-label={name} data-testid={`block-${name}`}>
            <h3 className="input-block-title">{name}
              {open(list) > 0 && <span className="muted"> · {open(list)} open</span>}</h3>
            {filled(list).map(one)}
            <ToFill rows={toFill(list)} elsewhere={elsewhere(list)} name={name} one={one} />
          </section>
        )) : <div className="input-block">{flat(filled(sorted))}<ToFill rows={toFill(sorted)} elsewhere={elsewhere(sorted)} name="rows" one={one} /></div>}
    </>
  );
}

/** A formulation's own values: `form.<name>.<part>` (the CPF's formulation family, pbpk_domain.cpf.formulations). */
const FORM_ROW = /^form\.(.+)\.(type|weibull\.[a-z0-9_]+|particles\.[a-z0-9_]+|bins)$/;

/** One formulation the model holds, in one line ("Test 10 mg · release Weibull · t50 18 min · shape 1.3"), with what of
 *  it waits on a person said beside it and its values, each with its source, folded under it. */
function FormulationRow({ name, rows, one }: { name: string; rows: Row[]; one: (r: Row) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const values = Object.fromEntries(rows.filter((r) => r.state === "kept")
    .map((r) => [FORM_ROW.exec(r.id)![2], { value: r.value, unit: r.unit }] as const));
  const waiting = rows.filter((r) => r.state !== "kept");
  const kept = rows.find((r) => r.id.endsWith(".type"))?.sources[0] ?? rows.find((r) => r.sources.length)?.sources[0];
  return (
    <div className={`input-row ${waiting.length ? "held" : "kept"}`} data-testid={`formulation-row-${name}`}>
      <div className="input-head">
        <div className="input-name"><strong data-testid={`formulation-line-${name}`}>{formulationLine(name, values)}</strong></div>
        <div className="input-source">{kept ? <>{kept.source.title || kept.source_type.toLowerCase().replace(/_/g, " ")}
          <span className="muted"> · grade {kept.confidence}</span></> : null}</div>
        <div className="input-state">
          <span className={`chip ${waiting.length ? "medium" : "low"}`}>{waiting.length ? `${waiting.length} to check` : "in the model"}</span>
        </div>
      </div>
      {waiting.map(one)}
      {rows.length > waiting.length && (
        <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)} data-testid={`formulation-values-${name}`}>
          {open ? "Hide its values" : `Its values and their sources (${rows.length - waiting.length})`}</button>
      )}
      {open && <div className="input-fill-rows">{rows.filter((r) => r.state === "kept").map(one)}</div>}
    </div>
  );
}
