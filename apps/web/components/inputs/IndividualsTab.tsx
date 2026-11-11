"use client";

import { useState } from "react";

import { EmptyState, InlineIssue, LabeledControl, WaitingFor } from "@/components/kit";
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
// an optional typed number: empty is null (not stated); anything typed must be a finite number, or the form will not save it
// (it once sent "70 kg" as null and still said the individual was entered: 2026-11-11 audit 2, item 7)
const num = (v: string) => (v.trim() === "" ? null : Number(v.trim()));
const bad = (v: string) => v.trim() !== "" && !Number.isFinite(Number(v.trim()));
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
  const ageBad = bad(d.age) || (d.age.trim() !== "" && !(Number(d.age) > 0));
  const minBad = bad(d.min), maxBad = bad(d.max), weightBad = bad(d.weight), heightBad = bad(d.height);
  const age = Number(d.age), lo = num(d.min), hi = num(d.max);
  // the mean lies within the stated range: age from ≤ mean ≤ age to
  const rangeBad = !minBad && !maxBad && !ageBad && ((lo !== null && hi !== null && lo > hi)
    || (d.age.trim() !== "" && ((lo !== null && lo > age) || (hi !== null && hi < age))));
  const needed = [
    !d.population && "the population database", !d.sex && "the sex", d.age.trim() === "" && "the mean age",
    ageBad && "a mean age above 0, in years", minBad && "age from as a number", maxBad && "age to as a number",
    weightBad && "the weight as a number in kg", heightBad && "the height as a number in cm",
    rangeBad && "age from ≤ mean age ≤ age to",
  ].filter((x): x is string => Boolean(x));
  const complete = needed.length === 0;
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
          <div className="ctl-row mt-6">
            <LabeledControl label="Population database" required>
              <select value={d.population} onChange={set("population")} aria-label={`population for ${s.study_id}`}>
                <option value="">choose…</option>
                {options.population.map((p) => <option key={p} value={p}>{p.replace(/_/g, " ")}</option>)}
              </select>
            </LabeledControl>
            <LabeledControl label="Sex" required>
              <select value={d.sex} onChange={set("sex")} aria-label={`sex for ${s.study_id}`}>
                <option value="">choose…</option>
                {options.sex.map((v) => <option key={v} value={v}>{v.toLowerCase()}</option>)}
              </select>
            </LabeledControl>
            <LabeledControl label="Mean age (y)" required className="w-110">
              <input placeholder="mean age (y)" value={d.age} onChange={set("age")} inputMode="decimal" aria-invalid={ageBad || rangeBad}
                     aria-label={`age for ${s.study_id}`} />
            </LabeledControl>
            <LabeledControl label="Age from (y)" className="w-95">
              <input placeholder="age from" value={d.min} onChange={set("min")} inputMode="decimal" aria-invalid={minBad || rangeBad}
                     aria-label={`age from for ${s.study_id}`} />
            </LabeledControl>
            <LabeledControl label="Age to (y)" className="w-95">
              <input placeholder="to" value={d.max} onChange={set("max")} inputMode="decimal" aria-invalid={maxBad || rangeBad}
                     aria-label={`age to for ${s.study_id}`} />
            </LabeledControl>
            <LabeledControl label="Weight (kg)" className="w-95">
              <input placeholder="weight (kg)" value={d.weight} onChange={set("weight")} inputMode="decimal" aria-invalid={weightBad}
                     aria-label={`weight for ${s.study_id}`} />
            </LabeledControl>
            <LabeledControl label="Height (cm)" className="w-95">
              <input placeholder="height (cm)" value={d.height} onChange={set("height")} inputMode="decimal" aria-invalid={heightBad}
                     aria-label={`height for ${s.study_id}`} />
            </LabeledControl>
          </div>
          <div className="row gap-6 mt-6">
            <button className="btn primary" disabled={!s.dataset_id || !complete}
                    onClick={() => void act(() => send("post", path, params, { changes: { demographics: {
                      population: d.population, sex: d.sex, age_years: age, age_min: lo, age_max: hi,
                      weight_kg: num(d.weight), height_cm: num(d.height) } } }), `${s.study_id}: its individual is entered.`)}>
              Save the individual
            </button>
            <button className="btn" disabled={!s.dataset_id || s.demographics === "default"}
                    onClick={() => void act(() => send("post", path, params, { demographics_choice: "healthy_adult_default" }),
                                            `${s.study_id}: the healthy adult default, listed as a limitation of the MAP.`)}>
              Use the healthy adult default
            </button>
            {!complete && <WaitingFor testId={`needed-individual-${s.study_id}`}>To save: {needed.join(", ")}.</WaitingFor>}
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
