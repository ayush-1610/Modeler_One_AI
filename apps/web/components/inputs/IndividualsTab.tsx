"use client";

// Each study's individual (the PK-Sim Individual building block; D-29), on Populations and individuals (plan 2026-11-14
// slice 3; the design text's "Tab Populations and individuals"): one row per study. A study in the model has its form
// (entered from the study's report, or the explicit healthy adult default, listed as a limitation in the MAP; never
// applied silently); studies that share one individual (the same default, the same published individual, the same
// entered demographics) sit on one line, each opening its own form. A study of the client's still to confirm on the
// delivery takes its demographics now, through `:enter`, with the individual PK-Sim simulates (its population database
// and sex, a person's choice): said as the card says it (`DeliverySubject.individual`, the landing's own rule), and
// simulated once it is confirmed; one to confirm with the sheet form is entered once it is confirmed, from its card.

import { useState } from "react";

import { SUBJECT } from "@/components/delivery/DeliveryReview";
import { DemographicsForm, demographicsText, statedDemographics } from "@/components/delivery/FactsForm";
import { EmptyState } from "@/components/kit";
import { send } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { normLabel, type Subject, type WorkItem } from "@/lib/inputsWork";
import { fieldInText, individualNeeds, individualText, plural } from "@/lib/words";

import { type Run } from "./InputsTodo";
import type { Options, StudyRow } from "./StudiesTab";

type Demographics = { population?: string; sex?: string; age_years?: number; age_min?: number | null; age_max?: number | null;
                      weight_kg?: number | null; height_cm?: number | null };

const STATE: Record<StudyRow["demographics"], [string, string]> = {
  entered: ["low", "entered"], published: ["low", "the published simulation's individual"],
  default: ["neutral", "healthy adult default (a MAP limitation)"], missing: ["high", "not stated"],
};
const num = (v: string) => (v.trim() === "" ? null : Number(v));

