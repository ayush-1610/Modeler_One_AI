"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { Card } from "@/components/ui";
import { get, narrow, send, type Envelope, type Narrow, type Schema } from "@/lib/api";

type Item = {
  req_id: string;
  label: string;
  kind: string;
  target: string;
  group: string;
  template: string;
  pksim: Record<string, string> | null;
  pksim_status: "HARVESTED" | "TO_HARVEST" | "NOT_APPLICABLE";
  unit: string | null;
  criticality: "REQUIRED" | "CONDITIONAL" | "OPTIONAL";
  applies: "yes" | "no" | "undetermined";
  condition_text: string;
  needed_for: string[];
  data_category: string;
  provider: string;
  provider_source: string;
  provider_statement: string;
  purpose: string | null;
  due_date: string | null;
  cross_check: boolean;
  conditions: string[];
  plausibility: string;
  product: string | null;
  note: string;
  status: string;
};

type FeasibilityLine = { feature: string; needed_because: string; status: string; route: string };

// GET /projects/{id}/requirements (RequirementsPage); the stored matrix and feasibility report are typed here
type PlanView = Narrow<Schema<"RequirementsPage">, {
  matrix: { templates: string[]; items: Item[]; overrides: { req_id: string; reason: string; by: string }[]; notes: string[] };
  feasibility: { lines: FeasibilityLine[]; blocking?: number; undetermined?: number; status: string | null };
}>;

type Provider = NonNullable<Schema<"OverrideRequest">["provider"]>;
const PROVIDERS: Provider[] = ["CLIENT", "LITERATURE", "SPONSOR_TO_MEASURE", "PREDICT", "STRUCTURE", "LIBRARY", "STUDY", "PROPOSAL",
                               "NOT_NEEDED"];
const FEAS_CHIP: Record<string, string> = {
  SUPPORTED: "low", LIMITED: "medium", NEEDS_HARVEST: "high", NOT_SUPPORTED: "high", UNDETERMINED: "neutral",
};

