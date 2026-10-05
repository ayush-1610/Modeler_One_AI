"use client";

import { useState } from "react";

import { ROLE_LABEL, type ParamNode, type PlanView } from "@/lib/plan";

// D1 · disposition and D2 · absorption and formulation (plan §11.2, §11.3): read-mostly in this release (D-13). The
// one edit on a parameter node is its fit: free it in an S1–S3 stage within bounds, with the reason (userLocked).

type FitSave = (parameter: string, fit: { stages: string[]; lower: number; upper: number; scale: "linear" | "log"; reason: string }) => Promise<string | null>;
type FitRemove = (parameter: string, reason: string) => Promise<string | null>;

function FitForm({ p, onSave, onRemove }: { p: ParamNode; onSave: FitSave; onRemove: FitRemove }) {
  const numeric = typeof p.value === "number";
  const [open, setOpen] = useState(false);
  const [stages, setStages] = useState<string[]>(p.fit?.stages ?? p.candidate_at.slice(0, 1));
  const [lower, setLower] = useState(String(p.fit?.lower ?? (numeric ? +((p.value as number) / 10).toPrecision(3) : "")));
  const [upper, setUpper] = useState(String(p.fit?.upper ?? (numeric ? +((p.value as number) * 10).toPrecision(3) : "")));
  const [scale, setScale] = useState<"linear" | "log">(p.fit?.scale ?? "log");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  if (!numeric) return null;
  if (!open) {
    return <button className="btn tiny" onClick={() => setOpen(true)} data-testid={`fit-${p.id}`}>{p.fit ? "change fit" : "fit…"}</button>;
  }
  return (
    <div className="fit-form" data-testid={`fit-form-${p.id}`}>
      <div className="row" style={{ gap: 6 }}>
        {["S1", "S2", "S3"].map((st) => (
          <label key={st} style={{ fontSize: 12 }}>
            <input type="checkbox" checked={stages.includes(st)}
                   onChange={(e) => setStages(e.target.checked ? [...stages, st] : stages.filter((x) => x !== st))} /> {st}
            {p.candidate_at.includes(st) ? "" : "*"}
          </label>
        ))}
        <select value={scale} onChange={(e) => setScale(e.target.value as "linear" | "log")} aria-label="scale">
          <option value="log">log</option><option value="linear">linear</option>
        </select>
      </div>
      <div className="row" style={{ gap: 4 }}>
        <input value={lower} onChange={(e) => setLower(e.target.value)} placeholder="lower" style={{ width: 80 }} aria-label="lower bound" />
        <input value={upper} onChange={(e) => setUpper(e.target.value)} placeholder="upper" style={{ width: 80 }} aria-label="upper bound" />
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="why (required)" style={{ flex: 1 }} />
      </div>
      <div className="row" style={{ gap: 4 }}>
        <button className="btn tiny primary" disabled={!reason.trim() || !stages.length}
                onClick={async () => setError(await onSave(p.id, { stages, lower: Number(lower), upper: Number(upper), scale, reason }))}>Save</button>
        {p.fit && <button className="btn tiny" disabled={!reason.trim()} onClick={async () => setError(await onRemove(p.id, reason))}>Fix again</button>}
        <button className="btn tiny" onClick={() => setOpen(false)}>Close</button>
      </div>
      <p className="muted" style={{ fontSize: 11, margin: 0 }}>* not an MS-01 candidate at that stage (the validator warns)</p>
      {error && <div className="banner err">{error}</div>}
    </div>
  );
}

function Param({ p, onSave, onRemove }: { p: ParamNode; onSave: FitSave; onRemove: FitRemove }) {
  const value = typeof p.value === "number" ? +p.value.toPrecision(4) : String(p.value ?? "—");
  return (
    <div className={`param-node ${p.fit ? "fitted" : ""}`} title={p.source ?? ""} data-testid={`param-${p.id}`}>
      <div className="spread"><code>{p.id}</code><span className="chip neutral">{p.status.toLowerCase()}</span></div>
      <div>{value} {p.unit ?? ""}</div>
      <div className="muted" style={{ fontSize: 12 }}>
        {p.fit ? `fitted in ${p.fit.stages.join(", ")} [${p.fit.lower}, ${p.fit.upper}] ${p.fit.scale}`
          : p.candidate_at.length ? `MS-01 candidate at ${p.candidate_at.join(", ")}` : "fixed"}
      </div>
      <FitForm p={p} onSave={onSave} onRemove={onRemove} />
    </div>
  );
}

