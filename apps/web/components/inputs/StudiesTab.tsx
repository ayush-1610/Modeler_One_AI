"use client";

// Clinical studies (plan 2026-11-14 slice 3; the design text's "Tab Clinical studies"): one card per study, whichever
// reader found it, listed by how the study is given (IV · oral fasted · oral fed · multiple dose · other, as far as its
// facts say: plan §2.2.8), each row opening on its card; the sheets whose study is not stated yet; the studies in the
// model, with their role and regimen; and the observed data on no study card (the literature, a digitized figure, a typed
// table, the published model). The tools that add observed data are a short row of buttons, not a paragraph.

import { useEffect, useMemo, useState } from "react";

import type { View as ClientView } from "@/components/client/types";
import { DataTable, EmptyState, InlineIssue } from "@/components/kit";
import { SortHeader, TableFilter, TableMore } from "@/components/kit/SortableTable";
import { SUBJECT } from "@/components/delivery/DeliveryReview";
import { send, type Schema } from "@/lib/api";
import { useResource, useResources } from "@/lib/hooks";
import { blindedWhy, normLabel, type Subject } from "@/lib/inputsWork";
import { numericKey, ordinal, useTableView } from "@/lib/tableView";
import { DESIGNS, DESIGN_TITLE, type Design, designOf, plural, valueWord } from "@/lib/words";

import { SheetGroups } from "./ClientConfirm";
import { type CardEnv, StatusChip, cardStatus, focused, viaSheet } from "./cards/ConfirmPath";
import { MODEL, inputsAfter } from "./after";
import { StudyCard, studyNames } from "./cards/StudyCard";
import { type Run, TodoCard, type TodoItem } from "./InputsTodo";
import { ObservedDatasets, datasetsWaiting, useDatasets } from "./ObservedDatasets";
import { downloadTemplate } from "./TabFiles";

type Group = Schema<"ReviewGroup">;
type Card = Schema<"DeliverySubject">;

export type StudyRow = Schema<"InputStudyRow">;
/** A tool the head's "Add data" opened on this area (plan 2026-11-14 slice 1); `at` makes each choice a new one. */
export type Intent = { what: "type" | "digitize"; at: number };
export type Options = Record<"route" | "formulation" | "food_state" | "purpose" | "sex" | "population", string[]>;

const ROLE: Record<string, string> = {
  S1: "calibration (IV)", S2: "calibration (oral)", S3: "calibration (formulation)", S5: "external validation",
  S6: "application", SUPPORTIVE: "supportive",
};

const fact = (s: StudyRow, key: string) => s.facts[key] as string | number | null | undefined;

// the Role column sorts in the pipeline's order, not alphabetically
const roleOrder = ordinal(["S1", "S2", "S3", "S5", "S6", "SUPPORTIVE"]);
const SHOW = [
  { id: "all", label: "All", test: () => true },
  { id: "used", label: "Used", test: (s: StudyRow) => !s.excluded },
  { id: "out", label: "Left out", test: (s: StudyRow) => Boolean(s.excluded) },
  { id: "blinded", label: "Blinded", test: (s: StudyRow) => s.blinded },
  { id: "unjudged", label: "No mean profile", test: (s: StudyRow) => !s.evaluable && !s.excluded },
] as const;
type Show = (typeof SHOW)[number]["id"];
const STUDY_KEYS = {
  study: (s: StudyRow) => s.study_id,
  protocol: (s: StudyRow) => `${String(fact(s, "route") ?? "")} ${String(numericKey(fact(s, "dose_mg")) ?? "").padStart(12, "0")}`,
  role: (s: StudyRow) => roleOrder(s.role),
  used: (s: StudyRow) => (s.excluded ? 1 : 0),
};
const studyText = (s: StudyRow) => [s.study_id, s.purpose, s.origin, fact(s, "formulation"), fact(s, "formulation_name"), fact(s, "route")]
  .filter(Boolean).join(" ").replace(/_/g, " ");

/** The studies table: sortable by its heads, filtered by text or by where a study stands, 20 rows at a time. A study
 *  that needs the person (blinded, its regimen missing) or whose row is being typed in is never paged or hidden by the text filter (a pressed chip narrows it too). */
