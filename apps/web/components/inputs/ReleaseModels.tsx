"use client";

// A formulation's release model, chosen here (the owner's D1; plan 2026-11-26 §8): the Data room sends the Weibull fit of
// a product whose dissolution profile levels off below 100 %, with its suggestion as a proposal. A person confirms it, or
// holds the formulation for particle dissolution with a reason (its Weibull values are set aside) and enters its particle
// radius and unstirred-layer thickness, or takes the Weibull fit again. Until each is answered the inputs wait.

import { useState } from "react";

import { send, type Schema } from "@/lib/api";

import { MODEL } from "./after";
import { type Run } from "./InputsTodo";

type Row = Schema<"ReleaseModelRow">;

const PATH = "/api/v1/projects/{project_id}/formulations/{name}:release-model" as const;

function Proposed({ r, projectId, run }: { r: Row; projectId: string; run: Run }) {
  const [holding, setHolding] = useState(false);
  const [reason, setReason] = useState("");
  const params = { project_id: projectId, name: r.formulation };
  return (
    <div className="proposal mt-12" data-testid={`proposal-${r.formulation}`} id={`proposal-${r.formulation}`} data-state="proposed">
      <strong>{r.formulation}</strong>
      <p className="m-4-0-0">Release model: <strong>{r.label}</strong>{r.detail && <span className="muted fs-12"> · {r.detail}</span>}</p>
      {r.why && <p className="muted fs-12 m-2-0">Why the Data room suggests it: {r.why}</p>}
      {(r.sources ?? []).length > 0 && <p className="muted fs-12 m-0">{(r.sources ?? []).join("; ")}</p>}
      <div className="row gap-6 mt-6">
        <button type="button" className="btn primary" data-testid={`release-confirm-${r.formulation}`}
                onClick={() => void run(() => send("post", PATH, params, { model: "weibull" }),
                                        `${r.formulation}: the Weibull fit is confirmed as its release.`, MODEL)}>
          Confirm the Weibull fit
        </button>
        {r.other && !holding && (
          <button type="button" className="btn" data-testid={`release-hold-open-${r.formulation}`} onClick={() => setHolding(true)}>
            {r.other.label} instead…
          </button>
        )}
      </div>
      {holding && r.other && (
        <div className="mt-6" data-testid={`release-hold-${r.formulation}`}>
          <p className="muted fs-12 m-0">{r.other.detail}. Its Weibull values are set aside, and the formulation waits for its particle
            radius and unstirred-layer thickness, entered next.</p>
          <div className="row gap-6 mt-4">
            <label className="add-field flex-1 minw-220">Why particle dissolution
              <input value={reason} onChange={(e) => setReason(e.target.value)} data-testid={`release-hold-reason-${r.formulation}`}
                     aria-label={`Why particle dissolution for ${r.formulation}`} /></label>
            <button type="button" className="btn" disabled={!reason.trim()} data-testid={`release-hold-${r.formulation}-confirm`}
                    onClick={() => void run(() => send("post", PATH, params, { model: "particles", reason }),
                                            `${r.formulation}: held for particle dissolution.`, MODEL)}>
              Hold for particle dissolution
            </button>
            <button type="button" className="btn" onClick={() => setHolding(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

const SOURCES = [["PUBLICATION", "publication"], ["CLIENT_REPORT", "client report"], ["REGULATORY_REVIEW", "regulatory review"],
                 ["DATABASE", "database"], ["ASSUMPTION", "assumption (no source)"]] as const;

/** A formulation held for particle dissolution: why and by whom, its particle inputs to enter (parameter registry 1.3:
 *  the radius in µm and the unstirred-layer thickness in mm, each as the source states it, converted by code), or the
 *  Weibull fit after all. */
function Held({ r, projectId, run }: { r: Row; projectId: string; run: Run }) {
  const [radius, setRadius] = useState("");
  const [radiusUnit, setRadiusUnit] = useState("µm");
  const [thickness, setThickness] = useState("");
  const [thicknessUnit, setThicknessUnit] = useState("mm");
  const [type, setType] = useState<(typeof SOURCES)[number][0]>("PUBLICATION");
  const [title, setTitle] = useState("");
  const [quote, setQuote] = useState("");
  const params = { project_id: projectId, name: r.formulation };
  const ready = Number(radius) > 0 && Number(thickness) > 0 && radiusUnit.trim() && thicknessUnit.trim()
    && (type === "ASSUMPTION" || title.trim());
  const id = (what: string) => `particles-${what}-${r.formulation}`;
  return (
    <div className="proposal mt-12" data-testid={`proposal-${r.formulation}`} id={`proposal-${r.formulation}`} data-state="held">
      <strong>{r.formulation}</strong>
      <p className="m-4-0-0">Held for particle dissolution{r.by ? ` by ${r.by}` : ""}: {r.reason}</p>
      <p className="muted fs-12 m-2-0">Enter its particle radius and the unstirred water layer&apos;s thickness, each as the source states
        it: they are converted to PK-Sim&apos;s units (µm, mm) and the formulation is built as particle dissolution.</p>
      <div className="row gap-6 mt-4">
        <label className="add-field">Particle radius (mean)
          <input value={radius} onChange={(e) => setRadius(e.target.value)} className="w-90" inputMode="decimal"
                 data-testid={id("radius")} aria-label={`particle radius for ${r.formulation}`} /></label>
        <label className="add-field">Unit
          <input value={radiusUnit} onChange={(e) => setRadiusUnit(e.target.value)} className="w-90"
                 aria-label={`unit of the particle radius for ${r.formulation}`} /></label>
        <label className="add-field">Layer thickness
          <input value={thickness} onChange={(e) => setThickness(e.target.value)} className="w-90" inputMode="decimal"
                 data-testid={id("thickness")} aria-label={`unstirred-layer thickness for ${r.formulation}`} /></label>
        <label className="add-field">Unit
          <input value={thicknessUnit} onChange={(e) => setThicknessUnit(e.target.value)} className="w-90"
                 aria-label={`unit of the layer thickness for ${r.formulation}`} /></label>
      </div>
      <div className="row gap-6 mt-4">
        <label className="add-field">Source
          <select value={type} onChange={(e) => setType(e.target.value as typeof type)} aria-label={`source type for ${r.formulation}`}>
            {SOURCES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select></label>
        <label className="add-field flex-1 minw-140">Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} data-testid={id("title")}
                 aria-label={`source title for ${r.formulation}`} /></label>
        <label className="add-field flex-1 minw-220">The sentence that states them
          <input value={quote} onChange={(e) => setQuote(e.target.value)} aria-label={`quote for ${r.formulation}`} /></label>
      </div>
      <div className="row gap-6 mt-6">
        <button type="button" className="btn primary" disabled={!ready} data-testid={id("enter")}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/formulations/{name}:particles", params, {
                  radius: { value: Number(radius), unit: radiusUnit }, thickness: { value: Number(thickness), unit: thicknessUnit },
                  source_type: type, title, quote,
                }), `${r.formulation}: built as particle dissolution.`, MODEL)}>
          Use these particle inputs
        </button>
        <button type="button" className="btn" data-testid={`release-take-${r.formulation}`}
                onClick={() => void run(() => send("post", PATH, params, { model: "weibull" }),
                                        `${r.formulation}: its Weibull fit is used again.`, MODEL)}>
          Use the Weibull fit after all
        </button>
      </div>
    </div>
  );
}

export function ReleaseModels({ rows, projectId, run }: { rows: readonly Row[]; projectId: string; run: Run }) {
  if (!rows.length) return null;
  return (
    <section className="card proposals" data-testid="release-models" aria-label="Release models proposed by the Data room">
      <h3 className="m-0">Release models proposed by the Data room</h3>
      <p className="muted fs-13 m-4-0-0">A product whose dissolution profile levels off below 100 % can be released two ways. The Data
        room sent its Weibull fit and suggests a model from the delivery&apos;s facts: confirm it, or hold the formulation for
        particle dissolution. The inputs wait for it.</p>
      {rows.map((r) => r.state === "held"
        ? <Held key={r.formulation} r={r} projectId={projectId} run={run} />
        : <Proposed key={r.formulation} r={r} projectId={projectId} run={run} />)}
    </section>
  );
}