export function D1Disposition({ view, onFit, onUnfit }: { view: PlanView; onFit: FitSave; onUnfit: FitRemove }) {
  const d = view.d1;
  return (
    <div className="flow" data-testid="d1">
      <div className="flow-col"><h4>Plasma</h4><div className="param-node muted">systemic circulation<br />informed by {d.informed_by.join(", ") || "no IV study (S1 skipped)"}</div></div>
      <div className="flow-arrow">→</div>
      <div className="flow-col"><h4>Binding</h4>{d.binding.map((p) => <Param key={p.id} p={p} onSave={onFit} onRemove={onUnfit} />)}</div>
      <div className="flow-arrow">→</div>
      <div className="flow-col"><h4>Distribution</h4>
        {d.distribution.length ? d.distribution.map((p) => <Param key={p.id} p={p} onSave={onFit} onRemove={onUnfit} />)
          : <div className="param-node muted">PK-Sim standard partition and permeability methods</div>}</div>
      <div className="flow-arrow">→</div>
      <div className="flow-col wide"><h4>Elimination and transport</h4>
        {d.pathways.map((w) => (
          <div key={w.process} className="pathway" data-testid={`pathway-${w.process}`}>
            <div className="spread"><strong>{w.process}</strong><span className="muted">{w.kind}</span></div>
            {w.parameters.map((p) => <Param key={p.id} p={p} onSave={onFit} onRemove={onUnfit} />)}
          </div>
        ))}
        {d.pathways.length === 0 && <div className="param-node muted">no pathway placed</div>}
      </div>
    </div>
  );
}

export function D2Absorption({ view, onFit, onUnfit, onStructure }: {
  view: PlanView; onFit: FitSave; onUnfit: FitRemove; onStructure: (key: string, value: unknown, reason: string) => Promise<string | null>;
}) {
  const d = view.d2;
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <div data-testid="d2">
      <div className="row" style={{ marginBottom: 10, gap: 8 }}>
        <span>Food effect:</span>
        <span className={`chip ${d.food_effect_in_question ? "medium" : "neutral"}`}>
          {d.food_effect_in_question ? "the question — fed predicted, never fitted (MS-01 rule 5)" : "not the question"}
        </span>
        <input placeholder="why change it" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 200 }} />
        <button className="btn tiny" disabled={!reason.trim()}
                onClick={async () => setError(await onStructure("food_effect_in_question", !d.food_effect_in_question, reason))}>
          {d.food_effect_in_question ? "Not the question" : "Make it the question"}
        </button>
        {error && <span className="banner err">{error}</span>}
      </div>
      <div className="flow">
        <div className="flow-col"><h4>Solubility · permeability</h4>
          {d.absorption.map((p) => <Param key={p.id} p={p} onSave={onFit} onRemove={onUnfit} />)}</div>
        <div className="flow-arrow">→</div>
        <div className="flow-col wide"><h4>Products and release</h4>
          {d.lanes.map((lane) => (
            <div key={lane.name} className="pathway" data-testid={`lane-${lane.name}`}>
              <div className="spread"><strong>{lane.name}</strong><span className="muted">release: {lane.release}</span></div>
              {lane.parameters.map((p) => <div key={p.id} className="muted" style={{ fontSize: 12 }}><code>{p.id}</code> {String(p.value)} {p.unit ?? ""}</div>)}
              <div className="dag-chips">
                {lane.studies.map((s) => <span key={s.study_id} className="study-chip ghost" title={ROLE_LABEL[s.role]}>■ {s.study_id} · {s.food_state} · {s.role}</span>)}
                {lane.studies.length === 0 && <span className="muted" style={{ fontSize: 12 }}>no oral study with this product</span>}
              </div>
            </div>
          ))}
        </div>
        <div className="flow-arrow">→</div>
        <div className="flow-col"><h4>Dissolution</h4>
          {d.dissolution.map((p) => <div key={p.id} className="param-node"><span className="sq">◆</span> {p.label}<div className="muted" style={{ fontSize: 12 }}>{p.release_model.toLowerCase()}</div></div>)}
          {d.dissolution.length === 0 && <div className="param-node muted">no dissolution profile</div>}
        </div>
      </div>
    </div>
  );
}
