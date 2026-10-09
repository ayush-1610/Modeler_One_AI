"use client";

import { useState } from "react";

import { D3Dag, STUDY_MIME, StudyChip } from "@/components/plan/D3Dag";
import { D1Disposition, D2Absorption } from "@/components/plan/Diagrams";
import { Card } from "@/components/ui";
import type { Envelope, Schema } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";
import { ROLE_LABEL, planApi, type DiffRow, type PlanView, type Role, type Violation } from "@/lib/plan";
import { startCampaign } from "@/lib/writes";

type Pending = { studyId: string; from: Role; to: Role; where: string; preview: Violation[] | null; problem: string | null;
                 deviation?: boolean };
const TABS = ["D3 · development and validation", "D1 · disposition", "D2 · absorption and formulation"] as const;

function DropDialog({ pending, onConfirm, onCancel }: { pending: Pending; onConfirm: (reason: string) => Promise<string | null>; onCancel: () => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mine = (pending.preview ?? []).filter((v) => v.target === pending.studyId || !["error"].includes(v.severity));
  const errors = mine.filter((v) => v.severity === "error");
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Confirm the move" data-testid="drop-dialog">
      <div className="dialog">
        <h3 style={{ marginTop: 0 }}>{pending.studyId}: {ROLE_LABEL[pending.from]} → {ROLE_LABEL[pending.to]}</h3>
        <p className="muted" style={{ marginTop: 0 }}>Dropped on {pending.where}. The validator&apos;s answer for this move:</p>
        {pending.problem && <div className="banner err">{pending.problem}</div>}
        {pending.deviation && (
          <div className="banner warn" data-testid="move-deviation">The MAP is signed: this move is a MAP deviation (D-14). It is
            recorded and applies only once the MIDD lead signs it into a new MAP version.</div>
        )}
        {pending.preview === null && !pending.problem && <p className="muted">checking…</p>}
        {pending.preview !== null && (errors.length === 0
          ? <div className="banner ok" data-testid="move-ok">No MS-01 rule is broken by this move.</div>
          : <ul className="flags" data-testid="move-errors">{errors.map((v) => <li key={v.id}>{v.message}</li>)}</ul>)}
        {pending.preview && mine.filter((v) => v.severity === "warning" && !v.acknowledged).length > 0 && (
          <ul className="flags warn">{mine.filter((v) => v.severity === "warning" && !v.acknowledged).map((v) => <li key={v.id}>{v.message}</li>)}</ul>
        )}
        <label className="muted" style={{ fontSize: 13 }}>Why (at least one sentence; it goes into the MAP)</label>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} style={{ width: "100%" }} data-testid="move-reason" />
        {error && <div className="banner err">{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn primary" disabled={reason.trim().length < 8} data-testid="move-confirm"
                  onClick={async () => setError(await onConfirm(reason))}>
            {errors.length ? "Place it anyway (blocks signing)" : "Place it"}
          </button>
        </div>
      </div>
    </div>
  );
}

function DiffView({ rows, onDecide }: { rows: DiffRow[]; onDecide: (id: string, accept: boolean, reason: string) => Promise<string | null> }) {
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  if (!rows.length) return <p className="muted" style={{ margin: 0 }} data-testid="diff-empty">The plan is the MS-01 default: no departure.</p>;
  return (
    <>
      <table data-testid="diff">
        <thead><tr><th>Change</th><th>MS-01 default</th><th>Plan</th><th>By · why</th><th /></tr></thead>
        <tbody>
          {rows.map((d, i) => (
            <tr key={`${d.kind}-${d.target}-${i}`} className={d.status === "PENDING" ? "pending" : ""} data-testid={`diff-${d.target}`}>
              <td><span className="chip neutral">{d.kind}</span> <code>{d.target}</code></td>
              <td className="diff-from">{String(d.from)}</td>
              <td className="diff-to">{String(d.to)}</td>
              <td style={{ fontSize: 13 }}>{d.by}{d.status === "PENDING" ? " (proposed)" : ""}<div className="muted">{d.reason}</div></td>
              <td>
                {d.status === "PENDING" && d.proposal ? (
                  <div className="row" style={{ gap: 4 }}>
                    <input placeholder="why" value={reasons[d.proposal] ?? ""} style={{ width: 120 }}
                           onChange={(e) => setReasons({ ...reasons, [d.proposal as string]: e.target.value })} />
                    <button className="btn tiny" disabled={!reasons[d.proposal]?.trim()}
                            onClick={async () => setError(await onDecide(d.proposal as string, true, reasons[d.proposal as string]))}>Accept</button>
                    <button className="btn tiny" disabled={!reasons[d.proposal]?.trim()}
                            onClick={async () => setError(await onDecide(d.proposal as string, false, reasons[d.proposal as string]))}>Reject</button>
                  </div>
                ) : <span className="chip low">applied</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <div className="banner err">{error}</div>}
    </>
  );
}

function ValidatorPanel({ view, onAcknowledge }: { view: PlanView; onAcknowledge: (id: string, reason: string) => Promise<string | null> }) {
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const open = view.violations.filter((v) => v.severity === "error" || !v.acknowledged);
  const done = view.violations.filter((v) => v.severity === "warning" && v.acknowledged);
  return (
    <div data-testid="validator">
      {open.length === 0 ? <div className="banner ok" data-testid="validator-green">Green: no open MS-01 rule violation.</div> : (
        <ul className="violations">
          {open.map((v) => (
            <li key={v.id} className={v.severity} data-testid={`violation-${v.id}`}>
              <span className={`chip ${v.severity === "error" ? "high" : "medium"}`}>{v.severity}</span> {v.message}
              {v.severity === "warning" && (
                <span className="row" style={{ gap: 4, marginTop: 4 }}>
                  <input placeholder="accept it because…" value={reasons[v.id] ?? ""} style={{ flex: 1 }}
                         onChange={(e) => setReasons({ ...reasons, [v.id]: e.target.value })} />
                  <button className="btn tiny" disabled={!reasons[v.id]?.trim()}
                          onClick={async () => setError(await onAcknowledge(v.id, reasons[v.id]))}>Acknowledge</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {done.length > 0 && <p className="muted" style={{ fontSize: 12 }}>Acknowledged (they become MAP limitations): {done.map((v) => v.message).join(" · ")}</p>}
      {error && <div className="banner err">{error}</div>}
    </div>
  );
}

/** D-15: whether external values are blinded, and the MIDD lead's switch (with its reason, on the audit chain). */
function BlindingPanel({ projectId }: { projectId: string }) {
  const { data: state } = useResource("/api/v1/projects/{project_id}/blinding", { project_id: projectId });
  const { run } = useMutation();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  if (!state) return null;
  return (
    <div data-testid="blinding" style={{ fontSize: 12 }}>
      <h3>Blinding (D-15)</h3>
      <p className="muted" style={{ margin: "0 0 4px" }}>
        {state.map_signed ? "Lifted: the MAP is signed." : state.on
          ? `On — ${state.blinded.length} external stud${state.blinded.length === 1 ? "y's" : "ies'"} values withheld until the MAP is signed.`
          : "Off — external values are visible."} <span className="muted">({state.source}{state.reason ? `: ${state.reason}` : ""})</span>
      </p>
      {!state.map_signed && (
        <div className="row" style={{ gap: 4 }}>
          <input placeholder="reason (MIDD lead)" value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1, minWidth: 100 }} />
          <button className="btn tiny" disabled={!reason.trim()} data-testid="blinding-toggle" onClick={async () => {
            const { problem } = await run(() => planApi.setBlinding(projectId, !state.on, reason));
            if (!problem) setReason("");
            setError(problem);
          }}>{state.on ? "Turn off" : "Turn on"}</button>
        </div>
      )}
      {error && <div className="banner err" style={{ marginTop: 4 }}>{error}</div>}
    </div>
  );
}

/** P5 model plan (plan §11, review layer L3): the three diagrams, "Overall Data", the diff, the validator, the signature. */
export function PlanCanvas({ projectId }: { projectId: string }) {
  const page = useResource("/api/v1/projects/{project_id}/plan", { project_id: projectId }, { poll: (d) => d.running });
  const mutation = useMutation();
  const [tab, setTab] = useState<(typeof TABS)[number]>(TABS[0]);
  const [pending, setPending] = useState<Pending | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [signature, setSignature] = useState<Schema<"SignatureView"> | null>(null);
  const view = page.data;

  if (page.problem) return <div className="banner err" data-testid="plan-problem">{page.problem}</div>;
  if (!view) return <p className="muted">Computing the MS-01 default plan…</p>;

  // a change to the plan, then the plan and the phase rail read again; answers the API's reason when it refused
  const apply = async <T,>(call: () => Promise<Envelope<T>>, ok?: string) => {
    const { problem } = await mutation.run(call);
    if (!problem && ok) setMessage(ok);
    return problem;
  };
  const onDrop = async (studyId: string, role: Role, where: string) => {
    const from = view.overall_data.studies.find((s) => s.study_id === studyId)?.role ?? "SUPPORTIVE";
    setPending({ studyId, from, to: role, where, preview: null, problem: null });
    // the dry run saves nothing, so it is a plain call, not a change
    const env = await planApi.place(projectId, studyId, role, "preview of the move", true);
    const preview = env.data && "deviation" in env.data ? env.data : null;
    setPending((p) => p && p.studyId === studyId ? { ...p, preview: preview?.violations ?? null, problem: env.errors?.[0]?.message ?? null,
                                                      deviation: preview?.deviation ?? false } : p);
  };
  const stale = view.artifact.status === "STALE";
  const signed = view.signed ?? view.map?.status === "APPROVED";
  const pendingDeviations = (view.deviations ?? []).filter((d) => !d.signature_id);
  // before the first signature: sign the plan; after it: sign the deviations (D-14), nothing else to sign
  const canSign = view.blocking === 0 && !stale && (!signed || pendingDeviations.length > 0);
  const studies = view.overall_data.studies;

  return (
    <div className="plan-layout">
      <aside className="overall-data" data-testid="overall-data" aria-label="Overall Data"
             onDragOver={(e) => { if (e.dataTransfer.types.includes(STUDY_MIME)) e.preventDefault(); }}>
        <h2>Overall Data</h2>
        <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>CPF v1 and the study catalog. Drag a dataset onto a D3 node, an arrow or the training layer.</p>
        <h3>Datasets ({studies.length})</h3>
        {studies.map((s) => (
          <div key={s.study_id} className="overall-study">
            <StudyChip s={s} view={view} />
            <div className="muted" style={{ fontSize: 11 }}>{s.route.replace("_", " ")} · {s.dose_mg} mg · {s.food_state} · {s.design} · n {s.n} → {s.role}</div>
          </div>
        ))}
        <BlindingPanel projectId={projectId} />
        <h3>Dissolution</h3>
        {view.d2.dissolution.length ? view.d2.dissolution.map((d) => <div key={d.id} className="muted" style={{ fontSize: 12 }}>◆ {d.label}</div>)
          : <p className="muted" style={{ fontSize: 12 }}>none</p>}
        <h3>CPF v1 ({view.overall_data.parameters.length})</h3>
        <ul className="param-list">
          {view.overall_data.parameters.map((p) => (
            <li key={p.id}><code>{p.id}</code> {typeof p.value === "number" ? +p.value.toPrecision(4) : String(p.value)} {p.unit ?? ""}</li>
          ))}
        </ul>
      </aside>
      <section className="plan-main">
        <Card title={`Model plan v${view.artifact.version} · ${view.plan.compound}`}
              action={<span className={`chip ${view.blocking ? "high" : "low"}`} data-testid="blocking-chip">
                {view.blocking ? `${view.blocking} open violation${view.blocking === 1 ? "" : "s"}` : "validator green"}</span>}>
          {stale && (
            <div className="banner warn" data-testid="plan-stale">
              The inputs changed since this plan ({view.artifact.stale_reasons.join("; ")}).
              <button className="btn tiny" style={{ marginLeft: 8 }} onClick={() => apply(() => planApi.rebase(projectId), "Plan brought up to date; your choices kept.")}>
                Bring it up to date</button>
            </div>
          )}
          <p className="muted" style={{ margin: "0 0 8px", fontSize: 13 }}>
            {view.plan.structure.objective} · {view.plan.structure.context_of_use} · model risk {view.plan.structure.model_risk}
          </p>
          <div className="row">
            <button className="btn" disabled={!view.agents.enabled || view.running || signed}
                    onClick={async () => setMessage(await apply(() => planApi.draft(projectId)) ?? "A5 is drafting the rationale; proposals appear in the diff.")}>
              Draft with A5</button>
            <input placeholder="signature note" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1, minWidth: 140 }} />
            <button className="btn primary" disabled={!canSign} data-testid="approve-and-sign"
                    title={canSign ? "generate the MAP from this plan and sign it (MIDD lead)"
                      : signed ? "the MAP is signed; a change now is a deviation to sign" : "resolve or acknowledge every violation first"}
                    onClick={async () => {
                      const done = pendingDeviations.length
                        ? `Deviations signed: MAP v${(view.map?.map_version ?? 1) + 1} supersedes v${view.map?.map_version ?? 1}.`
                        : "MAP generated from the plan and signed.";
                      const { data, problem } = await mutation.run(() => planApi.sign(projectId, note));
                      if (data) setSignature(data.signature);
                      setMessage(problem ?? done);
                    }}>
              {signed && pendingDeviations.length ? `Sign the deviation${pendingDeviations.length === 1 ? "" : "s"} (${pendingDeviations.length})` : "Approve and Sign"}</button>
            {signed && view.map && !pendingDeviations.length && (
              <button className="btn" data-testid="run-campaign" onClick={async () => {
                // the MAP artifact's staged campaign inputs (stored content), the body a campaign starts from
                const started = await startCampaign(projectId, view.map!.campaign as Parameters<typeof startCampaign>[1]);
                if (started.campaign_id) window.location.assign(`/campaigns/${started.campaign_id}`);
                else setMessage(`The campaign did not start: ${started.error ?? "no campaign id returned"}`);
              }}>Run the campaign (P6)</button>
            )}
          </div>
          {signed && <p className="muted" style={{ fontSize: 13 }} data-testid="map-signed">MAP v{view.map?.map_version ?? view.map?.version} signed{signature ? `: ${signature.manifestation}` : ""} · {view.map?.map_sha256.slice(0, 12)}{view.map?.supersedes ? " · supersedes the earlier version" : ""}</p>}
          {signed && pendingDeviations.length > 0 && (
            <div className="banner warn" data-testid="deviations-pending" style={{ marginTop: 8 }}>
              <strong>MAP deviations pending signature (D-14, ICH M15 §4.2).</strong> They apply to campaigns once the MIDD
              lead signs them into a new MAP version; until then the signed MAP stands.
              <ul className="plain" style={{ marginTop: 6 }}>
                {pendingDeviations.map((d, i) => <li key={i}><code>{d.target}</code> {d.change} — {d.reason}</li>)}
              </ul>
            </div>
          )}
          {signed && !pendingDeviations.length && (
            <p className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>A change now is a MAP deviation: it is recorded and
              waits for the MIDD lead&apos;s signature.</p>
          )}
          {message && <div className="banner ok" style={{ marginTop: 8 }}>{message}</div>}
        </Card>
        <nav className="tabs" aria-label="Diagrams">
          {TABS.map((t) => <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t}</button>)}
        </nav>
        <Card title={tab}>
          {tab === TABS[0] && <D3Dag view={view} onDrop={onDrop}
                                     onLayout={(layout) => void apply(() => planApi.layout(projectId, layout))} />}
          {tab === TABS[1] && <D1Disposition view={view} onFit={(pid, fit) => apply(() => planApi.fit(projectId, pid, fit))}
                                             onUnfit={(pid, reason) => apply(() => planApi.unfit(projectId, pid, reason))} />}
          {tab === TABS[2] && <D2Absorption view={view} onFit={(pid, fit) => apply(() => planApi.fit(projectId, pid, fit))}
                                            onUnfit={(pid, reason) => apply(() => planApi.unfit(projectId, pid, reason))}
                                            onStructure={(key, value, reason) => apply(() => planApi.structure(projectId, key, value, reason))} />}
        </Card>
        <div className="cols-2">
          <Card title="Live validator (MS-01)">
            <ValidatorPanel view={view} onAcknowledge={(id, reason) => apply(() => planApi.acknowledge(projectId, id, reason))} />
          </Card>
          <Card title="Changes from the MS-01 default">
            <DiffView rows={view.diff} onDecide={(id, accept, reason) => apply(() => planApi.decide(projectId, id, accept, reason))} />
            {view.plan.default_rationale.length > 0 && (
              <details style={{ marginTop: 8 }}><summary className="muted">MS-01 split rationale and limitations</summary>
                <ul className="flags">{[...view.plan.default_rationale, ...view.plan.default_limitations].map((r) => <li key={r}>{r}</li>)}</ul>
              </details>
            )}
          </Card>
        </div>
      </section>
      {pending && (
        <DropDialog pending={pending} onCancel={() => setPending(null)}
                    onConfirm={async (reason) => {
                      const error = await apply(() => planApi.place(projectId, pending.studyId, pending.to, reason));
                      if (!error) setPending(null);
                      return error;
                    }} />
      )}
    </div>
  );
}
