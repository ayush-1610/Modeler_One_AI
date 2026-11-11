"use client";

import { useId, useRef, useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Clip } from "@/components/kit/Clip";
import { send, type Envelope, type Schema } from "@/lib/api";

export type Ev = {
  id: string; target: string; value: number | string | null; unit: string | null; value_pksim: number | null;
  unit_pksim: string | null; state: string;
  // a held number without its PK-Sim value: the PK-Sim units harvested for its parameter ("" dimensionless), or null
  // when none is needed or none is harvested (the API's `inputs.pksim_units`)
  allowed_units?: string[] | null; confidence: string; flags: string[]; provider: string; source_type: string;
  conditions: Record<string, string>; quote: string;
  source: { title: string; authors: string; year: number | null; doi: string | null; page: number | null; locator: string | null;
            doc_sha256?: string | null; url?: string | null; pmid?: string | null };
};
type DatasetRow = { id: string; study_id: string; purpose: string; origin: string; provider: string; state: string; kind: string;
                    statistics: string[]; series: number };
export type TodoItem = {
  kind: "conflict" | "correct" | "pka" | "missing" | "datasets" | "formulation" | "process" | "unit" | "check" | "review"
    | "regimen" | "demographics" | "confirm";
  target: string; message: string; items: (Ev | DatasetRow)[]; evidence?: string[];
  suggestions?: { targets: string[]; molecules: string[] };
  identity?: { value: number; unit: string; quote: string; cid: string; name: string } | null;
  warnings?: string[];
  dataset_id?: string | null;
  tab?: string;
};
export type Run = <T>(fn: () => Promise<Envelope<T>>, ok: string) => Promise<string | null>;

export const ORDER = ["confirm", "conflict", "correct", "pka", "missing", "review", "regimen", "demographics", "datasets", "formulation", "process",
               "unit", "check"];
export const TITLE: Record<string, string> = {
  conflict: "Values more than 2-fold apart: keep one", correct: "Filed under the wrong parameter", pka: "pKa: acidic or basic?",
  missing: "Missing for S0", datasets: "Observed data to judge the model on", formulation: "Formulation of the tablet studies",
  process: "Which PK-Sim process carries the pathway", unit: "Unit to convert", check: "Software build",
  review: "Held until you check it", regimen: "Multiple-dose regimen", demographics: "Demographics",
  confirm: "The client's data to confirm",
};
export const LABEL: Record<string, string> = {
  "phys.mw": "Molecular weight", "phys.logp": "Lipophilicity", "bind.fu": "Fraction unbound in plasma",
  "phys.solubility.ref": "Reference solubility", "phys.pka": "pKa", elim: "An elimination pathway",
  "perm.intestinal": "Intestinal permeability", "elim.renal.gfr_fraction": "GFR fraction (renal filtration)",
  "elim.biliary.cl": "Biliary clearance", "dist.bp_ratio": "Blood-to-plasma ratio",
  "elim.fe_urine": "Fraction excreted unchanged in urine (fe)", "elim.fm.<enzyme>": "Fraction metabolised by an enzyme (fm)",
};

export const fmt = (v: number | string | null) => (v === null ? "—" : typeof v === "number" ? +v.toPrecision(4) : v);

/** A name to read for a CPF id: its LABEL, else, for a harvested PK-Sim path ("indiv.Organism|Lumen|Caecum|Effective
 *  surface area enhancement factor"), the path's own last segment after its container ("Caecum · Effective surface area
 *  enhancement factor"); an expression profile document by its molecule. Only the path's segments are used, verbatim
 *  (no PK-Sim name is made up); the full id is still shown once beside it. */
export function readable(id: string): string {
  if (LABEL[id]) return LABEL[id];
  const profile = /^expr\.profile\.(.+)$/.exec(id);
  if (profile) return `${profile[1]} · expression profile`;
  const path = /^(?:indiv|expr)\.(.+)$/.exec(id)?.[1];
  if (!path || !path.includes("|")) return id;
  const parts = path.split("|");
  const container = parts.length > 2 || parts[0] !== "Organism" ? parts[parts.length - 2] : null;
  return container ? `${container} · ${parts[parts.length - 1]}` : parts[parts.length - 1];
}

