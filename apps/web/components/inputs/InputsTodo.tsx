"use client";

import { useState } from "react";

import { send, type Envelope } from "@/lib/api";
import type { After } from "@/lib/hooks";
import { ASK_FORMULATION, flagLines, formulationParts, formulationProblem, PARAM_LABEL, paramLabel, todoLabel, todoMessage, unitText } from "@/lib/words";

import { MODEL, chooseAfter, correctAfter, evidenceAfter, identityAfter } from "./after";

export type Ev = {
  id: string; target: string; value: number | string | null; unit: string | null; value_pksim: number | null;
  unit_pksim: string | null; state: string; confidence: string; flags: string[]; provider: string; source_type: string;
  conditions: Record<string, string>; quote: string;
  source: { title: string; authors: string; year: number | null; doi: string | null; page: number | null; locator: string | null;
            doc_sha256?: string | null; url?: string | null; pmid?: string | null };
  /** the unit PK-Sim holds a value of its target in ("" none); null: not named (a placeholder, filed under a pathway first) */
  pksim_unit?: string | null;
};
/** An elimination pathway the data plan's "elim" is filed under (`inputs.elimination_pathways`): its unit and the
 *  harvested PK-Sim process and parameter that take it. */
export type Pathway = { id: string; unit: string | null; process: string; parameter: string };
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
  /** an item about the data plan's "elim": the pathways a value for it is filed under (OWN-5) */
  pathways?: Pathway[];
  /** the formulation item's problems one by one (the readiness check's own list; its message joins them with "; ") */
  details?: string[];
};
/** A change made on the page: its call, what is said when it succeeds, and what it made stale (`components/inputs/after.ts`). */
export type Run = <T>(fn: () => Promise<Envelope<T>>, ok: string, after: After<T>) => Promise<string | null>;

/** A model input's name in words, by its CPF id (one list of names: lib/words.ts). */
export const LABEL: Record<string, string> = PARAM_LABEL;

export const fmt = (v: number | string | null) => (v === null ? "—" : typeof v === "number" ? +v.toPrecision(4) : v);

export function Source({ e }: { e: Ev }) {
  const s = e.source;
  const who = [s.authors, s.year].filter(Boolean).join(" ");
  return (
    <div className="fs-12">
      <div>{s.title || e.source_type.toLowerCase()}{who ? ` · ${who}` : ""}{s.page ? ` · p.${s.page}` : ""}{s.locator ? ` · ${s.locator}` : ""}</div>
      <div className="muted">{e.provider.toLowerCase()} · {e.source_type.toLowerCase().replace(/_/g, " ")} · grade {e.confidence}
        {Object.keys(e.conditions).length > 0 && ` · ${Object.entries(e.conditions).map(([k, v]) => `${k} ${v}`).join(", ")}`}</div>
      {e.quote && <div className="quote">“{e.quote}”</div>}
      {/* why it waits, in words (final review OWN-5): no engine codes, a condition list as its template writes it */}
      {e.flags.length > 0 && <ul className="flags">{flagLines(e.flags).map((f) => <li key={f}>{f}</li>)}</ul>}
    </div>
  );
}

export function Value({ e }: { e: Ev }) {
  return (
    <span>
      <strong>{fmt(e.value)}</strong> {unitText(e.unit)}
      {e.value_pksim !== null && (e.value_pksim !== e.value || (e.unit_pksim ?? null) !== (e.unit ?? null)) &&
        <div className="muted fs-12">PK-Sim: {fmt(e.value_pksim)} {unitText(e.unit_pksim)}</div>}
    </span>
  );
}

/** The pathway a value for the data plan's "elim" is filed under (OWN-5): chosen first, each pathway by its name and the
 *  unit its value is stored in. */
export function PathwayPick({ pathways, value, onChange, label, testId, invalid = false }: {
  pathways: Pathway[]; value: string; onChange: (id: string) => void; label: string; testId?: string;
  /** the pathway is what a press found missing (its message says so) */
  invalid?: boolean;
}) {
  return (
    <select value={value} onChange={(x) => onChange(x.target.value)} aria-label={label} data-testid={testId} aria-invalid={invalid || undefined}>
      <option value="">choose the pathway…</option>
      {pathways.map((p) => <option key={p.id} value={p.id}>{paramLabel(p.id)}{p.unit ? ` (${p.unit})` : " (no unit)"}</option>)}
    </select>
  );
}

