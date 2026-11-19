"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { BlindedReason } from "@/components/delivery/BlindedReason";
import { Digitizer } from "@/components/evidence/Digitizer";
import { InlineIssue } from "@/components/kit";
import { TableFilter, TableMore } from "@/components/kit/SortableTable";
import { narrow, send, upload, type Narrow, type Schema } from "@/lib/api";
import type { DocumentView } from "@/lib/brief";
import { useResource } from "@/lib/hooks";
import { useTableView } from "@/lib/tableView";
import { datasetFlagText, datasetHolds, datasetNames, datasetSource, lowerFirst, pkParamText, unpromisedText, valueWord } from "@/lib/words";

import { MODEL, SEARCH, datasetAfter, evidenceAfter } from "./after";
import type { Run } from "./InputsTodo";

// a stored dataset (modeler_project.datasets.ObservedDataset), as the dataset routes answer it
type Dataset = Schema<"ObservedDataset">;
// a dataset as GET /projects/{id}/evidence lists it: for an external study before the MAP is signed (D-15) the
// redaction, its values withheld and marked `blinded`, with why its study is on the blinding list (`blinded_why`: round 5)
export type Listed = Narrow<Dataset, { reported: (Omit<Schema<"ReportedPK">, "value"> & { value: number | null })[] }>
  & { blinded?: boolean; blinded_why?: string | null };
type AccessRequest = { id: string; title: string; authors: string; doi: string | null; needed_for: string; status: string };
type View = Narrow<Pick<Schema<"EvidencePage">, "agents" | "running" | "datasets" | "access_requests">, {
  datasets: Listed[]; access_requests: AccessRequest[];
}>;

const ORIGIN_CHIP: Record<string, string> = {
  CLIENT: "low", LITERATURE: "low", FIGURE_DIGITIZED: "medium", OSP_LIBRARY: "low", SYNTHETIC: "high", ILLUSTRATIVE: "high",
};
/** Where a dataset comes from, in words (its `origin`). */
const ORIGIN_WORD: Record<string, string> = {
  CLIENT: "client", LITERATURE: "literature", FIGURE_DIGITIZED: "digitized figure", OSP_LIBRARY: "OSP library", SYNTHETIC: "synthetic",
  ILLUSTRATIVE: "illustrative",
};
const originWord = (origin: string) => ORIGIN_WORD[origin] ?? origin.toLowerCase().replace(/_/g, " ");

/** Where a dataset stands: in the model, left out with its reason, a digitized figure waiting for its overlay check, or
 *  the client's data waiting for a person to confirm its study (not in the model until then:
 *  `awaits_client_confirmation`, plan 2026-11-03 §3.3; never shown as in the model, the 2026-11-14 audit). */
export function standing(d: Listed): [string, string] {
  if (d.state === "REJECTED") return ["neutral", "left out"];
  if (d.origin === "CLIENT" && d.extraction !== "MANUAL" && d.state === "PROPOSED") return ["neutral", "waiting for confirmation"];
  if (d.origin === "FIGURE_DIGITIZED" && d.state !== "ACCEPTED" && !d.digitization?.overlay_approved_by) return ["medium", "overlay to check"];
  return ["low", "in the model"];
}

const SHOW = [
  { id: "all", label: "All", test: () => true },
  { id: "used", label: "In the model", test: (d: Listed) => standing(d)[1] === "in the model" },
  { id: "out", label: "Left out", test: (d: Listed) => d.state === "REJECTED" },
  { id: "overlay", label: "Overlay to check", test: (d: Listed) => standing(d)[1] === "overlay to check" },
  { id: "waiting", label: "Waiting for confirmation", test: (d: Listed) => standing(d)[1] === "waiting for confirmation" },
  { id: "blinded", label: "Blinded", test: (d: Listed) => Boolean(d.blinded) },
] as const;
type Show = (typeof SHOW)[number]["id"];
const NO_KEYS = {};
const datasetText = (d: Listed) => [d.study.study_id, d.origin, d.purpose, d.kind, d.study.route, d.study.formulation, d.source.title,
  standing(d)[1]].filter(Boolean).join(" ").replace(/_/g, " ");

/** The dataset cards, ten at a time with a text and a state filter; a blinded dataset or a figure whose overlay is still
 *  to check is always shown (the 2026-11-11 audit, item 11). */