/** A flag code said as a sentence; the code stays in the title for traceability (modeler_project.evidence). */
function flagText(f: string): string {
  const [code, ...rest] = f.split(": ");
  const detail = rest.join(": ");
  if (code === "needs_conversion") return `No automatic conversion to PK-Sim's unit${detail ? ` (${detail})` : ""}.`;
  if (f === "value_not_in_quote") return "The number is not in the quoted text: check it against the source.";
  if (code === "species_mismatch") return `Measured in another species${detail ? ` (${detail})` : ""}, not human.`;
  const range = /^outside_physical_range (.+)$/.exec(f);
  if (range) return `Outside the physically possible range (${range[1]}).`;
  return f;
}

/** A stored string value: a long one (an expression profile document) is clipped with "show all", never printed whole. */
export const ValueText = ({ v }: { v: number | string | null }) =>
  typeof v === "string" ? <Clip text={v} max={40} /> : <>{fmt(v)}</>;

export function Source({ e }: { e: Ev }) {
  const s = e.source;
  const who = [s.authors, s.year].filter(Boolean).join(" ");
  return (
    <div className="fs-12">
      <div>{s.title || e.source_type.toLowerCase()}{who ? ` · ${who}` : ""}{s.page ? ` · p.${s.page}` : ""}{s.locator ? ` · ${s.locator}` : ""}</div>
      <div className="muted">{e.provider.toLowerCase()} · {e.source_type.toLowerCase().replace(/_/g, " ")} · grade {e.confidence}
        {Object.keys(e.conditions).length > 0 && ` · ${Object.entries(e.conditions).map(([k, v]) => `${k} ${v}`).join(", ")}`}</div>
      {e.quote && <div className="quote">“{e.quote}”</div>}
      {e.flags.length > 0 && <ul className="flags">{e.flags.map((f) => <li key={f} title={f}>{flagText(f)}</li>)}</ul>}
    </div>
  );
}

export function Value({ e }: { e: Ev }) {
  return (
    <span>
      <strong><ValueText v={e.value} /></strong> {e.unit ?? ""}
      {e.value_pksim !== null && (e.value_pksim !== e.value || (e.unit_pksim ?? null) !== (e.unit ?? null)) &&
        <div className="muted fs-12">PK-Sim: {fmt(e.value_pksim)} {e.unit_pksim ?? ""}</div>}
    </span>
  );
}

function Conflict({ t, projectId, run }: { t: TodoItem; projectId: string; run: Run }) {
  const [keep, setKeep] = useState("");
  const [reason, setReason] = useState("");
  const items = t.items as Ev[];
  return (
    <>
      <table className="todo-table">
        <thead><tr><th /><th>Value</th><th>Source</th></tr></thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.id} className={keep === e.id ? "picked" : ""} onClick={() => setKeep(e.id)}>
              <td><input type="radio" name={`keep-${t.target}`} checked={keep === e.id} onChange={() => setKeep(e.id)} aria-label={`keep ${e.id}`} /></td>
              <td><Value e={e} /></td>
              <td><Source e={e} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row gap-6">
        <input placeholder="why this value (kept in the audit trail)" value={reason} onChange={(e) => setReason(e.target.value)} className="flex-1 minw-220" aria-label={`reason for ${t.target}`} />
        <button className="btn primary" disabled={!keep || !reason.trim()}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:choose", { project_id: projectId, evidence_id: keep }, { reason }),
                                        `${t.target}: one value kept, the others rejected with your reason.`)}>
          Keep the selected value, reject the others
        </button>
      </div>
    </>
  );
}

