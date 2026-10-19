"use client";

import { useState } from "react";

import { EmptyState } from "@/components/kit";
import { send } from "@/lib/api";

import { type Run } from "./InputsTodo";
import type { Options, StudyRow } from "./StudiesTab";

type Demographics = { population?: string; sex?: string; age_years?: number; age_min?: number | null; age_max?: number | null;
                      weight_kg?: number | null; height_cm?: number | null };

const STATE: Record<StudyRow["demographics"], [string, string]> = {
  entered: ["low", "entered"], published: ["low", "the published simulation's individual"],
  default: ["medium", "healthy adult default (a MAP limitation)"], missing: ["high", "not stated"],
};
const num = (v: string) => (v.trim() === "" ? null : Number(v));

/** One study's individual (the PK-Sim Individual building block): entered from the study's report, or the explicit
 *  healthy adult default (D-29; listed as a limitation in the MAP), never applied silently. */
function Individual({ s, projectId, run, options }: { s: StudyRow; projectId: string; run: Run; options: Options }) {
  const given = (s.facts.demographics ?? {}) as Demographics;
  const [d, setD] = useState({
    population: given.population ?? "", sex: given.sex ?? "", age: given.age_years?.toString() ?? "",
    min: given.age_min?.toString() ?? "", max: given.age_max?.toString() ?? "",
    weight: given.weight_kg?.toString() ?? "", height: given.height_cm?.toString() ?? "",
  });
  const set = (k: keyof typeof d) => (x: { target: { value: string } }) => setD({ ...d, [k]: x.target.value });
  const [tone, label] = STATE[s.demographics];
  const path = "/api/v1/projects/{project_id}/datasets/{dataset_id}:study" as const;
  const params = { project_id: projectId, dataset_id: s.dataset_id ?? "" };
  const complete = d.population && d.sex && Number(d.age) > 0;
  return (
    <div className="individual" data-testid={`individual-${s.study_id}`} id={`individual-${s.study_id}`}>
      <div className="spread">
        <strong>{s.study_id}</strong>
        <span className={`chip ${tone}`}>{label}</span>
      </div>
      {s.demographics === "published" ? (
        <p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>Simulated with the individual its published simulation names.</p>
      ) : (
        <>
          <div className="row" style={{ gap: 6, marginTop: 6 }}>
            <select value={d.population} onChange={set("population")} aria-label={`population for ${s.study_id}`}>
              <option value="">population database…</option>
              {options.population.map((p) => <option key={p} value={p}>{p.replace(/_/g, " ")}</option>)}
            </select>
            <select value={d.sex} onChange={set("sex")} aria-label={`sex for ${s.study_id}`}>
              <option value="">sex…</option>
              {options.sex.map((v) => <option key={v} value={v}>{v.toLowerCase()}</option>)}
            </select>
            <input placeholder="mean age (y)" value={d.age} onChange={set("age")} style={{ width: 100 }} aria-label={`age for ${s.study_id}`} />
            <input placeholder="age from" value={d.min} onChange={set("min")} style={{ width: 80 }} aria-label={`age from for ${s.study_id}`} />
            <input placeholder="to" value={d.max} onChange={set("max")} style={{ width: 60 }} aria-label={`age to for ${s.study_id}`} />
            <input placeholder="weight (kg)" value={d.weight} onChange={set("weight")} style={{ width: 95 }} aria-label={`weight for ${s.study_id}`} />
            <input placeholder="height (cm)" value={d.height} onChange={set("height")} style={{ width: 95 }} aria-label={`height for ${s.study_id}`} />
          </div>
          <div className="row" style={{ gap: 6, marginTop: 6 }}>
            <button className="btn primary" disabled={!s.dataset_id || !complete}
                    onClick={() => void run(() => send("post", path, params, { changes: { demographics: {
                      population: d.population, sex: d.sex, age_years: Number(d.age), age_min: num(d.min), age_max: num(d.max),
                      weight_kg: num(d.weight), height_cm: num(d.height) } } }), `${s.study_id}: its individual is entered.`)}>
              Save the individual
            </button>
            <button className="btn" disabled={!s.dataset_id || s.demographics === "default"}
                    onClick={() => void run(() => send("post", path, params, { demographics_choice: "healthy_adult_default" }),
                                            `${s.study_id}: the healthy adult default, listed as a limitation of the MAP.`)}>
              Use the healthy adult default
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/** The individuals of the studies (D-29): each entered or the explicit healthy adult default. */
export function StudyIndividuals({ studies, projectId, run, options }: {
  studies: StudyRow[]; projectId: string; run: Run; options: Options;
}) {
  const used = studies.filter((s) => !s.excluded);
  if (!used.length) return <EmptyState title="No studies yet">Each study&apos;s individual is set here once its data is added.</EmptyState>;
  return <>{used.map((s) => <Individual key={`${s.study_id}-${s.demographics}`} s={s} projectId={projectId} run={run} options={options} />)}</>;
}