function DatasetList({ datasets, projectId, run, unpromised }: { datasets: Listed[]; projectId: string; run: Run; unpromised: string[] }) {
  const [show, setShow] = useState<Show>("all");
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set());
  const view = useTableView({
    rows: datasets, keys: NO_KEYS, text: datasetText, pageSize: 10,
    filter: SHOW.find((x) => x.id === show)!.test, filterKey: show,
    keep: (d) => Boolean(d.blinded) || standing(d)[1] === "overlay to check", pin: (d) => touched.has(d.id),
  });
  const touch = (id: string) => { if (!touched.has(id)) setTouched(new Set([...touched, id])); };
  const names = namesOf(datasets);
  return (
    <>
      {datasets.length > 10 && (
        <TableFilter view={view} placeholder="Filter datasets: study, origin, source…" label="Filter the datasets" testId="datasets-filter">
          <div className="table-chips" role="group" aria-label="Show datasets">
            {SHOW.map((x) => (
              <button key={x.id} type="button" aria-pressed={show === x.id} data-testid={`datasets-show-${x.id}`}
                      onClick={() => setShow(x.id)}>{x.label}</button>
            ))}
          </div>
        </TableFilter>
      )}
      <div className="paged-cards">
        {view.visible.map((d) => (
          <div key={d.id} onInput={() => touch(d.id)}><DatasetCard d={d} name={names.get(d.id) ?? d.id} projectId={projectId} run={run}
                                                                unpromised={unpromisedOf(d, unpromised)} /></div>
        ))}
      </div>
      {view.visible.length === 0 && <p className="muted table-none">No dataset matches this filter.</p>}
      <TableMore view={view} noun="datasets" testId="datasets-more" />
    </>
  );
}

/** Each dataset's name, for the controls repeated on its line or card (Show the points, Leave it out…, the reveal and the
 *  overlay check): its study, what it holds (analyte, matrix, series) and where it was read from (`words.datasetNames`).
 *  230-23's parent and metabolite, read from one sheet, were named alike (final review round 6). */
const namesOf = (datasets: Listed[]) => {
  const names = datasetNames(datasets);
  return new Map(datasets.map((d, i) => [d.id, names[i]]));
};

/** What the client's reconciliation says of a dataset its data plan did not promise ("dataset CL-01 (ds-…): delivered,
 *  not promised by the data plan", by the dataset's id), if anything. */
const unpromisedOf = (d: Listed, lines: string[]) => lines.find((u) => u.includes(`(${d.id})`)) ?? null;

/** Leave a dataset out of the model, or take it back, with the reason: one small button, the reason asked only when it is
 *  pressed. */
function LeaveOut({ d, name: which, projectId, run, onProblem }: {
  d: Listed; projectId: string; run: Run; onProblem: (p: string | null) => void;
  /** the dataset's name (`namesOf`): a study has a dataset per file it is read from (EX-101's sheet and its protocol,
   *  final review round 4) and per analyte (230-23's parent and metabolite, round 6) */
  name: string;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const out = d.state === "REJECTED";
  const id = String(d.study.study_id);
  if (!open) {
    return <button type="button" className="link-btn" onClick={() => setOpen(true)} data-testid={`dataset-leave-${d.id}`}
                   aria-label={out ? `Use it again… the dataset of ${which}` : `Leave it out… the dataset of ${which}`}>{out ? "Use it again…" : "Leave it out…"}</button>;
  }
  return (
    <span className="row gap-6">
      <input autoFocus className="flex-1 minw-180" placeholder={out ? "why use it again" : "why leave it out"} value={reason}
             onChange={(e) => setReason(e.target.value)} aria-label={`reason for the dataset of ${which}`}
             onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }} />
      <button className="btn" disabled={!reason.trim()} data-testid={`dataset-exclude-${d.id}`}
              aria-label={`${out ? "Use it again" : "Leave it out"}: the dataset of ${which}`}
              onClick={async () => onProblem(await run(() => send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:decide",
                                                                  { project_id: projectId, dataset_id: d.id },
                                                                  { state: out ? "PROPOSED" : "REJECTED", reason }),
                                                       out ? `${id} is used again.` : `${id} is left out: ${reason}.`, datasetAfter(projectId, d.id)))}>
        {out ? "Use it again" : "Leave it out"}
      </button>
      {/* named by its dataset: with both of 230-23's forms open, two "Cancel" read alike (final review round 7) */}
      <button type="button" className="link-btn" data-testid={`dataset-leave-cancel-${d.id}`} aria-label={`Cancel: the dataset of ${which}`}
              onClick={() => setOpen(false)}>Cancel</button>
    </span>
  );
}