function Correction({ e, t, projectId, run }: { e: Ev; t: TodoItem; projectId: string; run: Run }) {
  const [target, setTarget] = useState(t.suggestions?.targets[0] ?? "");
  const [molecule, setMolecule] = useState("");
  const [kind, setKind] = useState("");
  const [reason, setReason] = useState("");
  const [number, setNumber] = useState("");
  const [unit, setUnit] = useState("");
  const statement = typeof e.value === "string";
  const concrete = target.replace("<enzyme>", molecule || "<enzyme>");
  const needsMolecule = target.includes("<enzyme>");
  const pka = t.kind === "pka";
  return (
    <div className="todo-row">
      <div className="row items-start gap-14">
        <div className="minw-110"><code>{e.target}</code><div><Value e={e} /></div></div>
        <div className="flex-1 minw-220"><Source e={e} /></div>
      </div>
      <div className="row gap-6 mt-6">
        {pka ? (
          <select value={kind} onChange={(x) => setKind(x.target.value)} aria-label={`acid or base for ${e.id}`}>
            <option value="">acidic or basic?</option><option value="acid">acidic pKa</option><option value="base">basic pKa</option>
          </select>
        ) : (
          <>
            <select value={target} onChange={(x) => setTarget(x.target.value)} aria-label={`parameter for ${e.id}`}>
              {(t.suggestions?.targets ?? []).map((s) => <option key={s} value={s}>{LABEL[s] ? `${LABEL[s]} (${s})` : s}</option>)}
            </select>
            {needsMolecule && (
              <select value={molecule} onChange={(x) => setMolecule(x.target.value)} aria-label={`enzyme for ${e.id}`}>
                <option value="">enzyme…</option>
                {(t.suggestions?.molecules ?? []).map((m) => <option key={m}>{m}</option>)}
              </select>
            )}
            {statement && <>
              <input type="number" step="any" placeholder="number in the quote" value={number} onChange={(x) => setNumber(x.target.value)} className="w-150" aria-label={`number for ${e.id}`} />
              <input placeholder="unit" value={unit} onChange={(x) => setUnit(x.target.value)} className="w-80" aria-label={`unit for ${e.id}`} />
            </>}
          </>
        )}
        <input placeholder="why" value={reason} onChange={(x) => setReason(x.target.value)} className="flex-1 minw-160"
               aria-label={`reason for ${e.id}`} />
        <button className="btn primary" disabled={!reason.trim() || (pka ? !kind : !target || (needsMolecule && !molecule) || (statement && !number))}
                title={statement ? "a sentence becomes a value only as a number its quote states" : undefined}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:correct",
                                                      { project_id: projectId, evidence_id: e.id },
                                                      pka ? { conditions: { type: kind }, reason }
                                                          : { target: concrete, reason, ...(statement ? { value: Number(number), unit: unit || null } : {}) }),
                                        pka ? `pKa ${fmt(e.value)} recorded as ${kind === "acid" ? "acidic" : "basic"}.`
                                            : `Filed as ${concrete}: check its value below and accept it.`)}>
          {pka ? "Save" : "Correct"}
        </button>
        <button className="btn" disabled={!reason.trim()}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:decide", { project_id: projectId, evidence_id: e.id }, { state: "REJECTED", reason }),
                                        `${e.id} rejected.`)}>Reject</button>
      </div>
    </div>
  );
}

const UNSET = "\u0000unset";   // no unit chosen yet ("" is the dimensionless unit, a real choice)
const unitLabel = (u: string) => (u === "" ? "dimensionless (no unit)" : u);

/** Accept or reject one held value. A number with no PK-Sim value yet (no automatic conversion) is accepted only with
 *  the value the person types in PK-Sim's unit, the unit chosen from those harvested for its parameter (owner's
 *  decision 3 of 2026-11-11): the field starts empty and nothing is prefilled or converted. */