/** A value filed under the data plan's "elim" (OWN-5): it cannot be used or accepted until it is filed under a pathway,
 *  said on the row; the pathway is chosen here and the value is filed under it (`:correct`: a corrected copy, held until
 *  a person checks its converted value). */
function FileUnderPathway({ e, pathways, projectId, run }: { e: Ev; pathways: Pathway[]; projectId: string; run: Run }) {
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  return (
    <div className="mt-6" data-testid={`file-pathway-${e.id}`}>
      <p className="fs-13 m-0" data-testid={`decide-refused-${e.id}`}>It cannot be accepted as it is: a value counts only under
        the elimination pathway it belongs to. Choose the pathway, then check its value there.</p>
      <div className="row gap-6 mt-4">
        <PathwayPick pathways={pathways} value={target} onChange={setTarget} label={`pathway for ${e.id}`} testId={`pathway-${e.id}`} />
        <input placeholder="why" value={reason} onChange={(x) => setReason(x.target.value)} className="flex-1 minw-160"
               aria-label={`reason to file ${e.id} under the pathway`} />
        <button className="btn primary" disabled={!target || !reason.trim()}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:correct",
                                                   { project_id: projectId, evidence_id: e.id }, { target, reason }),
                                        `Filed under ${paramLabel(target).toLowerCase()}: check its value and accept it.`, correctAfter(projectId, true))}>
          File it under this pathway</button>
      </div>
    </div>
  );
}

function Conflict({ t, projectId, run }: { t: TodoItem; projectId: string; run: Run }) {
  const [keep, setKeep] = useState("");
  const [reason, setReason] = useState("");
  const items = t.items as Ev[];
  return (
    <>
      <div className="table-scroll">
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
      </div>
      <div className="row gap-6">
        <input placeholder="why this value (kept in the audit trail)" value={reason} onChange={(e) => setReason(e.target.value)} className="flex-1 minw-220" aria-label={`reason for ${t.target}`} />
        <button className="btn primary" disabled={!keep || !reason.trim()}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:choose", { project_id: projectId, evidence_id: keep }, { reason }),
                                        `${paramLabel(t.target)}: one value kept, the others rejected with your reason.`, chooseAfter(projectId))}>
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
        <div className="minw-110"><span className="fs-13">{paramLabel(e.target)}</span><div><Value e={e} /></div></div>
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
              {(t.suggestions?.targets ?? []).map((s) => <option key={s} value={s}>{paramLabel(s)}</option>)}
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
              {/* said in text, not only in a hover (final review OWN-16) */}
              <span className="muted fs-12" id={`statement-${e.id}`}>A sentence becomes a value only as a number its quote states: type that number.</span>
            </>}
          </>
        )}
        <input placeholder="why" value={reason} onChange={(x) => setReason(x.target.value)} className="flex-1 minw-160"
               aria-label={`reason for ${e.id}`} />
        <button className="btn primary" disabled={!reason.trim() || (pka ? !kind : !target || (needsMolecule && !molecule) || (statement && !number))}
                aria-describedby={statement ? `statement-${e.id}` : undefined}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:correct",
                                                      { project_id: projectId, evidence_id: e.id },
                                                      pka ? { conditions: { type: kind }, reason }
                                                          : { target: concrete, reason, ...(statement ? { value: Number(number), unit: unit || null } : {}) }),
                                        pka ? `pKa ${fmt(e.value)} recorded as ${kind === "acid" ? "acidic" : "basic"}.`
                                            : `Filed as ${paramLabel(concrete)}: check its value below and accept it.`, correctAfter(projectId, !pka))}>
          {pka ? "Save" : "Correct"}
        </button>
        <button className="btn" disabled={!reason.trim()}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:decide", { project_id: projectId, evidence_id: e.id }, { state: "REJECTED", reason }),
                                        `${paramLabel(e.target)} ${fmt(e.value)}: rejected.`, evidenceAfter(projectId))}>Reject</button>
      </div>
    </div>
  );
}

