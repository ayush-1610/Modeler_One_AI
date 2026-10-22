"use client";

import { useState } from "react";

import { send, type Envelope } from "@/lib/api";

export type Ev = {
  id: string; target: string; value: number | string | null; unit: string | null; value_pksim: number | null;
  unit_pksim: string | null; state: string; confidence: string; flags: string[]; provider: string; source_type: string;
  conditions: Record<string, string>; quote: string;
  source: { title: string; authors: string; year: number | null; doi: string | null; page: number | null; locator: string | null };
};
type DatasetRow = { id: string; study_id: string; purpose: string; origin: string; provider: string; state: string; kind: string;
                    statistics: string[]; series: number };
export type TodoItem = {
  kind: "conflict" | "correct" | "pka" | "missing" | "datasets" | "formulation" | "process" | "unit" | "check" | "review"
    | "regimen" | "demographics";
  target: string; message: string; items: (Ev | DatasetRow)[]; evidence?: string[];
  suggestions?: { targets: string[]; molecules: string[] };
  identity?: { value: number; unit: string; quote: string; cid: string; name: string } | null;
  warnings?: string[];
  dataset_id?: string | null;
  tab?: string;
};
export type Run = <T>(fn: () => Promise<Envelope<T>>, ok: string) => Promise<string | null>;

export const ORDER = ["conflict", "correct", "pka", "missing", "review", "regimen", "demographics", "datasets", "formulation", "process",
               "unit", "check"];
export const TITLE: Record<string, string> = {
  conflict: "Values more than 2-fold apart: keep one", correct: "Filed under the wrong parameter", pka: "pKa: acidic or basic?",
  missing: "Missing for S0", datasets: "Observed data to judge the model on", formulation: "Formulation of the tablet studies",
  process: "Which PK-Sim process carries the pathway", unit: "Unit to convert", check: "Software build",
  review: "Held until you check it", regimen: "Multiple-dose regimen", demographics: "Demographics (D-29)",
};
export const LABEL: Record<string, string> = {
  "phys.mw": "Molecular weight", "phys.logp": "Lipophilicity", "bind.fu": "Fraction unbound in plasma",
  "phys.solubility.ref": "Reference solubility", "phys.pka": "pKa", elim: "An elimination pathway",
  "perm.intestinal": "Intestinal permeability", "elim.renal.gfr_fraction": "GFR fraction (renal filtration)",
  "elim.biliary.cl": "Biliary clearance", "dist.bp_ratio": "Blood-to-plasma ratio",
  "elim.fe_urine": "Fraction excreted unchanged in urine (fe)", "elim.fm.<enzyme>": "Fraction metabolised by an enzyme (fm)",
};

export const fmt = (v: number | string | null) => (v === null ? "—" : typeof v === "number" ? +v.toPrecision(4) : v);

export function Source({ e }: { e: Ev }) {
  const s = e.source;
  const who = [s.authors, s.year].filter(Boolean).join(" ");
  return (
    <div style={{ fontSize: 12 }}>
      <div>{s.title || e.source_type.toLowerCase()}{who ? ` · ${who}` : ""}{s.page ? ` · p.${s.page}` : ""}{s.locator ? ` · ${s.locator}` : ""}</div>
      <div className="muted">{e.provider.toLowerCase()} · {e.source_type.toLowerCase().replace(/_/g, " ")} · grade {e.confidence}
        {Object.keys(e.conditions).length > 0 && ` · ${Object.entries(e.conditions).map(([k, v]) => `${k} ${v}`).join(", ")}`}</div>
      {e.quote && <div className="quote">“{e.quote}”</div>}
      {e.flags.length > 0 && <ul className="flags">{e.flags.map((f) => <li key={f}>{f}</li>)}</ul>}
    </div>
  );
}

export function Value({ e }: { e: Ev }) {
  return (
    <span>
      <strong>{fmt(e.value)}</strong> {e.unit ?? ""}
      {e.value_pksim !== null && (e.value_pksim !== e.value || (e.unit_pksim ?? null) !== (e.unit ?? null)) &&
        <div className="muted" style={{ fontSize: 12 }}>PK-Sim: {fmt(e.value_pksim)} {e.unit_pksim ?? ""}</div>}
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
      <div className="row" style={{ gap: 6 }}>
        <input placeholder="why this value (kept in the audit trail)" value={reason} onChange={(e) => setReason(e.target.value)}
               style={{ flex: 1, minWidth: 220 }} aria-label={`reason for ${t.target}`} />
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
      <div className="row" style={{ alignItems: "flex-start", gap: 14 }}>
        <div style={{ minWidth: 110 }}><code>{e.target}</code><div><Value e={e} /></div></div>
        <div style={{ flex: 1, minWidth: 220 }}><Source e={e} /></div>
      </div>
      <div className="row" style={{ gap: 6, marginTop: 6 }}>
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
              <input type="number" step="any" placeholder="number in the quote" value={number} onChange={(x) => setNumber(x.target.value)}
                     style={{ width: 150 }} aria-label={`number for ${e.id}`} />
              <input placeholder="unit" value={unit} onChange={(x) => setUnit(x.target.value)} style={{ width: 80 }} aria-label={`unit for ${e.id}`} />
            </>}
          </>
        )}
        <input placeholder="why" value={reason} onChange={(x) => setReason(x.target.value)} style={{ flex: 1, minWidth: 160 }}
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

