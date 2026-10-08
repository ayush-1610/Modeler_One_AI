"use client";

import { useState } from "react";

import { Digitizer } from "@/components/evidence/Digitizer";
import { Card } from "@/components/ui";
import { narrow, send, type Envelope, type Narrow, type Schema } from "@/lib/api";
import type { DocumentView } from "@/lib/brief";
import { useMutation, useResource } from "@/lib/hooks";

type Series = { name: string; statistic: string; times: number[]; values: (number | null)[]; error: number[] | null;
                error_kind: string; n: number | null };
type Dataset = {
  id: string; kind: "profile" | "pk_parameters"; study: Record<string, unknown>; analyte: string; matrix: string;
  time_unit: string; unit: string; series: Series[];
  reported: { parameter: string; value: number; unit: string; statistic: string }[];
  origin: string; extraction: string;
  source: { doc_sha256: string | null; page: number | null; locator: string; title: string; doi: string | null };
  digitization: { page: number; resolution: Record<string, number>; overlay_approved_by: string | null } | null;
  purpose: string; provider: string; flags: string[]; state: string; proposed_by: string; decided_by: string | null;
  decision_reason: string;
  blinded?: boolean;   // D-15: an external study's values, withheld until the MAP is signed
};
// the part of GET /projects/{id}/evidence (EvidencePage) this panel reads; the stored datasets are typed above
type View = Narrow<Pick<Schema<"EvidencePage">, "coverage" | "agents" | "running" | "datasets">, { datasets: Dataset[] }>;

const ORIGIN_CHIP: Record<string, string> = {
  CLIENT: "low", LITERATURE: "low", FIGURE_DIGITIZED: "medium", OSP_LIBRARY: "low", SYNTHETIC: "high", ILLUSTRATIVE: "high",
};

function DatasetCard({ d: listed, onDecide, onOverlay, onReveal }: {
  d: Dataset;
  onDecide: (d: Dataset, state: Schema<"Decision">["state"], reason: string) => Promise<string | null>;
  onOverlay: (d: Dataset) => Promise<string | null>;
  onReveal: (d: Dataset, reason: string) => Promise<Dataset | string>;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<Dataset | null>(null);
  const [revealReason, setRevealReason] = useState("");
  const d = revealed ?? listed;
  const s = d.study;
  return (
    <div className={`evidence ${d.state.toLowerCase()}`} data-testid={`dataset-${d.id}`}>
      <div className="spread">
        <div className="row">
          <strong>{String(s.study_id)}</strong>
          <span className={`chip ${ORIGIN_CHIP[d.origin] ?? "neutral"}`}>{d.origin.toLowerCase().replace("_", " ")}</span>
          <span className="chip neutral">{d.kind === "profile" ? "profile" : "PK parameters only"}</span>
          <span className={`chip ${d.state === "ACCEPTED" ? "low" : d.state === "REJECTED" ? "high" : "medium"}`}>{d.state.toLowerCase()}</span>
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
                   onChange={(e) => setRevealReason(e.target.value)} />
            <button className="btn" disabled={!revealReason.trim()} onClick={async () => {
              const out = await onReveal(listed, revealReason);
              if (typeof out === "string") setError(out); else { setRevealed(out); setError(null); }
            }}>Reveal for this check</button>
          </div>
        </div>
      )}
      {!d.blinded && d.series.map((series) => (
        <div key={series.name} className="series">
          <span className="muted">{series.name} ({series.statistic.replace("_", " ")}{series.n ? `, n ${series.n}` : ""}) · {d.time_unit} → {d.unit}:</span>{" "}
          {series.times.map((t, i) => `${+t.toPrecision(4)}: ${series.values[i] === null ? "<LLOQ" : +(series.values[i] as number).toPrecision(4)}`).join(" · ")}
        </div>
      ))}
      {!d.blinded && d.reported.length > 0 && <div className="series">{d.reported.map((r) => `${r.parameter} ${r.value} ${r.unit}`).join(" · ")}</div>}
      {d.digitization && (
        <p className="muted" style={{ margin: "4px 0", fontSize: 12 }}>
          digitized from p.{d.digitization.page}; resolution ±{(d.digitization.resolution.x / 2).toPrecision(2)} {d.time_unit},
          ±{(d.digitization.resolution.y / 2).toPrecision(2)} {d.unit}; overlay {d.digitization.overlay_approved_by ? `approved by ${d.digitization.overlay_approved_by}` : "not approved"}
        </p>
      )}
      {d.flags.length > 0 && <ul className="flags">{d.flags.map((f) => <li key={f}>{f}</li>)}</ul>}
      {d.decision_reason && <p className="muted" style={{ margin: 0, fontSize: 12 }}>{d.state.toLowerCase()} by {d.decided_by}: {d.decision_reason}</p>}
      <div className="row" style={{ marginTop: 6 }}>
        {d.digitization && !d.digitization.overlay_approved_by && (
          <button className="btn" onClick={async () => setError(await onOverlay(d))}>Approve the overlay</button>
        )}
        <input style={{ flex: 1, minWidth: 180 }} placeholder="reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="btn" disabled={!reason.trim()} onClick={async () => setError(await onDecide(d, "ACCEPTED", reason))}>Accept</button>
        <button className="btn" disabled={!reason.trim()} onClick={async () => setError(await onDecide(d, "REJECTED", reason))}>Reject</button>
      </div>
      {error && <div className="banner err" style={{ marginTop: 6 }}>{error}</div>}
    </div>
  );
}