function StudiesTable({ studies, projectId, run, onIndividuals }: {
  studies: StudyRow[]; projectId: string; run: Run; onIndividuals: () => void;
}) {
  const [show, setShow] = useState<Show>("all");
  // a row the person has typed in (a regimen, a reason) stays shown, so its text is not lost; it is not counted as
  // needing attention, and focus alone (tabbing through) does not pin it
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set());
  const view = useTableView({
    rows: studies, keys: STUDY_KEYS, text: studyText, pageSize: 20,
    filter: SHOW.find((x) => x.id === show)!.test, filterKey: show,
    keep: (s) => s.blinded || s.regimen_missing, pin: (s) => touched.has(s.study_id),
  });
  const touch = (id: string) => { if (!touched.has(id)) setTouched(new Set([...touched, id])); };
  return (
    <div>
      <TableFilter view={view} placeholder="Filter studies: id, purpose, origin, formulation…" label="Filter the studies"
                   testId="studies-filter">
        <div className="table-chips" role="group" aria-label="Show studies">
          {SHOW.map((x) => (
            <button key={x.id} type="button" aria-pressed={show === x.id} data-testid={`studies-show-${x.id}`}
                    onClick={() => setShow(x.id)}>{x.label}</button>
          ))}
        </div>
      </TableFilter>
      <div className="table-scroll">
        <table className="studies-table">
          <caption className="sr-only">Studies</caption>
          <thead><tr>
            <SortHeader view={view} col="study" label="Study" /><SortHeader view={view} col="protocol" label="Protocol" />
            <SortHeader view={view} col="role" label="Role" /><th>Individual</th><th>Regimen</th>
            <SortHeader view={view} col="used" label="Used" />
          </tr></thead>
          <tbody className="paged-rows">
            {view.visible.map((s) => (
              <tr key={s.study_id} data-testid={`study-${s.study_id}`} id={`study-${s.study_id}`} className={s.excluded ? "left-out" : ""}
                  onInput={() => touch(s.study_id)}>
                <td><strong>{s.study_id}</strong>
                  <div className="muted fs-12">{(s.purpose ?? "").replace(/_/g, " ")} · {(s.origin ?? "").toLowerCase().replace("_", " ")}</div>
                  {s.blinded && <span className="chip medium" title="its values are hidden until the MAP is signed">blinded</span>}</td>
                <td>{String(fact(s, "route") ?? "").replace("_", " ")} · {fact(s, "dose_mg")} {s.facts.dose_per_kg ? "mg/kg" : "mg"} ·{" "}
                  {fact(s, "food_state")} · {fact(s, "formulation_name") ?? fact(s, "formulation")} · n {fact(s, "n")}
                  {!s.evaluable && !s.excluded && <div className="muted fs-12">no mean profile: not judged</div>}</td>
                <td>{s.role ? <span className="chip neutral" title={s.role_source === "proposed"
                  ? "proposed by the MS-01 split; changed on Review & sign, with a reason" : "the plan's placement"}>
                  {s.role} · {ROLE[s.role] ?? s.role.toLowerCase()}</span> : <span className="muted">—</span>}</td>
                <td><button type="button" className="link-btn" onClick={onIndividuals}>
                  {{ entered: "entered", published: "published individual", default: "healthy adult default", missing: "not stated" }[s.demographics]}
                </button></td>
                <td><Regimen s={s} projectId={projectId} run={run} /></td>
                <td>{s.excluded && <div className="muted fs-12">left out: {s.excluded}</div>}
                  <LeaveOut s={s} projectId={projectId} run={run} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {view.visible.length === 0 && <p className="muted table-none">No study matches this filter.</p>}
      <TableMore view={view} noun="studies" testId="studies-more" />
    </div>
  );
}

function Regimen({ s, projectId, run }: { s: StudyRow; projectId: string; run: Run }) {
  const [doses, setDoses] = useState("");
  const [every, setEvery] = useState("");
  if (fact(s, "design") !== "MD") return <span className="muted">single dose</span>;
  if (!s.regimen_missing) return <span>{fact(s, "n_doses")} doses every {fact(s, "dosing_interval_h")} h</span>;
  return (
    <div className="row gap-4">
      <input placeholder="doses" value={doses} onChange={(x) => setDoses(x.target.value)} className="w-70" aria-label={`doses for ${s.study_id}`} />
      <input placeholder="every (h)" value={every} onChange={(x) => setEvery(x.target.value)} className="w-80" aria-label={`interval for ${s.study_id}`} />
      <button className="btn primary" disabled={!s.dataset_id || !(Number(doses) > 0 && Number(every) > 0)}
              onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:study",
                                                 { project_id: projectId, dataset_id: s.dataset_id ?? "" },
                                                 { changes: { n_doses: Number(doses), dosing_interval_h: Number(every) } }),
                                      `${s.study_id}: ${doses} doses every ${every} h.`, MODEL)}>Save</button>
    </div>
  );
}