export function Decide({ e, projectId, run, card }: { e: Ev; projectId: string; run: Run; card?: string }) {
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const why = useRef<HTMLInputElement>(null);
  const [typed, setTyped] = useState("");
  const [unit, setUnit] = useState(UNSET);
  const ids = useId();
  const needsValue = typeof e.value === "number" && e.value_pksim === null;
  const units = e.allowed_units ?? null;
  const number = typed.trim() === "" ? NaN : Number(typed.trim());
  const valueReady = !needsValue || (units !== null && Number.isFinite(number) && unit !== UNSET);
  const body = needsValue ? { state: "ACCEPTED" as const, reason, value_pksim: number, unit_pksim: unit === UNSET ? null : unit || null }
                          : { state: "ACCEPTED" as const, reason };
  const accepted = needsValue ? `${e.target} = ${typed.trim()}${unit && unit !== UNSET ? ` ${unit}` : ""} accepted, typed in PK-Sim's unit.`
                              : `${e.target} = ${fmt(e.value_pksim ?? e.value)} accepted.`;
  const shown = typeof e.value === "string" && e.value.length > 40 ? `${e.value.slice(0, 40)}…` : String(fmt(e.value));
  const decide = async (body: Schema<"Decision">, ok: string) => {
    const next = afterThis(why.current);
    const p = await run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:decide",
                                   { project_id: projectId, evidence_id: e.id }, body), ok);
    setProblem(p);
    if (!p) next();
  };
  return (
    <div className="todo-row">
      <div className="row items-start gap-14">
        <div className="minw-110">{e.target !== card && <code>{e.target}</code>}<div><Value e={e} /></div></div>
        <div className="flex-1 minw-220"><Source e={e} /></div>
      </div>
      {needsValue && (
        <div className="pksim-entry" data-testid={`pksim-entry-${e.id}`}>
          {units !== null ? (
            <>
              <p className="muted fs-13 m-0">No automatic conversion: type the value in PK-Sim&apos;s unit to accept it.</p>
              <div className="row gap-6 pksim-controls">
                <label className="pksim-field" htmlFor={`${ids}-v`}>
                  <span>Value in PK-Sim&apos;s unit</span>
                  <input id={`${ids}-v`} type="text" inputMode="decimal" autoComplete="off" value={typed}
                         onChange={(x) => setTyped(x.target.value)} aria-invalid={typed.trim() !== "" && !Number.isFinite(number)} />
                </label>
                <label className="pksim-field" htmlFor={`${ids}-u`}>
                  <span>PK-Sim unit</span>
                  <select id={`${ids}-u`} value={unit} onChange={(x) => setUnit(x.target.value)}>
                    <option value={UNSET} disabled>choose…</option>
                    {units.map((u) => <option key={u} value={u}>{unitLabel(u)}</option>)}
                  </select>
                </label>
              </div>
              {typed.trim() !== "" && !Number.isFinite(number) && <p className="fs-12 m-0" role="status">Type a number, e.g. 0.42.</p>}
            </>
          ) : (
            <p className="muted fs-13 m-0">No automatic conversion, and no PK-Sim unit is harvested for this parameter: it
              cannot be accepted here. Correct it to the parameter it belongs to, or reject it.</p>
          )}
        </div>
      )}
      <div className="row gap-6 mt-6">
        <input placeholder="why" value={reason} onChange={(x) => setReason(x.target.value)} className="flex-1 minw-160"
               aria-label={`reason for ${e.id}`} ref={why} data-why={e.id} />
        <button className="btn primary" disabled={!reason.trim() || !valueReady} aria-label={`Accept ${e.target} = ${shown}`}
                onClick={() => void decide(body, accepted)}>Accept</button>
        <button className="btn" disabled={!reason.trim()} aria-label={`Reject ${e.target} = ${shown}`}
                onClick={() => void decide({ state: "REJECTED", reason }, `${e.id} rejected.`)}>Reject</button>
      </div>
      {problem && <InlineIssue severity="error" testId={`decide-problem-${e.id}`}>{problem}</InlineIssue>}
    </div>
  );
}

/** Where focus goes once this held value is decided and its row is gone: the next held value's "why" (never its Accept,
 *  so no value is accepted by pressing Enter again), else the one before, else the tab's heading. Read before the call,
 *  applied after the refresh has re-rendered the list (the 2026-11-11 audit 2, item 2). */
function afterThis(mine: HTMLInputElement | null): () => void {
  if (!mine) return () => undefined;
  const all = [...document.querySelectorAll<HTMLInputElement>("input[data-why]")];
  const at = all.indexOf(mine);
  const order = [...all.slice(at + 1), ...all.slice(0, Math.max(at, 0)).reverse()].map((x) => x.dataset.why!);
  const panel = mine.closest<HTMLElement>("[role=tabpanel]");
  return () => requestAnimationFrame(() => {
    const next = order.map((id) => document.querySelector<HTMLInputElement>(`input[data-why="${CSS.escape(id)}"]`)).find(Boolean);
    if (next) { next.focus(); return; }
    const heading = panel?.querySelector<HTMLElement>("h2, h3");
    if (heading) { heading.tabIndex = -1; heading.focus(); }
  });
}

// A study fact the model needs (D-29 demographics, a multiple-dose regimen), set on the study's dataset. The Studies tab
// of the Inputs page (R3b) replaces this with the full study form.
function StudyFix({ t, projectId, run }: { t: TodoItem; projectId: string; run: Run }) {
  const [doses, setDoses] = useState("");
  const [every, setEvery] = useState("");
  const path = "/api/v1/projects/{project_id}/datasets/{dataset_id}:study" as const;
  const params = { project_id: projectId, dataset_id: t.dataset_id ?? "" };
  return (
    <>
      <p className="muted m-2-0 fs-13">{t.message}</p>
      {t.dataset_id && t.kind === "demographics" && (
        <button className="btn" onClick={() => void run(() => send("post", path, params, { demographics_choice: "healthy_adult_default" }),
                                                        `${t.target}: the healthy adult default, listed as a limitation of the MAP.`)}>
          Use the healthy adult default
        </button>
      )}
      {t.dataset_id && t.kind === "regimen" && (
        <div className="row gap-6">
          <input placeholder="number of doses" value={doses} onChange={(x) => setDoses(x.target.value)} aria-label={`doses for ${t.target}`} />
          <input placeholder="interval (h)" value={every} onChange={(x) => setEvery(x.target.value)} aria-label={`interval for ${t.target}`} />
          <button className="btn primary" disabled={!(Number(doses) > 0 && Number(every) > 0)}
                  onClick={() => void run(() => send("post", path, params, { changes: { n_doses: Number(doses), dosing_interval_h: Number(every) } }),
                                          `${t.target}: ${doses} doses every ${every} h.`)}>Save</button>
        </div>
      )}
    </>
  );
}