/** The P1 data plan: every PK-Sim input and dataset the project needs, who provides it, and for what (plan §7). */
export function DataPlan({ projectId, view: tab }: { projectId: string; view: "plan" | "feasibility" }) {
  const [data, setData] = useState<PlanView | null>(null);
  const [missing, setMissing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const env = await get("/api/v1/projects/{project_id}/requirements", { project_id: projectId });
    if (env.data) { setData(narrow<PlanView>(env.data)); setMissing(false); setProblem(null); }
    else if (env.errors?.[0]?.message?.includes("no data plan")) setMissing(true);
    else setProblem(env.errors?.[0]?.message ?? "The data plan could not be read.");
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  const groups = useMemo(() => {
    const out: Record<string, Item[]> = {};
    data?.matrix.items.filter((i) => showAll || i.applies !== "no").forEach((i) => { (out[i.group] ??= []).push(i); });
    return out;
  }, [data, showAll]);

  async function run(call: () => Promise<Envelope<Schema<"RequirementsPage">>>) {
    setBusy(true);
    const env = await call();
    setBusy(false);
    if (env.data) { setData(narrow<PlanView>(env.data)); setMissing(false); setProblem(null); }
    else setProblem(env.errors?.[0]?.message ?? "not saved");
  }

  async function override(item: Item, change: { provider?: Provider; cross_check?: boolean }) {
    const reason = window.prompt(`Why change ${item.label}?`);
    if (!reason) return;
    await run(() => send("put", "/api/v1/projects/{project_id}/requirements/{req_id}", { project_id: projectId, req_id: item.req_id },
                         { ...change, reason }));
  }

  if (problem) return <div className="banner err">{problem}</div>;
  if (missing) {
    return (
      <Card title="Data plan">
        <p className="muted">The data plan is derived from the brief: every PK-Sim input and observed dataset the project
          needs, with who provides it. It is derived automatically when the brief is approved, or now as a draft.</p>
        <button className="btn primary" disabled={busy} onClick={() => run(() => send("post", "/api/v1/projects/{project_id}/requirements:derive", { project_id: projectId }))}>
          Derive from the brief
        </button>
      </Card>
    );
  }
  if (!data) return <p className="muted">Loading the data plan…</p>;

  if (tab === "feasibility") {
    return (
      <Card title="Feasibility — what the PK-Sim builder can produce for this brief"
            action={<span className="muted">{data.feasibility.blocking ?? 0} blocking · {data.feasibility.undetermined ?? 0} undetermined</span>}>
        <table data-testid="feasibility">
          <thead><tr><th>Feature</th><th>Because</th><th>Status</th><th>Route to support</th></tr></thead>
          <tbody>
            {data.feasibility.lines.map((l, i) => (
              <tr key={i}>
                <td>{l.feature}</td>
                <td className="muted">{l.needed_because}</td>
                <td><span className={`chip ${FEAS_CHIP[l.status] ?? "neutral"}`}>{l.status.toLowerCase().replace("_", " ")}</span></td>
                <td className="muted">{l.route || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    );
  }

  const approved = data.artifact.status === "APPROVED";
  return (
    <>
      <Card>
        <div className="spread">
          <div>
            <h2 style={{ margin: 0 }}>Data plan · v{data.artifact.version}</h2>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              {data.counts.applicable} inputs needed · {Object.entries(data.counts.by_provider).map(([k, v]) => `${v} ${k.toLowerCase().replace(/_/g, " ")}`).join(", ")}
              {" · "}{data.counts.undetermined} undetermined · {data.counts.to_harvest} need a PK-Sim harvest
            </p>
            <p className="muted" style={{ margin: "4px 0 0", fontSize: 12 }}>Templates: {data.matrix.templates.join(" · ")}</p>
          </div>
          <div className="row">
            <label className="row" style={{ gap: 6, fontSize: 13 }}>
              <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> show not applicable
            </label>
            <button className="btn" disabled={busy} onClick={() => run(() => send("post", "/api/v1/projects/{project_id}/requirements:derive", { project_id: projectId }))}>Re-derive</button>
            <button className="btn primary" disabled={busy || approved || data.brief_status !== "APPROVED" || data.artifact.stale_reasons.length > 0}
                    title={data.brief_status !== "APPROVED" ? "approve the brief first" : ""}
                    onClick={() => run(() => send("post", "/api/v1/projects/{project_id}/requirements:approve", { project_id: projectId }, { note: "" }))}>
              {approved ? "Approved" : "Approve data plan"}
            </button>
          </div>
        </div>
        {data.artifact.stale_reasons.length > 0 && (
          <div className="banner warn" style={{ marginTop: 10 }}>Stale: {data.artifact.stale_reasons.join("; ")} — re-derive.</div>
        )}
      </Card>
      {Object.entries(groups).map(([group, items]) => (
        <Card key={group} title={group}>
          <div style={{ overflowX: "auto" }}>
            <table className="plan-table">
              <thead>
                <tr><th>Input</th><th>PK-Sim</th><th>Need</th><th>Provider</th><th>Purpose</th><th>Stages</th><th /></tr>
              </thead>
              <tbody>
                {items.map((i) => (
                  <Fragment key={i.req_id}>
                    <tr className={i.applies === "no" ? "na" : ""} data-testid={`req-${i.req_id}`}>
                      <td>
                        <strong>{i.label}</strong>
                        <div className="muted" style={{ fontSize: 12 }}><code>{i.target}</code>{i.unit ? ` · ${i.unit}` : ""}</div>
                        {i.conditions.length > 0 && <div className="muted" style={{ fontSize: 12 }}>record: {i.conditions.join(", ")}</div>}
                      </td>
                      <td style={{ fontSize: 12 }}>
                        {i.pksim ? <>{i.pksim.building_block}<div className="muted">{i.pksim.location}</div></> : null}
                        {i.pksim_status === "TO_HARVEST" && <span className="chip high">to harvest</span>}
                      </td>
                      <td>
                        <span className={`chip ${i.criticality === "REQUIRED" ? "high" : i.criticality === "CONDITIONAL" ? "medium" : "neutral"}`}>
                          {i.criticality.toLowerCase()}
                        </span>
                        {i.applies === "undetermined" && <div className="muted" style={{ fontSize: 12 }}>if {i.condition_text}</div>}
                        {i.applies === "no" && <div className="muted" style={{ fontSize: 12 }}>not applicable</div>}
                      </td>
                      <td>
                        <select value={i.provider} disabled={busy} onChange={(e) => override(i, { provider: e.target.value as Provider })}>
                          {PROVIDERS.map((p) => <option key={p} value={p}>{p.toLowerCase().replace(/_/g, " ")}</option>)}
                        </select>
                        <div className="muted" style={{ fontSize: 12 }} title={i.provider_statement}>
                          {i.provider_source === "override" ? "set by a person" : i.provider_source === "template default" ? "default" : `proposal: “${i.provider_statement}”`}
                        </div>
                        {i.provider === "CLIENT" && (
                          <label style={{ fontSize: 12 }}>
                            <input type="checkbox" checked={i.cross_check} disabled={busy}
                                   onChange={(e) => override(i, { cross_check: e.target.checked })} /> cross-check in the literature
                          </label>
                        )}
                      </td>
                      <td>{i.purpose?.replace(/_/g, " ") ?? "—"}</td>
                      <td className="muted">{i.needed_for.join(", ")}</td>
                      <td><span className="chip neutral">{i.status.toLowerCase()}</span></td>
                    </tr>
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </>
  );
}