/** Leave a study out of the model, or take it back, with the reason (kept with the inputs and shown at the review). One
 *  small button per row; the reason is asked for only when it is pressed (the 2026-11-11 audit, item 4). */
function LeaveOut({ s, projectId, run }: { s: StudyRow; projectId: string; run: Run }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const verb = s.excluded ? "Include again" : "Leave out";
  if (!open) {
    return (
      <button type="button" className="link-btn" onClick={() => setOpen(true)}
              aria-label={s.excluded ? `Include ${s.study_id} again` : `Leave ${s.study_id} out`}>{verb}…</button>
    );
  }
  return (
    <div className="row gap-4">
      <input autoFocus placeholder={s.excluded ? "why include it again" : "why leave it out"} value={reason}
             onChange={(x) => setReason(x.target.value)} className="w-160" aria-label={`reason for ${s.study_id}`}
             onKeyDown={(x) => { if (x.key === "Escape") setOpen(false); }} />
      <button className="btn" disabled={!reason.trim()}
              onClick={() => void run(() => send("put", "/api/v1/projects/{project_id}/inputs/choices", { project_id: projectId },
                                                 { kind: "excluded_studies", key: s.study_id, value: s.excluded ? null : reason, reason }),
                                      s.excluded ? `${s.study_id} is used again.` : `${s.study_id} is left out: ${reason}.`, inputsAfter(projectId, []))}>
        {verb}
      </button>
      <button type="button" className="link-btn" onClick={() => setOpen(false)}>Cancel</button>
    </div>
  );
}

const list = (text: string) => text.split(/[\s,;]+/).filter(Boolean).map(Number);

/** A table typed in by hand (the fallback when no sheet or figure can be read): the study's facts, its mean profile and
 *  the source (POST /datasets; the manual path). */