function Datasets({ t }: { t: TodoItem }) {
  const rows = t.items as DatasetRow[];
  const meanless = rows.filter((d) => d.state !== "REJECTED" && !d.statistics.some((s) => s !== "individual"));
  return (
    <>
      {(t.warnings ?? []).length > 0 && (
        <ul className="flags" aria-label="dataset problems">
          {t.warnings!.map((w) => <li key={w}>{w}. Read the sheet again under the client&apos;s sheets below (the new reading replaces the old one).</li>)}
        </ul>
      )}
      {rows.length === 0 && <p className="muted m-0">No datasets yet: add data below (the client&apos;s sheets, a
        typed table or a digitized figure).</p>}
      {meanless.length > 0 && (
        <p className="muted fs-13 m-6-0">
          {meanless.map((d) => d.study_id).join(", ")}: individual subjects only. The campaign judges a mean profile, so these
          studies are kept for the population evaluation; for model building and validation you need studies with a mean profile
          (e.g. the published mean data of an IV or oral study).
        </p>
      )}
    </>
  );
}

/** What settles one open item, shown where the item is (its row or its tab): keep one of values in conflict, correct a
 *  misfiled value, call a pKa acidic or basic, check a held value, set a study's facts. Every change is recorded. */
export function TodoAction({ t, projectId, run }: { t: TodoItem; projectId: string; run: Run }) {
  return (
    <>
      {t.kind === "conflict" && <Conflict t={t} projectId={projectId} run={run} />}
      {(t.kind === "correct" || t.kind === "pka") && (
        <>
          <p className="muted m-2-0-4 fs-13">{t.message.replace(/^ev-[0-9a-f]+: /, "")}</p>
          {(t.items as Ev[]).map((e) => <Correction key={e.id} e={e} t={t} projectId={projectId} run={run} />)}
        </>
      )}
      {t.kind === "missing" && (
        <>
          {t.identity && (
            <div className="row gap-6 m-4-0">
              <span className="fs-13">The brief&apos;s PubChem record ({t.identity.name}, CID {t.identity.cid}) says
                <strong> {t.identity.value} g/mol</strong>. Check it is the free base, not the salt.</span>
              <button className="btn" onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/inputs:propose-identity", { project_id: projectId }),
                                                                "Molecular weight proposed from PubChem.")}>Propose it</button>
            </div>
          )}
          {(t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} card={t.target} />)}
        </>
      )}
      {t.kind === "review" && (
        <>
          {/* the message repeats the target and the value the row below shows: only said when there is no row */}
          {t.items.length === 0 && <p className="muted m-2-0-4 fs-13">{t.message.replace(/^ev-[0-9a-f]+: /, "")}</p>}
          {(t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} card={t.target} />)}
        </>
      )}
      {(t.kind === "regimen" || t.kind === "demographics") && <StudyFix t={t} projectId={projectId} run={run} />}
      {t.kind === "datasets" && <Datasets t={t} />}
      {t.kind === "formulation" && (
        <>
          <p className="muted m-2-0 fs-13">{t.message}. Propose the release model from the test
            product&apos;s dissolution profile (below), or give the formulation&apos;s values with their source.</p>
          {(t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} />)}
        </>
      )}
      {(t.kind === "process" || t.kind === "unit" || t.kind === "check") && (
        <p className="muted m-2-0 fs-13">{t.message}</p>
      )}
    </>
  );
}

/** One open item with its title, where it is settled. */
export function TodoCard({ t, projectId, run }: { t: TodoItem; projectId: string; run: Run }) {
  return (
    <div className="todo-item" data-testid={`todo-${t.kind}-${t.target}`} id={`todo-${t.kind}-${t.target}`}>
      <div className="spread">
        <strong>{TITLE[t.kind]}{t.kind !== "datasets" && t.kind !== "check" ? ` · ${readable(t.target)}` : ""}</strong>
        {/* the full id once, when the title does not already say it */}
        {(t.kind === "datasets" || t.kind === "check" || readable(t.target) !== t.target) && <code className="muted">{t.target}</code>}
      </div>
      <TodoAction t={t} projectId={projectId} run={run} />
    </div>
  );
}
