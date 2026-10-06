"use client";

import Link from "next/link";
import { useState } from "react";

import { apiSend } from "@/lib/writes";

export type Ev = {
  id: string; target: string; value: number | string | null; unit: string | null; value_pksim: number | null;
  unit_pksim: string | null; state: string; confidence: string; flags: string[]; provider: string; source_type: string;
  conditions: Record<string, string>; quote: string;
  source: { title: string; authors: string; year: number | null; doi: string | null; page: number | null; locator: string | null };
};
type DatasetRow = { id: string; study_id: string; purpose: string; origin: string; provider: string; state: string; kind: string;
                    statistics: string[]; series: number };
export type TodoItem = {
  kind: "conflict" | "correct" | "pka" | "missing" | "datasets" | "formulation" | "process" | "unit" | "check";
  target: string; message: string; items: (Ev | DatasetRow)[]; evidence?: string[];
  suggestions?: { targets: string[]; molecules: string[] };
  identity?: { value: number; unit: string; quote: string; cid: string; name: string } | null;
};
type Run = (fn: () => Promise<{ errors: { message: string }[] }>, ok: string) => Promise<string | null>;

const ORDER = ["conflict", "correct", "pka", "missing", "datasets", "formulation", "process", "unit", "check"];
const TITLE: Record<string, string> = {
  conflict: "Several accepted values: keep one", correct: "Filed under the wrong parameter", pka: "pKa: acidic or basic?",
  missing: "Missing for S0", datasets: "Observed data to judge the model on", formulation: "Formulation of the tablet studies",
  process: "Which PK-Sim process carries the pathway", unit: "Unit to convert", check: "Software build",
};
const LABEL: Record<string, string> = {
  "phys.mw": "Molecular weight", "phys.logp": "Lipophilicity", "bind.fu": "Fraction unbound in plasma",
  "phys.solubility.ref": "Reference solubility", "phys.pka": "pKa", elim: "An elimination pathway",
  "perm.intestinal": "Intestinal permeability", "elim.renal.gfr_fraction": "GFR fraction (renal filtration)",
  "elim.biliary.cl": "Biliary clearance", "dist.bp_ratio": "Blood-to-plasma ratio",
};

const fmt = (v: number | string | null) => (v === null ? "—" : typeof v === "number" ? +v.toPrecision(4) : v);

function Source({ e }: { e: Ev }) {
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

function Value({ e }: { e: Ev }) {
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
                onClick={() => void run(() => apiSend(`/api/v1/projects/${projectId}/evidence/${keep}:choose`, "POST", { reason }),
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
          </>
        )}
        <input placeholder="why" value={reason} onChange={(x) => setReason(x.target.value)} style={{ flex: 1, minWidth: 160 }}
               aria-label={`reason for ${e.id}`} />
        <button className="btn primary" disabled={!reason.trim() || (pka ? !kind : !target || (needsMolecule && !molecule))}
                onClick={() => void run(() => apiSend(`/api/v1/projects/${projectId}/evidence/${e.id}:correct`, "POST",
                                                      pka ? { conditions: { type: kind }, reason } : { target: concrete, reason }),
                                        pka ? `pKa ${fmt(e.value)} recorded as ${kind === "acid" ? "acidic" : "basic"}.`
                                            : `Filed as ${concrete}: check its value below and accept it.`)}>
          {pka ? "Save" : "Correct"}
        </button>
        <button className="btn" disabled={!reason.trim()}
                onClick={() => void run(() => apiSend(`/api/v1/projects/${projectId}/evidence/${e.id}:decide`, "POST", { state: "REJECTED", reason }),
                                        `${e.id} rejected.`)}>Reject</button>
      </div>
    </div>
  );
}

function Decide({ e, projectId, run }: { e: Ev; projectId: string; run: Run }) {
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
                onClick={() => void run(() => apiSend(`/api/v1/projects/${projectId}/evidence/${e.id}:decide`, "POST", { state: "ACCEPTED", reason }),
                                        `${e.target} = ${fmt(e.value_pksim ?? e.value)} accepted.`)}>Accept</button>
        <button className="btn" disabled={!reason.trim()}
                onClick={() => void run(() => apiSend(`/api/v1/projects/${projectId}/evidence/${e.id}:decide`, "POST", { state: "REJECTED", reason }),
                                        `${e.id} rejected.`)}>Reject</button>
      </div>
    </div>
  );
}

