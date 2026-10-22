"use client";

import { useState } from "react";

import { Digitizer } from "@/components/evidence/Digitizer";
import { InlineIssue } from "@/components/kit";
import { narrow, send, upload, type Narrow, type Schema } from "@/lib/api";
import type { DocumentView } from "@/lib/brief";
import { useResource } from "@/lib/hooks";

import type { Run } from "./InputsTodo";

// a stored dataset (modeler_project.datasets.ObservedDataset), as the dataset routes answer it
type Dataset = Schema<"ObservedDataset">;
// a dataset as GET /projects/{id}/evidence lists it: for an external study before the MAP is signed (D-15) the
// redaction, its values withheld and marked `blinded`
type Listed = Narrow<Dataset, { reported: (Omit<Schema<"ReportedPK">, "value"> & { value: number | null })[] }> & { blinded?: boolean };
type AccessRequest = { id: string; title: string; authors: string; doi: string | null; needed_for: string; status: string };
type View = Narrow<Pick<Schema<"EvidencePage">, "agents" | "running" | "datasets" | "access_requests">, {
  datasets: Listed[]; access_requests: AccessRequest[];
}>;

const ORIGIN_CHIP: Record<string, string> = {
  CLIENT: "low", LITERATURE: "low", FIGURE_DIGITIZED: "medium", OSP_LIBRARY: "low", SYNTHETIC: "high", ILLUSTRATIVE: "high",
};

/** Where a dataset stands: used, left out with its reason, or a digitized figure waiting for its overlay check. */
function standing(d: Listed): [string, string] {
  if (d.state === "REJECTED") return ["neutral", "left out"];
  if (d.origin === "FIGURE_DIGITIZED" && d.state !== "ACCEPTED" && !d.digitization?.overlay_approved_by) return ["medium", "overlay to check"];
  return ["low", "used"];
}

function DatasetCard({ d: listed, projectId, run }: { d: Listed; projectId: string; run: Run }) {
  const [reason, setReason] = useState("");
  const [revealed, setRevealed] = useState<Listed | null>(null);
  const [revealReason, setRevealReason] = useState("");
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
          <span className={`chip ${ORIGIN_CHIP[d.origin] ?? "neutral"}`}>{d.origin.toLowerCase().replace("_", " ")}</span>
          <span className="chip neutral">{d.kind === "profile" ? "profile" : "PK parameters only"}</span>
          <span className={`chip ${tone}`} data-testid={`dataset-state-${d.id}`}>{label}</span>
        </div>
        <span className="muted">{d.purpose.replace(/_/g, " ")}</span>
      </div>
      <p className="muted" style={{ margin: "4px 0", fontSize: 13 }}>
        {String(s.route).replace("_", " ")} · {String(s.dose_mg)} mg · {String(s.formulation ?? "")} · {String(s.food_state ?? "fasted")} · n {String(s.n)}
        {" · "}{d.source.title || "source"}{d.source.locator ? ` · ${d.source.locator}` : ""}{d.source.page ? ` p.${d.source.page}` : ""}
      </p>
      {d.blinded && (
        <div className="banner warn" data-testid={`blinded-${d.id}`} style={{ margin: "6px 0" }}>
          External study: its values are blinded until the MAP is signed (D-15, ICH M15 §4.1). The metadata above is
          what the split uses. To check this dataset now, give the reason; the access is recorded in the audit trail.
          <div className="row" style={{ marginTop: 6 }}>
            <input style={{ flex: 1, minWidth: 180 }} placeholder="why it must be seen now (required)" value={revealReason}
                   onChange={(e) => setRevealReason(e.target.value)} aria-label={`why ${String(s.study_id)} must be seen now`} />
            <button className="btn" disabled={!revealReason.trim()} onClick={async () => {
              const env = await send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:reveal",
                                     { project_id: projectId, dataset_id: listed.id }, { reason: revealReason });
              if (env.data) { setRevealed(env.data as Listed); setProblem(null); } else setProblem(env.errors?.[0]?.message ?? "not revealed");
            }}>Reveal for this check</button>
          </div>
        </div>
      )}
      {!d.blinded && d.series.map((series) => (
        <div key={series.name} className="series">
          <span className="muted">{series.name} ({series.statistic?.replace("_", " ")}{series.n ? `, n ${series.n}` : ""}) · {d.time_unit} → {d.unit}:</span>{" "}
          {series.times.map((t, i) => `${+t.toPrecision(4)}: ${series.values[i] === null ? "<LLOQ" : +(series.values[i] as number).toPrecision(4)}`).join(" · ")}
        </div>
      ))}
      {!d.blinded && d.reported.length > 0 && <div className="series">{d.reported.map((r) => `${r.parameter} ${r.value} ${r.unit}`).join(" · ")}</div>}
      {d.digitization && (
        <p className="muted" style={{ margin: "4px 0", fontSize: 12 }}>
          digitized from p.{d.digitization.page}{d.digitization.crop ? ", cropped to the figure" : ""}; resolution ±{(d.digitization.resolution.x / 2).toPrecision(2)} {d.time_unit},
          ±{(d.digitization.resolution.y / 2).toPrecision(2)} {d.unit}; overlay {d.digitization.overlay_approved_by ? `checked by ${d.digitization.overlay_approved_by}` : "not checked yet"}
        </p>
      )}
      {d.flags.length > 0 && <ul className="flags">{d.flags.map((f) => <li key={f}>{f}</li>)}</ul>}
      {out && d.decision_reason && <p className="muted" style={{ margin: 0, fontSize: 12 }}>left out by {d.decided_by}: {d.decision_reason}</p>}
      <div className="row" style={{ marginTop: 6 }}>
        {d.digitization && !d.digitization.overlay_approved_by && !out && (
          <button className="btn primary" data-testid={`overlay-${d.id}`}
                  onClick={async () => setProblem(await run(() => send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:overlay",
                                                                       { project_id: projectId, dataset_id: d.id }),
                                                           `${String(s.study_id)}: the overlay is checked; the study is used.`))}>
            The overlay matches the figure
          </button>
        )}
        <input style={{ flex: 1, minWidth: 180 }} placeholder={out ? "why use it again" : "why leave it out"} value={reason}
               onChange={(e) => setReason(e.target.value)} aria-label={`reason for dataset ${String(s.study_id)}`} />
        <button className="btn" disabled={!reason.trim()} data-testid={`dataset-exclude-${d.id}`}
                onClick={async () => setProblem(await run(() => send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:decide",
                                                                     { project_id: projectId, dataset_id: d.id },
                                                                     { state: out ? "PROPOSED" : "REJECTED", reason }),
                                                          out ? `${String(s.study_id)} is used again.` : `${String(s.study_id)} is left out: ${reason}.`))}>
          {out ? "Use it again" : "Leave it out"}
        </button>
      </div>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </div>
  );
}