export function Decide({ e, projectId, run }: { e: Ev; projectId: string; run: Run }) {
  const [reason, setReason] = useState("");
  return (
    <div className="todo-row">
      <div className="row" style={{ alignItems: "flex-start", gap: 14 }}>
        <div style={{ minWidth: 110 }}><code>{e.target}</code><div><Value e={e} /></div></div>
        <div style={{ flex: 1, minWidth: 220 }}><Source e={e} /></div>
      </div>
      <div className="row" style={{ gap: 6, marginTop: 6 }}>
        <input placeholder="why" value={reason} onChange={(x) => setReason(x.target.value)} style={{ flex: 1, minWidth: 160 }}
               aria-label={`reason for ${e.id}`} />
        <button className="btn primary" disabled={!reason.trim() || (typeof e.value === "number" && e.value_pksim === null)}
                title={typeof e.value === "number" && e.value_pksim === null ? "no automatic conversion: accept it on the Literature page with its PK-Sim value" : undefined}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:decide", { project_id: projectId, evidence_id: e.id }, { state: "ACCEPTED", reason }),
                                        `${e.target} = ${fmt(e.value_pksim ?? e.value)} accepted.`)}>Accept</button>
        <button className="btn" disabled={!reason.trim()}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:decide", { project_id: projectId, evidence_id: e.id }, { state: "REJECTED", reason }),
                                        `${e.id} rejected.`)}>Reject</button>
      </div>
    </div>
  );
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
      <p className="muted" style={{ margin: "2px 0", fontSize: 13 }}>{t.message}</p>
      {t.dataset_id && t.kind === "demographics" && (
        <button className="btn" onClick={() => void run(() => send("post", path, params, { demographics_choice: "healthy_adult_default" }),
                                                        `${t.target}: the healthy adult default, listed as a limitation of the MAP.`)}>
          Use the healthy adult default
        </button>
      )}
      {t.dataset_id && t.kind === "regimen" && (
        <div className="row" style={{ gap: 6 }}>
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
      {rows.length === 0 && <p className="muted" style={{ margin: 0 }}>No datasets yet: add data below (the client&apos;s sheets, a
        typed table or a digitized figure).</p>}
      {meanless.length > 0 && (
        <p className="muted" style={{ fontSize: 13, margin: "6px 0" }}>
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
          <p className="muted" style={{ margin: "2px 0 4px", fontSize: 13 }}>{t.message.replace(/^ev-[0-9a-f]+: /, "")}</p>
          {(t.items as Ev[]).map((e) => <Correction key={e.id} e={e} t={t} projectId={projectId} run={run} />)}
        </>
      )}
      {t.kind === "missing" && (
        <>
          {t.identity && (
            <div className="row" style={{ gap: 6, margin: "4px 0" }}>
              <span style={{ fontSize: 13 }}>The brief&apos;s PubChem record ({t.identity.name}, CID {t.identity.cid}) says
                <strong> {t.identity.value} g/mol</strong>. Check it is the free base, not the salt.</span>
              <button className="btn" onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/inputs:propose-identity", { project_id: projectId }),
                                                                "Molecular weight proposed from PubChem.")}>Propose it</button>
            </div>
          )}
          {(t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} />)}
        </>
      )}
      {t.kind === "review" && (
        <>
          <p className="muted" style={{ margin: "2px 0 4px", fontSize: 13 }}>{t.message.replace(/^ev-[0-9a-f]+: /, "")}</p>
          {(t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} />)}
        </>
      )}
      {(t.kind === "regimen" || t.kind === "demographics") && <StudyFix t={t} projectId={projectId} run={run} />}
      {t.kind === "datasets" && <Datasets t={t} />}
      {t.kind === "formulation" && (
        <>
          <p className="muted" style={{ margin: "2px 0", fontSize: 13 }}>{t.message}. Propose the release model from the test
            product&apos;s dissolution profile (below), or give the formulation&apos;s values with their source.</p>
          {(t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} />)}
        </>
      )}
      {(t.kind === "process" || t.kind === "unit" || t.kind === "check") && (
        <p className="muted" style={{ margin: "2px 0", fontSize: 13 }}>{t.message}</p>
      )}
    </>
  );
}

/** One open item with its title, where it is settled. */
export function TodoCard({ t, projectId, run }: { t: TodoItem; projectId: string; run: Run }) {
  return (
    <div className="todo-item" data-testid={`todo-${t.kind}-${t.target}`} id={`todo-${t.kind}-${t.target}`}>
      <div className="spread">
        <strong>{TITLE[t.kind]}{t.kind !== "datasets" && t.kind !== "check" ? ` · ${LABEL[t.target] ?? t.target}` : ""}</strong>
        <code className="muted">{t.target}</code>
      </div>
      <TodoAction t={t} projectId={projectId} run={run} />
    </div>
  );
}
