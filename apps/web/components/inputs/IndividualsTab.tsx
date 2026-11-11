"use client";

import { useState } from "react";

import { EmptyState, InlineIssue } from "@/components/kit";
import { TableFilter, TableMore } from "@/components/kit/SortableTable";
import { send } from "@/lib/api";
import { useTableView } from "@/lib/tableView";

import { type Run } from "./InputsTodo";
import type { Options, StudyRow } from "./StudiesTab";

type Demographics = { population?: string; sex?: string; age_years?: number; age_min?: number | null; age_max?: number | null;
                      weight_kg?: number | null; height_cm?: number | null };

const STATE: Record<StudyRow["demographics"], [string, string]> = {
  entered: ["low", "entered"], published: ["low", "the published simulation's individual"],
  default: ["medium", "healthy adult default (a MAP limitation)"], missing: ["high", "not stated"],
};
const num = (v: string) => (v.trim() === "" ? null : Number(v));
// a study whose individual still needs the person: not stated, or the healthy adult default (a MAP limitation)
const open = (s: StudyRow) => s.demographics === "missing" || s.demographics === "default";
const NO_KEYS = {};
const studyText = (s: StudyRow) => `${s.study_id} ${STATE[s.demographics][1]} ${summary(s)}`;

/** One line for an individual already settled, from its stored demographics only (nothing filled in). */
function summary(s: StudyRow): string {
  if (s.demographics === "published") return "the individual its published simulation names";
  const d = (s.facts.demographics ?? {}) as Demographics;
  const age = d.age_years != null ? `${d.age_years} y${d.age_min != null || d.age_max != null ? ` (${d.age_min ?? "?"}–${d.age_max ?? "?"})` : ""}` : null;
  return [d.population?.replace(/_/g, " "), d.sex?.toLowerCase(), age, d.weight_kg != null ? `${d.weight_kg} kg` : null,
          d.height_cm != null ? `${d.height_cm} cm` : null].filter(Boolean).join(" · ");
}

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
  // entered and published individuals are one line; the form opens on "Edit" (the 2026-11-11 audit 2, item 2)
  const [editing, setEditing] = useState(open(s));
  const [problem, setProblem] = useState<string | null>(null);
  const act: Run = async (fn, ok) => { const p = await run(fn, ok); setProblem(p); return p; };
  return (
    <div className={`individual ${editing ? "" : "settled"}`} data-testid={`individual-${s.study_id}`} id={`individual-${s.study_id}`}>
      <div className="spread">
        <strong>{s.study_id}</strong>
        {!editing && <span className="muted fs-13 individual-summary">{summary(s)}</span>}
        <span className="row gap-6">
          <span className={`chip ${tone}`}>{label}</span>
          {!open(s) && s.demographics !== "published" && (
            <button type="button" className="link-btn" aria-expanded={editing} onClick={() => setEditing(!editing)}
                    aria-label={`${editing ? "Close" : "Edit"} the individual of ${s.study_id}`}>{editing ? "Close" : "Edit"}</button>
          )}
        </span>
      </div>
      {s.demographics === "published" || !editing ? null : (
        <>
          <div className="row gap-6 mt-6">
            <select value={d.population} onChange={set("population")} aria-label={`population for ${s.study_id}`}>
              <option value="">population database…</option>
              {options.population.map((p) => <option key={p} value={p}>{p.replace(/_/g, " ")}</option>)}
            </select>
            <select value={d.sex} onChange={set("sex")} aria-label={`sex for ${s.study_id}`}>
              <option value="">sex…</option>
              {options.sex.map((v) => <option key={v} value={v}>{v.toLowerCase()}</option>)}
            </select>
            <input placeholder="mean age (y)" value={d.age} onChange={set("age")} className="w-100" aria-label={`age for ${s.study_id}`} />
            <input placeholder="age from" value={d.min} onChange={set("min")} className="w-80" aria-label={`age from for ${s.study_id}`} />
            <input placeholder="to" value={d.max} onChange={set("max")} className="w-60" aria-label={`age to for ${s.study_id}`} />
            <input placeholder="weight (kg)" value={d.weight} onChange={set("weight")} className="w-95" aria-label={`weight for ${s.study_id}`} />
            <input placeholder="height (cm)" value={d.height} onChange={set("height")} className="w-95" aria-label={`height for ${s.study_id}`} />
          </div>
          <div className="row gap-6 mt-6">
            <button className="btn primary" disabled={!s.dataset_id || !complete}
                    onClick={() => void act(() => send("post", path, params, { changes: { demographics: {
                      population: d.population, sex: d.sex, age_years: Number(d.age), age_min: num(d.min), age_max: num(d.max),
                      weight_kg: num(d.weight), height_cm: num(d.height) } } }), `${s.study_id}: its individual is entered.`)}>
              Save the individual
            </button>
            <button className="btn" disabled={!s.dataset_id || s.demographics === "default"}
                    onClick={() => void act(() => send("post", path, params, { demographics_choice: "healthy_adult_default" }),
                                            `${s.study_id}: the healthy adult default, listed as a limitation of the MAP.`)}>
              Use the healthy adult default
            </button>
          </div>
          {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
        </>
      )}
    </div>
  );
}

/** The individuals of the studies (D-29): each entered or the explicit healthy adult default. The ones still open (not
 *  stated, or the default) are always shown; the rest page by 20 under a filter (the 2026-11-11 audit 2, item 2). */
export function StudyIndividuals({ studies, projectId, run, options }: {
  studies: StudyRow[]; projectId: string; run: Run; options: Options;
}) {
  const used = studies.filter((s) => !s.excluded);
  const view = useTableView({ rows: used, keys: NO_KEYS, text: studyText, pageSize: 20, keep: open });
  if (!used.length) return <EmptyState title="No studies yet">Each study&apos;s individual is set here once its data is added.</EmptyState>;
  return (
    <>
      {used.length > 20 && <TableFilter view={view} placeholder="Filter the studies: id, population, sex…" label="Filter the studies' individuals"
                                        testId="individuals-filter" />}
      {view.visible.map((s) => <Individual key={`${s.study_id}-${s.demographics}`} s={s} projectId={projectId} run={run} options={options} />)}
      {view.visible.length === 0 && <p className="muted table-none">No study matches this filter.</p>}
      <TableMore view={view} noun="studies" testId="individuals-more" />
    </>
  );
}