/** Every observed dataset, however it arrived (the client's sheets, the literature agent, a digitized figure, a typed
 *  table, the published model), with its values, its source and where it stands; a digitized figure is used once its
 *  overlay is checked. The digitizer and the observed-data agent are here too (redesign §3.2, the Studies tab). */
export function ObservedDatasets({ projectId, run }: { projectId: string; run: Run }) {
  const page = useResource("/api/v1/projects/{project_id}/evidence", { project_id: projectId },
    { select: (d) => narrow<View>(d), poll: (d) => d.running, interval: 4000 });
  const documents = useResource("/api/v1/projects/{project_id}/documents", { project_id: projectId });
  const [digitizing, setDigitizing] = useState(false);
  const view = page.data;
  const docs: DocumentView[] = documents.data?.documents ?? [];
  if (page.problem) return <InlineIssue severity="error">{page.problem}</InlineIssue>;
  if (!view) return <p className="muted">Loading the datasets…</p>;
  return (
    <section className="observed" data-testid="observed-datasets">
      <div className="spread">
        <h3>Every dataset ({view.datasets.length})</h3>
        <div className="row">
          <button type="button" className="btn" disabled={!view.agents.enabled || view.running} data-testid="find-observed"
                  title={view.agents.enabled ? undefined : "agents are off: add data from the client's files, a figure or a typed table"}
                  onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence:research", { project_id: projectId },
                                                     undefined, { agent: "A3" }),
                                          "The observed-data agent is searching; datasets appear as it records them.")}>
            {view.running ? "Searching…" : "Find observed data (agent)"}
          </button>
          <button type="button" className="btn" onClick={() => setDigitizing(!digitizing)} data-testid="open-digitizer">
            {digitizing ? "Close the digitizer" : "Digitize a figure"}
          </button>
        </div>
      </div>
      {digitizing && (
        <div className="card" data-testid="digitizer-card">
          <Digitizer projectId={projectId} documents={docs} onSaved={() => setDigitizing(false)} />
        </div>
      )}
      {view.datasets.length === 0 ? <p className="muted" style={{ margin: 0 }}>No observed data yet.</p>
        : view.datasets.map((d) => <DatasetCard key={d.id} d={d} projectId={projectId} run={run} />)}
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
      <h3 style={{ marginTop: 0 }}>Papers the literature agent could not read ({requests.length})</h3>
      <ul className="access-requests">
        {requests.map((r) => (
          <li key={r.id} data-testid={`access-${r.id}`}>
            <strong>{r.title}</strong>
            <span className="muted"> · {r.authors}{r.doi ? ` · doi ${r.doi}` : ""} · for {r.needed_for}</span>
            <label className="btn" style={{ marginLeft: 8 }}>
              Store the paper
              <input type="file" hidden accept=".pdf,.docx,.md,.txt" onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const form = new FormData();
                form.set("file", file);
                void run(() => upload("/api/v1/projects/{project_id}/access-requests/{request_id}:fulfil",
                                      { project_id: projectId, request_id: r.id }, form), "Paper stored; the agent can cite it now.");
              }} />
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}