/** One study's individual: entered from the study's report, or the explicit healthy adult default. */
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
        <p className="muted m-4-0-0 fs-13">Simulated with the individual its published simulation names.</p>
      ) : (
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

/** What two studies share when they share an individual: its kind and, entered, its values. */
const sharedKey = (s: StudyRow) => (s.demographics === "missing" ? null : `${s.demographics}|${JSON.stringify(s.facts.demographics ?? {})}`);

/** Studies that share one individual, on one line; each opens its own form. */
function SharedLine({ studies, projectId, run, options }: { studies: StudyRow[]; projectId: string; run: Run; options: Options }) {
  const [open, setOpen] = useState<string | null>(null);
  const [tone, label] = STATE[studies[0].demographics];
  const given = (studies[0].facts.demographics ?? {}) as Demographics;
  const values = studies[0].demographics === "entered"
    ? [given.population?.replace(/_/g, " "), given.sex?.toLowerCase(), given.age_years ? `${given.age_years} y` : "", given.weight_kg ? `${given.weight_kg} kg` : ""]
      .filter(Boolean).join(" · ") : "";
  return (
    <div className="individual shared" data-testid={`individual-shared-${studies.map((s) => s.study_id).join("-")}`}>
      <div className="spread">
        <span>
          {studies.map((s, i) => (
            <span key={s.study_id}>{i > 0 && " · "}
              <button type="button" className="link-btn" aria-expanded={open === s.study_id} onClick={() => setOpen(open === s.study_id ? null : s.study_id)}
                      aria-label={`Change the individual of ${s.study_id}`}><strong>{s.study_id}</strong></button>
            </span>
          ))}
          <span className="muted fs-13"> · {plural(studies.length, "study", "studies")}, one individual{values ? `: ${values}` : ""}</span>
        </span>
        <span className={`chip ${tone}`}>{label}</span>
      </div>
      {open && <div className="mt-6"><Individual s={studies.find((s) => s.study_id === open)!} projectId={projectId} run={run} options={options} /></div>}
    </div>
  );
}

/** The individuals of the studies (D-29): each study in the model with its form, those sharing an individual on one line;
 *  the client's studies still to confirm, with their demographics now (on the delivery) or once confirmed (the sheet
 *  form). */
export function StudyIndividuals({ studies, projectId, run, options, subjects = [], vocabulary = null, onOpen }: {
  studies: StudyRow[]; projectId: string; run: Run; options: Options;
  /** the client's studies (one card each), to list those not confirmed yet */
  subjects?: Subject[];
  /** a table layout to read the intake vocabulary from (the population's words), if any */
  vocabulary?: string | null;
  /** open a study's card */
  onOpen?: (item: WorkItem | null, subject: Subject) => void;
}) {
  const used = studies.filter((s) => !s.excluded);
  const inModel = new Set(used.map((s) => normLabel(s.study_id)));
  const pending = subjects.filter((s) => s.kind === "study" && !s.done && !inModel.has(normLabel(s.label)));
  const groups = new Map<string, StudyRow[]>();
  const alone: StudyRow[] = [];
  for (const s of used) {
    const key = sharedKey(s);
    if (key === null) alone.push(s);
    else groups.set(key, [...(groups.get(key) ?? []), s]);
  }
  for (const [key, list] of [...groups]) if (list.length < 2) { alone.push(...list); groups.delete(key); }
  if (!used.length && !pending.length) {
    return <EmptyState title="No study confirmed yet">Each confirmed study gets its individual here; a client&apos;s study to confirm on the
      delivery can take its demographics as soon as it arrives.</EmptyState>;
  }
  return (
    <>
      {used.length === 0 && <p className="muted m-0 fs-13">No study is in the model yet: each confirmed study gets its individual here.</p>}
      {[...groups.values()].map((list) => <SharedLine key={list.map((s) => s.study_id).join("|")} studies={list} projectId={projectId} run={run} options={options} />)}
      {alone.map((s) => <Individual key={`${s.study_id}-${s.demographics}`} s={s} projectId={projectId} run={run} options={options} />)}
      {pending.length > 0 && (
        <div className="individuals-pending" data-testid="individuals-pending">
          <h4 className="delivery-sub">The client&apos;s studies to confirm</h4>
          {pending.map((s) => <Pending key={s.key} s={s} projectId={projectId} vocabulary={vocabulary} options={options} onOpen={onOpen} />)}
        </div>
      )}
    </>
  );
}

/** A client's study not confirmed yet: on the delivery, its demographics are entered now with the individual PK-Sim
 *  simulates, which loads with the study; until the individual is chosen they are kept, not simulated, as the card and
 *  the loading say (`DeliverySubject.individual`). With the sheet form, they are entered once it is confirmed. */
function Pending({ s, projectId, vocabulary, options, onOpen }: {
  s: Subject; projectId: string; vocabulary: string | null; options: Options; onOpen?: (item: WorkItem | null, subject: Subject) => void;
}) {
  const [entering, setEntering] = useState(false);
  const delivery = s.path === "delivery" && s.row && !s.blinded ? s.row : null;
  // the study's card, under the key its card uses: what is stated on it already, and the individual it makes
  const card = useResource(SUBJECT, { project_id: projectId, type: delivery?.subject_type ?? "study", subject: delivery?.subject ?? "" },
                           { enabled: Boolean(delivery) });
  const stated = statedDemographics((card.data?.tables ?? []).flatMap((t) => t.values));
  const said = demographicsText(stated);
  const individual = card.data?.individual ?? null;
  const set = individual?.demographics ?? null;
  const chip = s.path !== "delivery" ? "to confirm first" : set || !said ? "loads when the study is confirmed" : "kept, not simulated yet";
  return (
    <div className="individual pending" data-testid={`individual-pending-${s.key}`}>
      <div className="spread">
        <strong>{s.label}</strong>
        <span className={`chip ${set || !said || s.path !== "delivery" ? "neutral" : "high"}`}>{chip}</span>
      </div>
      {delivery ? (
        entering ? (
          <DemographicsForm key={said} projectId={projectId} params={{ project_id: projectId, type: delivery.subject_type, subject: delivery.subject }}
                            vocabulary={{ mapping: vocabulary }} options={options} onDone={() => setEntering(false)}
                            testId={`individual-enter-${delivery.subject}`} stated={stated} />
        ) : said ? (
          <p className="m-4-0-0 fs-13" data-testid={`individual-entered-${delivery.subject}`}>
            {set ? <><span className="muted">The individual:</span> {individualText(set)}
              {individual && individual.kept.length > 0 && <span className="muted"> · {individual.kept.map(fieldInText).join(", ")} kept, not simulated</span>}</>
              : <>{said}{individual ? <span className="muted"> · {individualNeeds(individual.needs, individual.why)}</span> : null}</>}{" "}
            <button type="button" className="link-btn" onClick={() => setEntering(true)} data-testid={`individual-enter-open-${delivery.subject}`}
                    aria-label={`${set ? "Correct" : "Choose"} the individual of ${s.label}`}>{set ? "Correct…" : "Choose the individual…"}</button>
          </p>
        ) : (
          <p className="m-4-0-0 fs-13">
            <button type="button" className="btn small" onClick={() => setEntering(true)} data-testid={`individual-enter-open-${delivery.subject}`}
                    disabled={!card.data && !card.problem}>Enter them…</button>
            <span className="muted"> the population, age, weight and share of women, from the study&apos;s report, with the PK-Sim population and the
              sex to simulate; or ask the client from its card.</span>
          </p>
        )
      ) : (
        <p className="m-4-0-0 fs-13">
          {onOpen ? <button type="button" className="link-btn" onClick={() => onOpen(null, s)}>Enter once the study is confirmed →</button>
            : "Enter once the study is confirmed."}
          {s.blinded && <span className="muted"> Blinded until the plan is signed.</span>}
        </p>
      )}
    </div>
  );
}