/** A value to accept or reject. One whose unit was not converted to PK-Sim's is accepted with its value typed in PK-Sim's
 *  unit, which the API names (`pksim_unit`), in place of the dead "accept it on the Literature page" (final review OWN-5);
 *  one filed under the data plan's "elim" is filed under its pathway first (`pathways`), and is never accepted as it is;
 *  one filed under a kind of parameter (an enzyme's clearance with no enzyme named) or a name PK-Sim does not take is
 *  filed under the parameter it is first, where its item names them (`todo.suggestions`). Where none of these can be
 *  done, the row says why Accept is not offered and what can be done instead. */
export function Decide({ e, projectId, run, pathways, todo }: {
  e: Ev; projectId: string; run: Run; pathways?: Pathway[];
  /** the item the value waits under: its suggested parameters, to file a value PK-Sim cannot take as it is */
  todo?: TodoItem;
}) {
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const name = paramLabel(e.target);
  const unconverted = typeof e.value === "number" && e.value_pksim === null;
  // a number whose parameter PK-Sim names no unit for (the data plan's "elim", a kind of parameter, a name the model does
  // not take): it cannot be checked in PK-Sim's unit, so it is never accepted as it is
  const unplaced = unconverted && e.pksim_unit === null;
  const placeholder = e.pksim_unit === null && Boolean(pathways?.length);
  const byHand = unconverted && typeof e.pksim_unit === "string";
  const handValue = typed.trim() !== "" && !Number.isNaN(Number(typed)) ? Number(typed) : null;
  const unitWord = e.pksim_unit ? e.pksim_unit : "PK-Sim's terms (no unit)";
  if (!placeholder && unplaced && todo?.suggestions?.targets.length) {
    return (
      <div data-testid={`decide-${e.id}`}>
        <p className="fs-13 m-6-0-0" data-testid={`decide-refused-${e.id}`}>It cannot be accepted as it is: it is filed under
          {" "}{name.toLowerCase()}, which is not one parameter PK-Sim takes. Choose the parameter it is (with its enzyme, where it
          names one), then check its value.</p>
        <Correction e={e} t={todo} projectId={projectId} run={run} />
      </div>
    );
  }
  return (
    <div className="todo-row" data-testid={`decide-${e.id}`}>
      <div className="row items-start gap-14">
        <div className="minw-110"><span className="fs-13">{name}</span><div><Value e={e} /></div></div>
        <div className="flex-1 minw-220"><Source e={e} /></div>
      </div>
      {placeholder ? <FileUnderPathway e={e} pathways={pathways!} projectId={projectId} run={run} /> : (
        <>
          {byHand && (
            <p className="fs-13 m-6-0-0" data-testid={`decide-by-hand-${e.id}`}>{fmt(e.value)} {unitText(e.unit)} is not converted
              automatically: type its value in {unitWord} to accept it.</p>
          )}
          {unplaced && (
            <p className="fs-13 m-6-0-0" data-testid={`decide-refused-${e.id}`}>It cannot be accepted: no unit is known in which
              PK-Sim takes {name.toLowerCase()}, so its value cannot be checked. Reject it, and add the value again under the parameter
              it is, on its row on <a href="?tab=compound" data-testid={`decide-refused-go-${e.id}`}>Compound</a>.</p>
          )}
          <div className="row gap-6 mt-6">
            {byHand && (
              <label className="add-field">Value in {unitWord}
                <input value={typed} onChange={(x) => setTyped(x.target.value)} className="w-110" inputMode="decimal"
                       aria-label={`value of ${name} in ${unitWord}`} data-testid={`decide-pksim-${e.id}`} /></label>
            )}
            <input placeholder="why" value={reason} onChange={(x) => setReason(x.target.value)} className="flex-1 minw-160"
                   aria-label={`reason for ${e.id}`} />
            {!unplaced && (!unconverted || byHand) && (
              <button className="btn primary" disabled={!reason.trim() || (byHand && handValue === null)}
                      onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:decide",
                                                         { project_id: projectId, evidence_id: e.id },
                                                         { state: "ACCEPTED", reason,
                                                           ...(byHand ? { value_pksim: handValue, unit_pksim: e.pksim_unit || null } : {}) }),
                                              `${name} = ${fmt(byHand ? handValue : e.value_pksim ?? e.value)}${byHand && e.pksim_unit ? ` ${e.pksim_unit}` : ""} accepted.`, evidenceAfter(projectId))}>
                Accept</button>
            )}
            <button className="btn" disabled={!reason.trim()}
                    onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:decide", { project_id: projectId, evidence_id: e.id }, { state: "REJECTED", reason }),
                                            `${name} ${fmt(e.value)}: rejected.`, evidenceAfter(projectId))}>Reject</button>
          </div>
        </>
      )}
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
      <p className="muted m-2-0 fs-13">{t.message}</p>
      {t.dataset_id && t.kind === "demographics" && (
        <button className="btn" onClick={() => void run(() => send("post", path, params, { demographics_choice: "healthy_adult_default" }),
                                                        `${t.target}: the healthy adult default, listed as a limitation of the MAP.`, MODEL)}>
          Use the healthy adult default
        </button>
      )}
      {t.dataset_id && t.kind === "regimen" && (
        <div className="row gap-6">
          <input placeholder="number of doses" value={doses} onChange={(x) => setDoses(x.target.value)} aria-label={`doses for ${t.target}`} />
          <input placeholder="interval (h)" value={every} onChange={(x) => setEvery(x.target.value)} aria-label={`interval for ${t.target}`} />
          <button className="btn primary" disabled={!(Number(doses) > 0 && Number(every) > 0)}
                  onClick={() => void run(() => send("post", path, params, { changes: { n_doses: Number(doses), dosing_interval_h: Number(every) } }),
                                          `${t.target}: ${doses} doses every ${every} h.`, MODEL)}>Save</button>
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
          <p className="muted m-2-0-4 fs-13">{todoMessage(t.kind, t.message)}</p>
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
                                                                "Molecular weight proposed from PubChem.", identityAfter(projectId))}>Propose it</button>
            </div>
          )}
          {(t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} pathways={t.pathways} todo={t} />)}
        </>
      )}
      {t.kind === "review" && (
        <>
          <p className="muted m-2-0-4 fs-13">{todoMessage(t.kind, t.message)}</p>
          {(t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} pathways={t.pathways} todo={t} />)}
        </>
      )}
      {(t.kind === "regimen" || t.kind === "demographics") && <StudyFix t={t} projectId={projectId} run={run} />}
      {t.kind === "datasets" && <Datasets t={t} />}
      {t.kind === "formulation" && (
        <>
          <ul className="m-2-0 fs-13" data-testid="formulation-problems">
            {formulationParts(t).map((m) => <li key={m}>{formulationProblem(m)}</li>)}
          </ul>
          {/* the ways forward, each a link (round 3, owner-job gap 11): with no product here, adding one is the lever */}
          <p className="muted m-2-0 fs-13" data-testid="formulation-how">A formulation&apos;s release comes from a product&apos;s dissolution
            profile: &ldquo;Use this profile as the release&rdquo; on the product&apos;s card, on <a href="?tab=formulations">Products and
            dissolution</a>. With no product there, <a href={"?tab=formulations&add=product"} data-testid="formulation-add-product">add
            the product the study used</a> (&ldquo;Add a product&rdquo;) and its dissolution file (Add data), or <a href={`?tab=todo&at=${ASK_FORMULATION}`}
            data-testid="formulation-ask">ask the client for it</a> (To do, &ldquo;Ask the client&rdquo;). A study wrongly read as a tablet or
            capsule is corrected on its card on <a href="?tab=studies">Clinical studies</a>.</p>
          {(t.items as Ev[]).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} />)}
        </>
      )}
      {(t.kind === "process" || t.kind === "unit" || t.kind === "check") && (
        <p className="muted m-2-0 fs-13">{todoMessage(t.kind, t.message)}</p>
      )}
    </>
  );
}

/** One open item with its title, where it is settled. */
export function TodoCard({ t, projectId, run }: { t: TodoItem; projectId: string; run: Run }) {
  return (
    <div className="todo-item" data-testid={`todo-${t.kind}-${t.target}`} id={`todo-${t.kind}-${t.target}`}>
      {/* named in words only (final review OWN-8): "The formulation of the tablet studies", never "form.*" */}
      <strong>{todoLabel(t.kind, t.target)}</strong>
      <TodoAction t={t} projectId={projectId} run={run} />
    </div>
  );
}