/** A blinded dataset (an external study before the MAP is signed, D-15): revealed for one check with the reason, which
 *  the audit trail keeps. Why it is blinded is said, in the words every withheld study is (round 5: "blinded until the MAP
 *  is signed" said nothing of why), the plan's or the split's part leading to the studies' roles on Review & sign.
 *  `onRevealed` receives the dataset with its values. */
function Reveal({ d, name, projectId, onRevealed, onProblem, compact = false, said = null }: {
  d: Listed; name: string; projectId: string; onRevealed: (d: Listed) => void; onProblem: (p: string | null) => void; compact?: boolean;
  /** the reason its study's card says already (its withheld line): not said again on the card (round 7) */
  said?: string | null;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className={`banner warn ${compact ? "m-4-0 fs-13" : "m-6-0"}`} data-testid={`blinded-${d.id}`}>
      {/* one sentence, its reference after what it qualifies (round 7: "… (what they still wait on) (ICH M15).") */}
      <span id={`${compact ? "blinded-why-line" : "blinded-why"}-${d.id}`} data-testid={`blinded-why-${d.id}`}>Its values are blinded until the plan is signed
        (ICH M15){d.blinded_why && d.blinded_why !== said ? <>, because <BlindedReason why={d.blinded_why} projectId={projectId} /></> : null}.</span>
      {compact ? " To check them now, give the reason; the access is recorded in the audit trail."
        : " The metadata above is what the split uses. To check this dataset now, give the reason; the access is recorded in the audit trail."}
      <div className="row mt-6">
        <input className="flex-1 minw-180" placeholder="why it must be seen now (required)" value={reason}
               onChange={(e) => setReason(e.target.value)} aria-label={`why the dataset of ${name} must be seen now`} />
        <button className="btn" disabled={!reason.trim()} aria-label={`Reveal for this check: the dataset of ${name}`} onClick={async () => {
          const env = await send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:reveal",
                                 { project_id: projectId, dataset_id: d.id }, { reason });
          if (env.data) { onRevealed(env.data as Listed); onProblem(null); } else onProblem(env.errors?.[0]?.message ?? "not revealed");
        }}>Reveal for this check</button>
      </div>
    </div>
  );
}

/** What a dataset carries besides its points: the PK the source reports, how a figure was digitized, and its flags. */
function DatasetNotes({ d }: { d: Listed }) {
  return (
    <>
      {!d.blinded && d.reported.length > 0 && <div className="series">{d.reported.map((r) => `${pkParamText(r.parameter)} ${r.value} ${r.unit}`).join(" · ")}</div>}
      {d.digitization && (
        <p className="muted m-4-0 fs-12">
          digitized from p.{d.digitization.page}{d.digitization.crop ? ", cropped to the figure" : ""}; resolution ±{(d.digitization.resolution.x / 2).toPrecision(2)} {d.time_unit},
          ±{(d.digitization.resolution.y / 2).toPrecision(2)} {d.unit}; overlay {d.digitization.overlay_approved_by ? `checked by ${d.digitization.overlay_approved_by}` : "not checked yet"}
        </p>
      )}
      {d.flags.length > 0 && <ul className="flags">{d.flags.map((f) => <li key={f}>{datasetFlagText(f)}</li>)}</ul>}
    </>
  );
}

/** "The overlay matches the figure": a digitized figure's points count once a person has checked its overlay (D-27). */
function Overlay({ d, name, projectId, run, onProblem, small = false }: {
  d: Listed; name: string; projectId: string; run: Run; onProblem: (p: string | null) => void;
  /** on a study's card, where the card's own confirmation is the one primary button */
  small?: boolean;
}) {
  if (!d.digitization || d.digitization.overlay_approved_by || d.state === "REJECTED") return null;
  return (
    <button className={small ? "btn small" : "btn primary"} data-testid={`overlay-${d.id}`}
            aria-label={`The overlay matches the figure: ${name}`}
            onClick={async () => onProblem(await run(() => send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:overlay",
                                                                { project_id: projectId, dataset_id: d.id }),
                                                    `${String(d.study.study_id)}: the overlay is checked; the study is used.`, MODEL))}>
      The overlay matches the figure
    </button>
  );
}