function TypedTable({ projectId, run, options }: { projectId: string; run: Run; options: Options }) {
  const [f, setF] = useState({ study_id: "", route: "oral", dose_mg: "", formulation: "solution", food_state: "fasted", n: "",
                               purpose: "model_building", time_unit: "h", unit: "ng/ml", times: "", values: "", title: "", link: "",
                               origin: "LITERATURE", analyte: "", product: "" });
  // a model system: each study names the analyte it measures and the product it gives (MS-01 v1.3 §6.5); chosen, never guessed
  const system = useResource("/api/v1/projects/{project_id}/system", { project_id: projectId }).data?.system ?? null;
  const set = (k: keyof typeof f) => (x: { target: { value: string } }) => setF({ ...f, [k]: x.target.value });
  const times = list(f.times), values = list(f.values);
  const example = f.origin === "ILLUSTRATIVE";
  const ok = f.study_id.trim() && Number(f.dose_mg) > 0 && Number(f.n) > 0 && times.length > 1 && times.length === values.length
    && !times.some(Number.isNaN) && !values.some(Number.isNaN) && (example || f.title.trim() || f.link.trim())
    && (!system || (f.analyte && f.product));
  const pick = (k: keyof typeof f, values: string[]) => (
    <select value={f[k]} onChange={set(k)} aria-label={k.replace("_", " ")}>{values.map((v) => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}</select>
  );
  return (
    <div className="typed-table" data-testid="typed-table">
      <div className="row gap-6">
        <input placeholder="study id" value={f.study_id} onChange={set("study_id")} className="w-140" aria-label="study id" />
        {pick("route", options.route)}
        <input placeholder="dose (mg)" value={f.dose_mg} onChange={set("dose_mg")} className="w-90" aria-label="dose" />
        {pick("formulation", options.formulation)}
        {pick("food_state", options.food_state)}
        <input placeholder="n" value={f.n} onChange={set("n")} className="w-60" aria-label="subjects" />
        {pick("purpose", options.purpose)}
        <select value={f.origin} onChange={set("origin")} aria-label="where the data come from" data-testid="typed-origin">
          <option value="LITERATURE">a published table or text</option>
          <option value="CLIENT">the client&apos;s data</option>
          <option value="ILLUSTRATIVE">example data (test only, never evidence)</option>
        </select>
      </div>
      {system && (
        <div className="row gap-6 mt-4">
          <select value={f.analyte} onChange={set("analyte")} aria-label="analyte measured" data-testid="typed-analyte">
            <option value="">analyte measured…</option>
            {system.analytes.map((a) => (
              <option key={a.name} value={a.name}>
                {a.name}{a.judged_at.length ? ` (judged at ${a.judged_at.join(", ")})` : " (reported, not judged)"}
              </option>
            ))}
          </select>
          <select value={f.product} onChange={set("product")} aria-label="product given" data-testid="typed-product">
            <option value="">product given…</option>
            {Object.keys(system.products).map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
      )}
      <div className="row gap-6 mt-4">
        <input placeholder="times, e.g. 0.5 1 2 4 8" value={f.times} onChange={set("times")} className="flex-1 minw-180" aria-label="times" />
        <input placeholder="unit" value={f.time_unit} onChange={set("time_unit")} className="w-60" aria-label="time unit" />
        <input placeholder="mean concentrations" value={f.values} onChange={set("values")} className="flex-1 minw-180" aria-label="values" />
        <input placeholder="unit" value={f.unit} onChange={set("unit")} className="w-80" aria-label="concentration unit" />
      </div>
      <div className="row gap-6 mt-4">
        <input placeholder="source title" value={f.title} onChange={set("title")} className="flex-1 minw-180" aria-label="source title" />
        <input placeholder="DOI or URL" value={f.link} onChange={set("link")} className="w-200" aria-label="source link" />
        <button className="btn primary" disabled={!ok}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/datasets", { project_id: projectId }, {
                  study: { study_id: f.study_id.trim(), route: f.route, dose_mg: Number(f.dose_mg), formulation: f.formulation,
                           food_state: f.food_state, n: Number(f.n), n_timepoints: times.length,
                           ...(system ? { analyte: f.analyte, product: f.product } : {}) },
                  ...(system ? { analyte: f.analyte } : {}),
                  time_unit: f.time_unit, unit: f.unit, purpose: f.purpose,
                  origin: f.origin as "LITERATURE" | "CLIENT" | "ILLUSTRATIVE",
                  series: [{ times, values, n: Number(f.n), statistic: "arithmetic_mean" }],
                  source: { title: f.title, ...(f.link.startsWith("10.") ? { doi: f.link } : f.link ? { url: f.link } : {}) },
                }), `${f.study_id}: the typed table is added.`, MODEL)}>
          Add the study
        </button>
      </div>
      {times.length !== values.length && values.length > 0 && <p className="inline-issue warn">{times.length} times but {values.length} values.</p>}
    </div>
  );
}

/** A study's facts as far as they are known for the list (route, food state, design, dose): the study in the model,
 *  the sheet form's facts, the delivery's facts of its files. */
function factsOf(s: Subject, inModel: StudyRow | undefined, card: Card | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  const put = (k: string, v: unknown) => { if (v !== null && v !== undefined && v !== "" && !(k in out)) out[k] = String(v); };
  if (inModel) for (const k of ["route", "food_state", "design", "dose_mg"]) put(k, inModel.facts[k]);
  // a group the delivery blinds withholds its facts (D-15): nothing of it is said on the row
  for (const g of s.groups.filter((x) => !x.blinded)) {
    for (const f of g.facts) put(f.field, typeof f.stored === "string" || typeof f.stored === "number" ? f.stored : f.value);
  }
  for (const v of (card?.tables ?? []).filter((t) => t.kind === "facts").flatMap((t) => t.values)) {
    if (v.blinded || v.status === "superseded" || v.status === "excluded") continue;
    put(v.field === "dose" ? (v.unit === "mg" ? "dose_mg" : "dose") : v.field, v.field === "dose" && v.unit !== "mg" ? `${v.value} ${v.unit ?? ""}`.trim() : v.value);
  }
  return out;
}

/** What a study's row says of how it is given: "Oral · 50 mg · fasted". */
const givenText = (f: Record<string, string>) => [f.route ? valueWord(f.route) : "", f.dose_mg ? `${f.dose_mg} mg` : f.dose ?? "",
                                                   f.food_state ? valueWord(f.food_state).toLowerCase() : "", f.design === "MD" ? "multiple dose" : ""]
  .filter(Boolean).join(" · ") || "not stated yet";