function Datasets({ t, projectId, run }: { t: TodoItem; projectId: string; run: Run }) {
  const [reason, setReason] = useState("");
  const rows = t.items as DatasetRow[];
  const proposed = rows.filter((d) => d.state === "PROPOSED");
  const meanless = rows.filter((d) => d.state !== "REJECTED" && !d.statistics.some((s) => s !== "individual"));
  return (
    <>
      {rows.length === 0 ? <p className="muted" style={{ margin: 0 }}>No datasets yet: read the client&apos;s sheets on the Client data page, or add published data on the Literature page.</p> : (
        <table className="todo-table">
          <thead><tr><th>Study</th><th>For</th><th>Data</th><th>State</th></tr></thead>
          <tbody>{rows.map((d) => (
            <tr key={d.id} data-testid={`todo-dataset-${d.study_id}`}>
              <td><strong>{d.study_id}</strong><div className="muted" style={{ fontSize: 12 }}>{d.origin.toLowerCase()} · {d.id}</div></td>
              <td>{d.purpose.replace(/_/g, " ")}</td>
              <td>{d.series} series · {d.statistics.join(", ").replace(/_/g, " ")}</td>
              <td><span className={`chip ${d.state === "ACCEPTED" ? "low" : "medium"}`}>{d.state.toLowerCase()}</span></td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {meanless.length > 0 && (
        <p className="muted" style={{ fontSize: 13, margin: "6px 0" }}>
          {meanless.map((d) => d.study_id).join(", ")}: individual subjects only. The campaign judges a mean profile, so these
          studies are kept for the population evaluation; for model building and validation you need studies with a mean profile
          (e.g. the published mean data of an IV or oral study).
        </p>
      )}
      {proposed.length > 0 && (
        <div className="row" style={{ gap: 6 }}>
          <input placeholder="why (e.g. checked against the client's report)" value={reason} onChange={(e) => setReason(e.target.value)}
                 style={{ flex: 1, minWidth: 220 }} aria-label="reason for the datasets" />
          <button className="btn primary" disabled={!reason.trim()} onClick={async () => {
            for (const d of proposed) {
              const err = await run(() => apiSend(`/api/v1/projects/${projectId}/datasets/${d.id}:decide`, "POST", { state: "ACCEPTED", reason }), "");
              if (err) return;
            }
          }}>Accept the {proposed.length} proposed dataset{proposed.length === 1 ? "" : "s"}</button>
        </div>
      )}
    </>
  );
}

/** What stands between the inputs and readiness, each with what settles it, in the order to do them. */
export function InputsTodo({ projectId, todo, run }: { projectId: string; todo: TodoItem[]; run: Run }) {
  const [researching, setResearching] = useState<string | null>(null);
  if (todo.length === 0) return null;
  const sorted = [...todo].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
  return (
    <section className="card todo" aria-label="What stops readiness" data-testid="inputs-todo">
      <div className="spread">
        <h2 style={{ margin: 0 }}>What stops readiness ({todo.length})</h2>
        <button className="btn" onClick={async () => setResearching(await run(() => apiSend(`/api/v1/projects/${projectId}/evidence:research`, "POST"),
                                                                              "The literature agent (A2) is searching; its proposals appear here and on the Literature page.") ?? "started")}>
          Ask the literature agent for what is missing
        </button>
      </div>
      <p className="muted" style={{ margin: "4px 0 10px", fontSize: 13 }}>
        Each decision is yours and is recorded with its reason; the inputs are re-assembled after each one. Values are never averaged or
        chosen by code.
      </p>
      {researching && researching !== "started" && <div className="banner err">{researching}</div>}
      {sorted.map((t, i) => (
        <div key={`${t.kind}-${t.target}-${i}`} className="todo-item" data-testid={`todo-${t.kind}-${t.target}`}>
          <div className="spread">
            <strong>{TITLE[t.kind]}{t.kind !== "datasets" && t.kind !== "check" ? ` · ${LABEL[t.target] ?? t.target}` : ""}</strong>
            <code className="muted">{t.target}</code>
          </div>
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
                  <button className="btn" onClick={() => void run(() => apiSend(`/api/v1/projects/${projectId}/inputs:propose-identity`, "POST"),
                                                                    "Molecular weight proposed from PubChem: accept it below.")}>Propose it</button>
                </div>
              )}
              {(t.items as Ev[]).length > 0
                ? (t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} />)
                : !t.identity && <p className="muted" style={{ margin: "2px 0", fontSize: 13 }}>
                    No proposal yet: ask the literature agent (button above), or add the value with its source on the{" "}
                    <Link href={`/projects/${projectId}/evidence`}>Literature page</Link>.</p>}
            </>
          )}
          {t.kind === "datasets" && <Datasets t={t} projectId={projectId} run={run} />}
          {t.kind === "formulation" && (
            <>
              <p className="muted" style={{ margin: "2px 0", fontSize: 13 }}>{t.message}. Propose the release model from the test product&apos;s
                dissolution profile on the <Link href={`/projects/${projectId}/client-data`}>Client data page</Link>, then accept it here.</p>
              {(t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} />)}
            </>
          )}
          {(t.kind === "process" || t.kind === "unit" || t.kind === "check") && (
            <p className="muted" style={{ margin: "2px 0", fontSize: 13 }}>{t.message}{t.kind === "process" ? " — choose it on the Compound tab." : ""}</p>
          )}
        </div>
      ))}
    </section>
  );
}