/** A dataset on its study's card: one line with where it stands, whether the data plan promised it, and Leave out; its
 *  points under "Show the points", with what the source reports and how a figure was digitized. Everything the dataset
 *  list offers is here too: a blinded dataset is revealed for a check, a digitized figure's overlay is checked. */
function DatasetLine({ d: listed, name, projectId, run, unpromised, said = null }: {
  d: Listed; name: string; projectId: string; run: Run; unpromised: string | null; said?: string | null;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const [points, setPoints] = useState(false);
  const [revealed, setRevealed] = useState<Listed | null>(null);
  const d = revealed ?? listed;
  const [tone, label] = standing(d);
  const s = d.study;
  const more = d.series.length > 0 || d.reported.length > 0 || Boolean(d.digitization) || d.flags.length > 0;
  return (
    <li className="evidence dataset-line" data-testid={`dataset-${d.id}`}>
      <div className="dataset-line-head">
        <span className={`chip ${ORIGIN_CHIP[d.origin] ?? "neutral"}`}>{originWord(d.origin)}</span>
        <span>{datasetHolds(d)} · {datasetSource(d)}</span>
        <span className={`chip ${tone}`} data-testid={`dataset-state-${d.id}`}>{label}</span>
        {unpromised && <span className="chip neutral" data-testid={`dataset-unpromised-${d.id}`} title={unpromisedText(unpromised)}>not in the data plan</span>}
        {d.blinded && <span className="chip neutral" data-testid={`dataset-blinded-${d.id}`} aria-describedby={`blinded-why-line-${d.id}`}>blinded until
          the plan is signed</span>}
        {!d.blinded && more && (
          <button type="button" className="link-btn" aria-expanded={points} onClick={() => setPoints(!points)}
                  aria-label={`${points ? "Hide" : "Show"} the ${d.series.length ? "points" : "details"} of ${name}`}>
            {points ? "Hide" : "Show"} the {d.series.length ? "points" : "details"}</button>
        )}
        <Overlay d={d} name={name} projectId={projectId} run={run} onProblem={setProblem} small />
        <LeaveOut d={d} name={name} projectId={projectId} run={run} onProblem={setProblem} />
      </div>
      {d.blinded && <Reveal d={d} name={name} projectId={projectId} onRevealed={(x) => { setRevealed(x); setPoints(true); }} onProblem={setProblem} said={said}
                            compact />}
      {!d.blinded && points && d.series.map((series) => (
        <div key={series.name} className="series">
          <span className="muted">{series.name} ({series.statistic ? valueWord(series.statistic) : ""}{series.n ? `, n ${series.n}` : ""}) · {d.time_unit} → {d.unit}:</span>{" "}
          {series.times.map((t, i) => `${+t.toPrecision(4)}: ${series.values[i] === null ? "<LLOQ" : +(series.values[i] as number).toPrecision(4)}`).join(" · ")}
        </div>
      ))}
      {(points || d.blinded) && <DatasetNotes d={d} />}
      {!points && !d.blinded && d.digitization && !d.digitization.overlay_approved_by && (
        <p className="muted m-0 fs-12">A digitized figure: its points count once you have checked the overlay against the figure.</p>
      )}
      {d.state === "REJECTED" && d.decision_reason && <p className="muted m-0 fs-12">left out by {d.decided_by}: {d.decision_reason}</p>}
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      <span className="sr-only">{String(s.study_id)}</span>
    </li>
  );
}

function DatasetCard({ d: listed, name, projectId, run, unpromised }: {
  d: Listed; name: string; projectId: string; run: Run; unpromised: string | null;
}) {
  const [revealed, setRevealed] = useState<Listed | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const d = revealed ?? listed;
  const s = d.study;
  const [tone, label] = standing(d);
  const out = d.state === "REJECTED";
  return (
    <div className={`evidence ${out ? "rejected" : "proposed"}`} data-testid={`dataset-${d.id}`}>
      <div className="spread">
        <div className="row">
          <strong>{String(s.study_id)}</strong>
          <span className={`chip ${ORIGIN_CHIP[d.origin] ?? "neutral"}`}>{originWord(d.origin)}</span>
          <span className="chip neutral">{d.kind === "profile" ? "profile" : "PK parameters only"}</span>
          <span className={`chip ${tone}`} data-testid={`dataset-state-${d.id}`}>{label}</span>
          {unpromised && <span className="chip neutral" data-testid={`dataset-unpromised-${d.id}`} title={unpromisedText(unpromised)}>not in the data plan</span>}
        </div>
        <span className="muted">{d.purpose.replace(/_/g, " ")}</span>
      </div>
      <p className="muted m-4-0 fs-13">
        {datasetHolds(d)} · {lowerFirst(valueWord(String(s.route)))} · {String(s.dose_mg)} mg{s.formulation ? ` · ${lowerFirst(valueWord(String(s.formulation)))}` : ""}
        {" · "}{lowerFirst(valueWord(String(s.food_state ?? "fasted")))} · n {String(s.n)} · {datasetSource(d)}
      </p>
      {d.blinded && <Reveal d={d} name={name} projectId={projectId} onRevealed={setRevealed} onProblem={setProblem} />}
      {!d.blinded && d.series.map((series) => (
        <div key={series.name} className="series">
          <span className="muted">{series.name} ({series.statistic ? valueWord(series.statistic) : ""}{series.n ? `, n ${series.n}` : ""}) · {d.time_unit} → {d.unit}:</span>{" "}
          {series.times.map((t, i) => `${+t.toPrecision(4)}: ${series.values[i] === null ? "<LLOQ" : +(series.values[i] as number).toPrecision(4)}`).join(" · ")}
        </div>
      ))}
      <DatasetNotes d={d} />
      {out && d.decision_reason && <p className="muted m-0 fs-12">left out by {d.decided_by}: {d.decision_reason}</p>}
      <div className="row mt-6">
        <Overlay d={d} name={name} projectId={projectId} run={run} onProblem={setProblem} />
        <LeaveOut d={d} name={name} projectId={projectId} run={run} onProblem={setProblem} />
      </div>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </div>
  );
}

/** The project's datasets, as the dataset list reads them (one read, shared). */
export function useDatasets(projectId: string): Listed[] | null {
  const page = useResource("/api/v1/projects/{project_id}/evidence", { project_id: projectId },
    { select: (d) => narrow<View>(d), poll: (d) => d.running, interval: 4000 });
  return page.data?.datasets ?? null;
}

/** The datasets of one study (by its names, as a dataset's `study_id` says them), read from the project's datasets. */
export function useStudyDatasets(projectId: string, study: (studyId: string) => boolean): Listed[] | null {
  const all = useDatasets(projectId);
  return all ? all.filter((d) => study(String(d.study.study_id))) : null;
}

/** What waits for a person among a study's datasets, said on its row while its card is closed: "1 blinded · 1 overlay
 *  to check". */
export const datasetsWaiting = (datasets: Listed[]) => [
  datasets.filter((d) => d.blinded).length ? `${datasets.filter((d) => d.blinded).length} blinded` : "",
  datasets.filter((d) => standing(d)[1] === "overlay to check").length ? `${datasets.filter((d) => standing(d)[1] === "overlay to check").length} overlay to check` : "",
].filter(Boolean).join(" · ");

/** The datasets of one study, on its card (plan 2026-11-14 slice 3): one line each, with where it stands, whether the
 *  data plan promised it, Leave out and, where they apply, the reveal of a blinded dataset and the overlay check of a
 *  digitized figure. Nothing when the study has none. */
export function StudyDatasets({ datasets, projectId, run, unpromised = [], said = null }: {
  datasets: Listed[]; projectId: string; run: Run; unpromised?: string[];
  /** why the card says its study is blinded (`blindedWhy`): a dataset blinded for the same reason does not say it again */
  said?: string | null;
}) {
  if (!datasets.length) return null;
  const names = namesOf(datasets);
  return (
    <ul className="dataset-lines" data-testid="study-datasets">
      {datasets.map((d) => <DatasetLine key={d.id} d={d} name={names.get(d.id) ?? d.id} projectId={projectId} run={run} said={said}
                                        unpromised={unpromisedOf(d, unpromised)} />)}
    </ul>
  );
}

/** The observed datasets on no study card (the literature, a digitized figure, a typed table, the published model, the
 *  observed-data agent), with their values, their source and where they stand; a digitized figure is used once its
 *  overlay is checked. The digitizer and the observed-data agent (only while AI is on) are here too. `except`: the
 *  datasets shown on a study card. */
export function ObservedDatasets({ projectId, run, digitize, except, unpromised = [] }: {
  projectId: string; run: Run;
  /** set (a new time each choice) when the head's "Add data" asks for the digitizer */
  digitize?: number;
  except?: (studyId: string) => boolean;
  unpromised?: string[];
}) {
  const page = useResource("/api/v1/projects/{project_id}/evidence", { project_id: projectId },
    { select: (d) => narrow<View>(d), poll: (d) => d.running, interval: 4000 });
  const documents = useResource("/api/v1/projects/{project_id}/documents", { project_id: projectId });
  // a figure the reading tray suggested opens the digitizer on its page (?digitize=<sha>&page=<n>; plan 2026-11-10, R5)
  const params = useSearchParams();
  const asked = params?.get("digitize");
  const initial = asked ? { sha: asked, page: Number(params?.get("page")) || 1, study: params?.get("study") ?? undefined } : undefined;
  const [digitizing, setDigitizing] = useState(Boolean(asked));
  useEffect(() => { if (asked) setDigitizing(true); }, [asked]);
  useEffect(() => {
    if (!digitize) return;
    setDigitizing(true);
    window.setTimeout(() => document.getElementById("observed-datasets")?.scrollIntoView({ block: "start", behavior: "smooth" }), 80);
  }, [digitize]);
  const view = page.data;
  const docs: DocumentView[] = documents.data?.documents ?? [];
  if (page.problem) return <InlineIssue severity="error">{page.problem}</InlineIssue>;
  if (!view) return <p className="muted">Loading the datasets…</p>;
  const datasets = except ? view.datasets.filter((d) => !except(String(d.study.study_id))) : view.datasets;
  return (
    <section className="observed" data-testid="observed-datasets">
      <div className="spread">
        <h3>Other observed data ({datasets.length})</h3>
        <div className="row">
          {/* the agent's button only while AI is on */}
          {view.agents.enabled && (
            <button type="button" className="btn" disabled={view.running} data-testid="find-observed"
                    onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence:research", { project_id: projectId },
                                                       undefined, { agent: "A3" }),
                                            "The observed-data agent is searching; datasets appear as it records them.", SEARCH)}>
              {view.running ? "Searching…" : "Find observed data with AI"}
            </button>
          )}
          <button type="button" className="btn" onClick={() => setDigitizing(!digitizing)} data-testid="open-digitizer">
            {digitizing ? "Close the digitizer" : "Digitize a figure"}
          </button>
        </div>
      </div>
      {digitizing && (
        <div className="card" data-testid="digitizer-card">
          {documents.data ? <Digitizer key={initial?.sha ?? "pick"} projectId={projectId} documents={docs} initial={initial}
                                       onSaved={() => setDigitizing(false)} />
            : <p className="muted">Loading the documents…</p>}
        </div>
      )}
      {datasets.length === 0 ? <p className="muted m-0">None: the literature, a digitized figure or a table typed in appear here; the
        client&apos;s studies are on their cards above.</p>
        : <DatasetList datasets={datasets} projectId={projectId} run={run} unpromised={unpromised} />}
    </section>
  );
}