const SHOW_CARDS = [
  { id: "all", label: "All", test: () => true },
  { id: "open", label: "To confirm", test: (s: Subject) => !s.done },
  { id: "done", label: "In the model", test: (s: Subject) => s.done },
] as const;
type ShowCards = (typeof SHOW_CARDS)[number]["id"];

/** The client's studies, one card each, by how they are given; a row opens on its card. The first study to confirm is
 *  open; the others open from their row, or from To do. */
function StudyList({ subjects, studies, env, unpromised, only, onShow }: {
  subjects: Subject[]; studies: StudyRow[]; env: CardEnv; unpromised: string[]; only: boolean; onShow: (id: string) => void;
}) {
  const [show, setShow] = useState<ShowCards>("all");
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  // the facts of a study signed on the delivery are on its card (read two at a time, under the key its card uses)
  const rows = subjects.filter((s) => s.path === "delivery" && s.row && !s.done && !s.blinded).map((s) => s.row!);
  const read = useResources(SUBJECT, rows.map((r) => ({ project_id: env.projectId, type: r.subject_type, subject: r.subject })),
                            { limit: 2, staleTime: 60_000 });
  const cards = new Map(rows.map((r, i) => [r.subject, read[i]?.data ?? null] as const));
  // what waits among a study's datasets (blinded, an overlay to check), said on its row: acted on in its card
  const datasets = useDatasets(env.projectId) ?? [];
  const waitingOn = (s: Subject) => { const named = studyNames(s); return datasetsWaiting(datasets.filter((d) => named(String(d.study.study_id)))); };
  const inModel = (s: Subject) => studies.find((x) => normLabel(x.study_id) === normLabel(s.label));
  const facts = (s: Subject) => factsOf(s, inModel(s), s.row ? cards.get(s.row.subject) : null);
  const designs = new Map(subjects.map((s) => [s.key, designOf(facts(s))] as const));
  // the first to confirm, in the order the list shows them
  const current = DESIGNS.flatMap((d) => subjects.filter((s) => designs.get(s.key) === d)).find((s) => !s.done && !s.blinded)?.key ?? null;
  // the study open as "the first to confirm" stays open once confirmed, while the next one opens
  const [shown, setShown] = useState<string | null>(current);
  useEffect(() => {
    if (current === shown) return;
    if (shown && subjects.find((s) => s.key === shown)?.done) setToggled((was) => (shown in was ? was : { ...was, [shown]: true }));
    setShown(current);
  }, [current]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const target = env.focus ? subjects.find((s) => focused(s, env.focus)) : undefined;
    if (target) setToggled((was) => ({ ...was, [target.key]: true }));
  }, [env.focus]); // eslint-disable-line react-hooks/exhaustive-deps
  // up to three studies are all open; past three, the first to confirm (the owner, 2026-11-05: "one by one"); the one
  // that was the first to confirm stays open until the effect above has seen why it no longer is (just confirmed: it
  // stays open, with what its signature loaded)
  const isOpen = (s: Subject) => toggled[s.key] ?? (subjects.length <= 3 || s.key === current || s.key === shown);
  const filter = SHOW_CARDS.find((x) => x.id === show)!.test;
  const design = (s: Subject): Design => designs.get(s.key) ?? "other";
  // one table, by design: a study whose facts move it to another design stays the same row, and its card stays open
  const listed = DESIGNS.flatMap((d) => subjects.filter((s) => design(s) === d && filter(s) && (!only || !s.done)));
  const toggle = (s: Subject) => {
    if (s.path === "delivery" || !s.groups[0]) return `delivery-subject-open-${s.row?.subject ?? s.key}`;
    return `toggle-${s.groups[0].id}`;
  };
  return (
    <section className="studies-list" data-testid="studies-list" aria-label="The client's studies">
      <div className="studies-list-head">
        <h2 className="area-section-title">The client&apos;s studies <span className="muted">({subjects.length})</span></h2>
        <div className="table-chips" role="group" aria-label="Show the studies">
          {SHOW_CARDS.map((x) => (
            <button key={x.id} type="button" aria-pressed={show === x.id} data-testid={`studies-cards-${x.id}`} onClick={() => setShow(x.id)}>
              {x.label}</button>
          ))}
        </div>
      </div>
      {listed.length === 0 && <p className="muted m-0">{only ? "No study waits for you." : "No study here with this filter."}</p>}
      {listed.length > 0 && (
          <DataTable<Subject> rows={listed} rowKey={(s) => s.key} className="studies-cards" label="The client's studies, by how each is given"
            rowTestId={(s) => `study-row-${s.key}`} rowClassName={(s) => (isOpen(s) ? "open" : undefined)}
            group={{ of: design, testId: (d) => `studies-design-${d}`,
                     title: (d, rows) => <span className="studies-design-title">{DESIGN_TITLE[d as Design]} <span className="muted">({rows.length})</span></span> }}
            after={(s) => (isOpen(s) ? <StudyCard subject={s} env={env} unpromised={unpromised} onShow={() => onShow(inModel(s)?.study_id ?? s.label)} /> : null)}
            columns={[
              { key: "study", label: "Study", render: (s) => (
                <>
                  <strong className="card-title">{s.label}</strong>
                  {s.aliases.length > 0 && <div className="muted fs-12">also read as {s.aliases.join(", ")}</div>}
                  {s.blinded && <span className="chip neutral">blinded until the plan is signed</span>}
                  {/* why, from the card's reason (round 4): a wrong name match is seen in the list too */}
                  {s.blinded && blindedWhy(s) && <div className="muted fs-12" data-testid={`study-blinded-why-${s.key}`}>because {blindedWhy(s)}</div>}
                </>
              ) },
              { key: "given", label: "How it is given", render: (s) => <span className="fs-13">{givenText(facts(s))}</span> },
              { key: "data", label: "Data", render: (s) => {
                const datasets = s.groups.reduce((n, g) => n + g.items.filter((i) => i.data).length, 0);
                const sheets = s.groups.reduce((n, g) => n + g.items.filter((i) => i.kind === "draft").length, 0);
                const waiting = waitingOn(s);
                return <span className="fs-13">{[s.row ? plural(s.row.values, "value") : "", datasets ? plural(datasets, "dataset") : "",
                                                 sheets ? plural(sheets, "sheet") + " to read" : ""].filter(Boolean).join(" · ") || "—"}
                  {waiting && <span className="muted" data-testid={`study-datasets-waiting-${s.key}`}> · {waiting}</span>}</span>;
              } },
              { key: "status", label: "Status", render: (s) => <StatusChip status={cardStatus(s, env.work)} testId={`study-status-${s.key}`} /> },
              { key: "confirm", label: "Confirmed with", render: (s) => <span className="muted fs-13">{viaSheet(s) ? "the sheet form"
                : s.path === "delivery" ? "Confirm and sign" : s.path === "sheet-form" ? "Confirm" : "not available yet"}</span> },
              { key: "role", label: "Role", render: (s) => { const r = inModel(s)?.role; return r ? <span className="fs-13">{r} · {ROLE[r] ?? r.toLowerCase()}</span> : <span className="muted">—</span>; } },
              { key: "open", label: "", render: (s) => (
                <button type="button" className="btn small" aria-expanded={isOpen(s)} aria-label={`${isOpen(s) ? "Close" : "Open"} the card of ${s.label}`}
                        data-testid={toggle(s)} onClick={() => setToggled({ ...toggled, [s.key]: !isOpen(s) })}>{isOpen(s) ? "Close" : "Open"}</button>
              ) },
            ]} />
      )}
    </section>
  );
}