/** P2 observed data (plan §9): clinical PK datasets with their origin, from tables, figures or by hand. */
export function ObservedData({ projectId }: { projectId: string }) {
  const page = useResource("/api/v1/projects/{project_id}/evidence", { project_id: projectId },
    { select: (d) => narrow<View>(d), poll: (d) => d.running, interval: 4000 });
  const documents = useResource("/api/v1/projects/{project_id}/documents", { project_id: projectId });
  const { run } = useMutation();
  const [digitizing, setDigitizing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const view = page.data;
  const docs: DocumentView[] = documents.data?.documents ?? [];

  if (page.problem) return <div className="banner err">{page.problem}</div>;
  if (!view) return <p className="muted">Loading…</p>;

  // a change, then the datasets read again; answers the API's reason when it refused
  const act = async <T,>(fn: () => Promise<Envelope<T>>): Promise<string | null> => (await run(fn)).problem;
  const needs = view.coverage.filter((c) => ["IV-SD", "PO-SOL-FASTED / PO-IR-FASTED", "PO-FED", "PO-MD", "EXTERNAL", "urine", "DDI",
                                               "SPECIAL", "lloq", "BE study"].includes(c.target));
  return (
    <>
      <Card title="Dataset needs of the data plan">
        <table>
          <tbody>
            {needs.map((n) => (
              <tr key={n.req_id}>
                <td>{n.label}</td>
                <td><span className={`chip ${n.status === "ACCEPTED" ? "low" : n.status === "PROPOSED" ? "medium" : n.status === "NOT_AVAILABLE" ? "neutral" : "high"}`}
                          data-testid={`need-${n.req_id}`}>{n.status.toLowerCase().replace("_", " ")}</span></td>
                <td className="muted">{n.criticality.toLowerCase()}{n.applies === "undetermined" ? " · if applicable" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" disabled={!view.agents.enabled || view.running}
                  onClick={async () => setNotice(await act(() => send("post", "/api/v1/projects/{project_id}/evidence:research", { project_id: projectId }, undefined, { agent: "A3" }))
                    ?? "The observed-data agent is searching; datasets appear as it records them.")}>
            Find observed data (agent)
          </button>
          <button className="btn" onClick={() => setDigitizing(!digitizing)} data-testid="open-digitizer">
            {digitizing ? "Close the digitizer" : "Digitize a figure"}
          </button>
        </div>
        {notice && <div className="banner ok" style={{ marginTop: 8 }}>{notice}</div>}
      </Card>
      {digitizing && (
        <Card title="Digitize a figure">
          <Digitizer projectId={projectId} documents={docs} onSaved={() => setDigitizing(false)} />
        </Card>
      )}
      <Card title={`Datasets (${view.datasets.length})`}>
        {view.datasets.length === 0 ? <p className="muted" style={{ margin: 0 }}>No observed data yet.</p> : view.datasets.map((d) => (
          <DatasetCard key={d.id} d={d}
                       onDecide={(ds, state, reason) => act(() => send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:decide",
                                                                        { project_id: projectId, dataset_id: ds.id }, { state, reason }))}
                       onOverlay={(ds) => act(() => send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:overlay", { project_id: projectId, dataset_id: ds.id }))}
                       onReveal={async (ds, reason) => {
                         const env = await send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:reveal",
                                                { project_id: projectId, dataset_id: ds.id }, { reason });
                         // the stored dataset, typed by this page (the API sends it as an open object)
                         return (env.data as Dataset | null) ?? env.errors?.[0]?.message ?? "not revealed";
                       }} />
        ))}
      </Card>
    </>
  );
}