/** The papers the literature agent found but could not read: storing the PDF lets it cite them (A2 access requests). */
export function AccessRequests({ projectId, run }: { projectId: string; run: Run }) {
  const page = useResource("/api/v1/projects/{project_id}/evidence", { project_id: projectId },
    { select: (d) => narrow<View>(d) });
  const requests = (page.data?.access_requests ?? []).filter((r) => r.status === "OPEN");
  if (!requests.length) return null;
  return (
    <section className="card" data-testid="access-requests">
      <h3 className="mt-0">Papers the literature agent could not read ({requests.length})</h3>
      <ul className="access-requests">
        {requests.map((r) => (
          <li key={r.id} data-testid={`access-${r.id}`}>
            <strong>{r.title}</strong>
            <span className="muted"> · {r.authors}{r.doi ? ` · doi ${r.doi}` : ""} · for {r.needed_for}</span>
            <label className="btn ml-8">
              Store the paper
              <input type="file" hidden accept=".pdf,.docx,.md,.txt" onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const form = new FormData();
                form.set("file", file);
                void run(() => upload("/api/v1/projects/{project_id}/access-requests/{request_id}:fulfil",
                                      { project_id: projectId, request_id: r.id }, form), "Paper stored; the agent can cite it now.", evidenceAfter(projectId));
              }} />
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}