/** Clinical studies (redesign §3.2; plan 2026-11-14 slice 3): the client's studies, one card each; the sheets whose
 *  study is not stated; the studies in the model, with the role the MS-01 split proposes (changed only on Review & sign),
 *  whether each is blinded (D-15), its regimen and whether it is used; and the observed data on no study card. The
 *  client's files and their sheets are in Client files (plan 2026-11-14 slice 1). */
export function StudiesTab({ studies, todo, projectId, run, options, onIndividuals, client, intent, only = false, env, subjects, sheets }: {
  studies: StudyRow[]; todo: TodoItem[]; projectId: string; run: Run; options: Options; onIndividuals: () => void;
  client: ClientView | undefined;
  /** "Type a table in" or "Digitize a figure", chosen in the head's "Add data" */
  intent?: Intent | null;
  /** "Only what needs me": what waits for the person, not the studies in the model or the other observed data */
  only?: boolean;
  env: CardEnv;
  /** the client's studies, one card each (lib/inputsWork.ts) */
  subjects: Subject[];
  /** the sheets whose study is not stated yet */
  sheets: Group[];
}) {
  const unpromised = client?.reconciliation.unpromised ?? [];
  const [typing, setTyping] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const template = async () => setProblem(await downloadTemplate(client?.template));
  useEffect(() => {
    if (intent?.what !== "type") return;
    setTyping(true);
    window.setTimeout(() => document.querySelector('[data-testid="typed-table"]')?.scrollIntoView({ block: "start", behavior: "smooth" }), 80);
  }, [intent]);
  // a dataset whose study has a card is shown on that card, not again among the other observed data
  const onCard = useMemo(() => {
    const tests = subjects.map(studyNames);
    return (studyId: string) => tests.some((t) => t(studyId));
  }, [subjects]);
  const show = (id: string) => {
    const el = document.getElementById(`study-${id}`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  };
  const waiting = subjects.filter((s) => !s.done).length;
  // what the /inputs to-do says of the observed data (no dataset yet; individual subjects only), once no client study
  // waits for confirmation (until then it is settled by confirming one, as To do counts it); its regimen rows are filled
  // in the table of studies in the model
  const notes = todo.filter((t) => t.kind !== "regimen" && !(t.kind === "datasets" && waiting > 0));
  return (
    <>
      {subjects.length > 0 && <StudyList subjects={subjects} studies={studies} env={env} unpromised={unpromised} only={only} onShow={show} />}
      {!only && subjects.length === 0 && (
        <EmptyState title="No client study yet">Add the client&apos;s files with Add data at the top of the page, or fill the client-data
          template; each study they hold gets its card here, to confirm.</EmptyState>
      )}
      <SheetGroups projectId={projectId} groups={sheets.filter((g) => !only || g.state === "to_confirm")} run={run}
                   title="Sheets not linked to a study yet" testId="studies-sheets" />
      {notes.map((t, i) => <TodoCard key={`${t.kind}-${t.target}-${i}`} t={t} projectId={projectId} run={run} />)}
      {!only && (
        <section className="studies-in-model" data-testid="studies-in-model">
          {/* counted as the status line counts them (lib/inputsWork.ts `inModel`): a study signed on the delivery once,
              its arms' datasets beside it */}
          <h2 className="area-section-title">In the model <span className="muted" data-testid="studies-in-model-count">({plural(env.work.inModel.studies, "study", "studies")}
            {env.work.inModel.datasets !== env.work.inModel.studies ? `, ${plural(env.work.inModel.datasets, "dataset")}` : ""})</span></h2>
          {/* what the client delivered that the data plan did not ask for, besides a dataset (each says so on its line) */}
          {unpromised.some((u) => !u.startsWith("dataset ")) && (
            <p className="muted fs-13 m-0-0-8" data-testid="unpromised-other">Delivered, not in the data plan:{" "}
              {unpromised.filter((u) => !u.startsWith("dataset ")).join("; ")}</p>
          )}
          {studies.length === 0 ? (
            <EmptyState title="No study confirmed yet">{waiting ? `${plural(waiting, "study waits", "studies wait")} for confirmation above. ` : ""}
              A confirmed study, a table typed in, a digitized figure or a published model&apos;s study appears here with its role.</EmptyState>
          ) : <StudiesTable studies={studies} projectId={projectId} run={run} onIndividuals={onIndividuals} />}
        </section>
      )}
      {only && studies.some((s) => s.regimen_missing) && (
        <StudiesTable studies={studies.filter((s) => s.regimen_missing)} projectId={projectId} run={run} onIndividuals={onIndividuals} />
      )}
      {!only && (
        <section className="add-data" data-testid="add-data">
          <h3>Add observed data</h3>
          <div className="row gap-6">
            <button type="button" className="btn small" onClick={template} data-testid="download-template">The client-data template</button>
            <button type="button" className="btn small" onClick={() => setTyping(!typing)} data-testid="type-table" aria-expanded={typing}>
              {typing ? "Close the typed table" : "Type a table in"}</button>
            <span className="muted fs-13">Digitize a figure or find observed data with AI under Other observed data, below.</span>
          </div>
          {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
          {typing && <TypedTable projectId={projectId} run={run} options={options} />}
        </section>
      )}
      {!only && (
        <div id="observed-datasets">
          <ObservedDatasets projectId={projectId} run={run} digitize={intent?.what === "digitize" ? intent.at : undefined} except={onCard}
                            unpromised={unpromised} />
        </div>
      )}
    </>
  );
}
