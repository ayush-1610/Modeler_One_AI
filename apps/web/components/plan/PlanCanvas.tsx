"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Banner, InlineIssue, PageShell, ReasonField, WaitingFor } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { D3Dag, STUDY_MIME, StudyChip } from "@/components/plan/D3Dag";
import { D1Disposition, D2Absorption } from "@/components/plan/Diagrams";
import { Credibility, StudiesTable } from "@/components/review/Credibility";
import { EstimationPlan } from "@/components/review/EstimationPlan";
import { ReviewTable } from "@/components/review/ReviewTable";
import { Applications } from "@/components/review/Applications";
import { ValidationPlan } from "@/components/review/ValidationPlan";
import { Card } from "@/components/ui";
import type { Envelope, Schema } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";
import { ROLE_LABEL, planApi, type DiffRow, type PlanView, type Role, type Violation } from "@/lib/plan";
import { celebrate, toast } from "@/components/kit/Motion";
import { StepBlocked } from "@/components/kit/StepBlocked";

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
        <h3 className="mt-0">{pending.studyId}: {ROLE_LABEL[pending.from]} → {ROLE_LABEL[pending.to]}</h3>
        <p className="muted mt-0">Dropped on {pending.where}. The validator&apos;s answer for this move:</p>
        {pending.problem && <Banner tone="err">{pending.problem}</Banner>}
        {pending.deviation && (
          <Banner tone="warn" testId="move-deviation">The MAP is signed: this move is a MAP deviation. It is
            recorded and applies only once the MIDD lead signs it into a new MAP version.</Banner>
        )}
        {pending.preview === null && !pending.problem && <p className="muted">checking…</p>}
        {pending.preview !== null && (errors.length === 0
          ? <Banner tone="ok" testId="move-ok">No MS-01 rule is broken by this move.</Banner>
          : <ul className="flags" data-testid="move-errors">{errors.map((v) => <li key={v.id}>{v.message}</li>)}</ul>)}
        {pending.preview && mine.filter((v) => v.severity === "warning" && !v.acknowledged).length > 0 && (
          <ul className="flags warn">{mine.filter((v) => v.severity === "warning" && !v.acknowledged).map((v) => <li key={v.id}>{v.message}</li>)}</ul>
        )}
        <label className="muted fs-13">Why (at least one sentence; it goes into the MAP)</label>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} className="w-full" data-testid="move-reason" />
        {error && <Banner tone="err">{error}</Banner>}
        <div className="row justify-end mt-8">
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
  if (!rows.length) return <p className="muted m-0" data-testid="diff-empty">The plan is the MS-01 default: no departure.</p>;
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
              <td className="fs-13">{d.by}{d.status === "PENDING" ? " (proposed)" : ""}<div className="muted">{d.reason}</div></td>
              <td>
                {d.status === "PENDING" && d.proposal ? (
                  <div className="ctl-row">
                    <ReasonField value={reasons[d.proposal] ?? ""} className="w-160" ariaLabel={`reason for the change to ${d.target}`}
                                 onChange={(v) => setReasons({ ...reasons, [d.proposal as string]: v })} />
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
      {error && <Banner tone="err">{error}</Banner>}
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
      {open.length === 0 ? <Banner tone="ok" testId="validator-green">Green: no open MS-01 rule violation.</Banner> : (
        <ul className="violations">
          {open.map((v) => (
            <li key={v.id} className={v.severity} data-testid={`violation-${v.id}`}>
              <span className={`chip ${v.severity === "error" ? "high" : "medium"}`}>{v.severity}</span> {v.message}
              {v.severity === "warning" && (
                <span className="ctl-row mt-4">
                  <ReasonField placeholder="accept it because…" value={reasons[v.id] ?? ""} className="flex-1 minw-160"
                               ariaLabel={`reason to acknowledge ${v.id}`} onChange={(x) => setReasons({ ...reasons, [v.id]: x })} />
                  <button className="btn tiny" disabled={!reasons[v.id]?.trim()}
                          onClick={async () => setError(await onAcknowledge(v.id, reasons[v.id]))}>Acknowledge</button>
                  {!reasons[v.id]?.trim() && <WaitingFor>Type a reason to acknowledge it.</WaitingFor>}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {done.length > 0 && <p className="muted fs-12">Acknowledged (they become MAP limitations): {done.map((v) => v.message).join(" · ")}</p>}
      {error && <Banner tone="err">{error}</Banner>}
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
    <div data-testid="blinding" className="fs-12">
      <h3>Blinding</h3>
      <p className="muted m-0-0-4">
        {state.map_signed ? "Lifted: the MAP is signed." : state.on
          ? `On — ${state.blinded.length} external stud${state.blinded.length === 1 ? "y's" : "ies'"} values withheld until the MAP is signed.`
          : "Off — external values are visible."} <span className="muted">({state.source}{state.reason ? `: ${state.reason}` : ""})</span>
      </p>
      {!state.map_signed && (
        <div className="row gap-4">
          <input placeholder="reason (MIDD lead)" value={reason} onChange={(e) => setReason(e.target.value)} className="flex-1 minw-100" />
          <button className="btn tiny" disabled={!reason.trim()} data-testid="blinding-toggle" onClick={async () => {
            const { problem } = await run(() => planApi.setBlinding(projectId, !state.on, reason));
            if (!problem) setReason("");
            setError(problem);
          }}>{state.on ? "Turn off" : "Turn on"}</button>
        </div>
      )}
      {error && <Banner tone="err" className="mt-4">{error}</Banner>}
    </div>
  );
}

/** Step 3 · Review & sign (redesign §3.3; plan §11): the one review D-27 relies on. The signature on top; the studies and
 *  their roles on the MS-01 canvas (the three diagrams, "Overall Data"); every input with its source in the review
 *  table; the estimation plan and the validation plan (R4b); credibility (the model risk, the tier's acceptance
 *  criteria, the budget split, the limitations); the live validator and the diff. */
export function PlanCanvas({ projectId, steps }: { projectId: string; steps?: ReactNode }) {
  const page = useResource("/api/v1/projects/{project_id}/plan", { project_id: projectId }, { poll: (d) => d.running });
  const review = useResource("/api/v1/projects/{project_id}/plan/review", { project_id: projectId }, { enabled: page.data !== null });
  const mutation = useMutation();
  const [tab, setTab] = useState<(typeof TABS)[number]>(TABS[0]);
  const [pending, setPending] = useState<Pending | null>(null);
  // a result or a refusal: a refusal (a rejected signature, a rebase the API turned down) is an error, read aloud
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [note, setNote] = useState("");
  const [signature, setSignature] = useState<Schema<"SignatureView"> | null>(null);
  const view = page.data;

  if (page.problem || !view) {
    return (
      <PageShell tone="review" steps={steps} eyebrow="Step 3 of 4 · Review & sign" title="Review & sign">
        {page.problem && /not ready/i.test(page.problem)
          // the plan is made from ready inputs: say what Inputs still waits on and go there, not an error on an empty page
          ? <StepBlocked projectId={projectId} step="review" title="Review & sign opens when the inputs are ready"
                         detail={page.problem} testId="plan-blocked" />
          : page.problem ? <Banner tone="err" testId="plan-problem">{page.problem}</Banner>
          : <p className="muted">Computing the MS-01 default plan…</p>}
      </PageShell>
    );
  }

  // a change to the plan, then the plan and the phase rail read again; answers the API's reason when it refused
  const apply = async <T,>(call: () => Promise<Envelope<T>>, ok?: string) => {
    const { problem } = await mutation.run(call);
    if (!problem && ok) setMessage({ ok: true, text: ok });
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
  // one label for the one signature, here and on the dashboard (NEXT.review)
  const signLabel = signed && pendingDeviations.length
    ? `Sign the deviation${pendingDeviations.length === 1 ? "" : "s"} (${pendingDeviations.length})` : "Sign the plan (MAP)";
  const nextMapVersion = signed ? (view.map?.map_version ?? 1) + 1 : 1;

  return (
    <PageShell
      tone="review" steps={steps}
      eyebrow="Step 3 of 4 · Review & sign"
      title={<>Review &amp; sign · {view.plan.compound}</>}
      lede={<>The one review before the run: the studies and their roles, every input with its source, and the model&apos;s
        credibility. The plan starts as the MS-01 default; each change has a reason, and the MAP is generated from the plan
        and signed only when the validator has nothing open.</>}
      actions={<span className={`chip ${view.blocking ? "high" : "low"}`} data-testid="blocking-chip">
        {view.blocking ? `${view.blocking} open violation${view.blocking === 1 ? "" : "s"}` : "validator green"}</span>}
    >
      <Card title={`Model plan v${view.artifact.version} · the signature`}>
        {stale && (
          <Banner tone="warn" testId="plan-stale">
            The inputs changed since this plan ({view.artifact.stale_reasons.join("; ")}).
            <button className="btn tiny ml-8" onClick={async () => {
              const problem = await apply(() => planApi.rebase(projectId), "Plan brought up to date; your choices kept.");
              if (problem) setMessage({ ok: false, text: `The plan was not brought up to date: ${problem}` });
            }}>
              Bring it up to date</button>
          </Banner>
        )}
        <p className="muted m-0-0-8 fs-13">
          {view.plan.structure.objective} · {view.plan.structure.context_of_use}
        </p>
        <div className="row">
          <button className="btn" disabled={!view.agents.enabled || view.running || signed}
                  onClick={async () => {
                    const problem = await apply(() => planApi.draft(projectId));
                    setMessage(problem ? { ok: false, text: problem } : { ok: true, text: "The rationale is being drafted; its proposals appear in the diff." });
                  }}
                  title="The plan agent (A5) drafts the rationale; you review each proposal in the diff">
            Draft the rationale</button>
          <input placeholder="signature note" value={note} onChange={(e) => setNote(e.target.value)} className="flex-1 minw-140" />
          <button className="btn primary" disabled={!canSign || mutation.busy} data-testid="approve-and-sign"
                  title={canSign ? "generate the MAP from this plan and sign it (MIDD lead)"
                    : signed ? "the MAP is signed; a change now is a deviation to sign" : "resolve or acknowledge every violation first"}
                  onClick={() => setConfirming(true)}>
            {signLabel}</button>
          {signed && view.map && !pendingDeviations.length && (
            // the one start is on the Run step, from this signed MAP (the owner's decision 2 of 2026-11-11)
            <Link className="btn" href={`/projects/${projectId}`} data-testid="go-to-run">Go to Run</Link>
          )}
        </div>
        {!canSign && !signed && view.blocking > 0 && (
          <p className="muted fs-12 m-6-0-0">
            <a href="#review-validator">The live validator</a> lists what is still open.</p>
        )}
        {signed && <p className="muted fs-13" data-testid="map-signed">MAP v{view.map?.map_version ?? view.map?.version} signed{signature ? `: ${signature.manifestation}` : ""} · {view.map?.map_sha256.slice(0, 12)}{view.map?.supersedes ? " · supersedes the earlier version" : ""}</p>}
        {signed && pendingDeviations.length > 0 && (
          <Banner tone="warn" className="mt-8" testId="deviations-pending">
            <strong>MAP deviations pending signature (ICH M15).</strong> They apply to campaigns once the MIDD
            lead signs them into a new MAP version; until then the signed MAP stands.
            <ul className="plain mt-6">
              {pendingDeviations.map((d, i) => <li key={i}><code>{d.target}</code> {d.change} — {d.reason}</li>)}
            </ul>
          </Banner>
        )}
        {signed && !pendingDeviations.length && (
          <p className="muted fs-12 m-4-0-0">A change now is a MAP deviation: it is recorded and
            waits for the MIDD lead&apos;s signature.</p>
        )}
        {message && <div className="mt-8"><Banner tone={message.ok ? "ok" : "err"} testId="plan-message">{message.text}</Banner></div>}
        {confirming && (
          // what is signed, and what the signature means, before it is made (Part 11 §11.50), as for an escalation's decision
          <Dialog title="Electronic signature" size="narrow" testId="sign-confirm-dialog"
                  onClose={() => { if (!mutation.busy) setConfirming(false); }}>
            <>
              <p className="muted" data-testid="sign-confirm-what">
                {pendingDeviations.length ? (
                  <>You are about to sign {pendingDeviations.length} MAP deviation{pendingDeviations.length === 1 ? "" : "s"} for{" "}
                    <strong>{view.plan.compound}</strong> into <strong>MAP v{nextMapVersion}</strong>, which supersedes
                    MAP v{nextMapVersion - 1}:</>
                ) : (
                  <>You are about to sign <strong>MAP v{nextMapVersion}</strong> for <strong>{view.plan.compound}</strong>,
                    generated from model plan v{view.artifact.version}.</>
                )}{" "}
                It is recorded as an <em>Approved</em> signature (MIDD lead) bound to the MAP&apos;s content; your password
                is never entered into Modeler One — the signature is taken from your session&apos;s step-up authentication.
              </p>
              {pendingDeviations.length > 0 && (
                <ul className="plain">
                  {pendingDeviations.map((d, i) => <li key={i}><code>{d.target}</code> {d.change} — {d.reason}</li>)}
                </ul>
              )}
              {note.trim() && <p className="muted fs-13">Signature note: {note.trim()}</p>}
              <div className="dialog-actions">
                <button className="btn" disabled={mutation.busy} onClick={() => setConfirming(false)}>Cancel</button>
                <button className="btn primary" disabled={mutation.busy} data-testid="sign-confirm" onClick={async () => {
                  const done = pendingDeviations.length
                    ? `Deviations signed: MAP v${nextMapVersion} supersedes v${nextMapVersion - 1}.`
                    : "MAP generated from the plan and signed.";
                  const { data, problem } = await mutation.run(() => planApi.sign(projectId, note));
                  setConfirming(false);
                  if (data) { setSignature(data.signature); celebrate(); toast(done); }
                  setMessage(problem ? { ok: false, text: `The MAP was not signed: ${problem}` } : { ok: true, text: done });
                }}>{mutation.busy ? "Signing…" : signLabel}</button>
              </div>
            </>
          </Dialog>
        )}
      </Card>
      <nav className="review-nav" aria-label="Review sections">
        <a href="#review-studies">Studies and roles</a><a href="#review-inputs">The inputs</a>
        <a href="#review-estimation">The estimation plan</a><a href="#review-validation">The validation plan</a>
        <a href="#review-applications">Applications</a>
        <a href="#review-credibility">Credibility</a><a href="#review-validator">Validator and changes</a>
      </nav>
      <section className="review-block" id="review-studies" aria-labelledby="review-studies-title">
        <h2 id="review-studies-title">Studies and roles</h2>
        <div className="plan-layout">
          <aside className="overall-data" data-testid="overall-data" aria-label="Overall Data"
                 onDragOver={(e) => { if (e.dataTransfer.types.includes(STUDY_MIME)) e.preventDefault(); }}>
            <h2>Overall Data</h2>
            <p className="muted fs-12 mt-0">CPF v1 and the study catalog. Drag a dataset onto a D3 node, an arrow or the training layer.</p>
            <h3>Datasets ({studies.length})</h3>
            {studies.map((s) => (
              <div key={s.study_id} className="overall-study">
                <StudyChip s={s} view={view} />
                <div className="muted fs-11">{s.route.replace("_", " ")} · {s.dose_mg} mg · {s.food_state} · {s.design} · n {s.n} → {s.role}</div>
              </div>
            ))}
            <BlindingPanel projectId={projectId} />
            <h3>Dissolution</h3>
            {view.d2.dissolution.length ? view.d2.dissolution.map((d) => <div key={d.id} className="muted fs-12">◆ {d.label}</div>)
              : <p className="muted fs-12">none</p>}
            <h3>CPF v1 ({view.overall_data.parameters.length})</h3>
            <ul className="param-list">
              {view.overall_data.parameters.map((p) => (
                <li key={p.id}><code>{p.id}</code> {typeof p.value === "number" ? +p.value.toPrecision(4) : String(p.value)} {p.unit ?? ""}</li>
              ))}
            </ul>
          </aside>
          <section className="plan-main">
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
          </section>
        </div>
        {review.data && <StudiesTable projectId={projectId} review={review.data} run={mutation.run} busy={mutation.busy} />}
      </section>
      <section className="review-block" id="review-inputs" aria-labelledby="review-inputs-title">
        <h2 id="review-inputs-title">The inputs</h2>
        <p className="muted review-lede">Every value the model takes, with the source the CPF keeps. Exclude a value with a reason:
          the next source takes its place, and the plan asks to be brought up to date.</p>
        {review.problem ? <InlineIssue severity="error">{review.problem}</InlineIssue>
          : review.data ? <ReviewTable projectId={projectId} review={review.data} run={mutation.run} busy={mutation.busy} />
            : <p className="muted">Loading the review…</p>}
      </section>
      <section className="review-block" id="review-estimation" aria-labelledby="review-estimation-title">
        <h2 id="review-estimation-title">The estimation plan</h2>
        <p className="muted review-lede">Each parameter fixed or estimated, its start value and source, and its bounds. Estimating one
          is your choice, with a reason; MS-01&apos;s default bounds are proposed and the validator checks them.</p>
        {review.data ? <EstimationPlan projectId={projectId} review={review.data} apply={apply} />
          : review.problem ? <InlineIssue severity="error">{review.problem}</InlineIssue> : <p className="muted">Loading…</p>}
      </section>
      <section className="review-block" id="review-validation" aria-labelledby="review-validation-title">
        <h2 id="review-validation-title">The validation plan</h2>
        <p className="muted review-lede">What validates the model under this MAP, and what happens if it fails.</p>
        {review.data ? <ValidationPlan review={review.data} />
          : review.problem ? <InlineIssue severity="error">{review.problem}</InlineIssue> : <p className="muted">Loading…</p>}
      </section>
      <section className="review-block" id="review-applications" aria-labelledby="review-applications-title">
        <h2 id="review-applications-title">Applications</h2>
        <p className="muted review-lede">What S6 runs after validation, with its inputs, and what the campaign does with each application
          the brief names. One it cannot run yet is said here; acknowledged, it becomes a limitation of the MAP.</p>
        {review.data ? <Applications projectId={projectId} view={view} review={review.data} apply={apply} />
          : review.problem ? <InlineIssue severity="error">{review.problem}</InlineIssue> : <p className="muted">Loading…</p>}
      </section>
      <section className="review-block" id="review-credibility" aria-labelledby="review-credibility-title">
        <h2 id="review-credibility-title">Credibility (ICH M15)</h2>
        {review.data ? <Credibility projectId={projectId} view={view} review={review.data} apply={apply} />
          : review.problem ? <InlineIssue severity="error">{review.problem}</InlineIssue> : <p className="muted">Loading…</p>}
      </section>
      <div className="cols-2" id="review-validator">
        <Card title="Live validator (MS-01)">
          <ValidatorPanel view={view} onAcknowledge={(id, reason) => apply(() => planApi.acknowledge(projectId, id, reason))} />
        </Card>
        <Card title="Changes from the MS-01 default">
          <DiffView rows={view.diff} onDecide={(id, accept, reason) => apply(() => planApi.decide(projectId, id, accept, reason))} />
          {view.plan.default_rationale.length > 0 && (
            <details className="mt-8"><summary className="muted">MS-01 split rationale and limitations</summary>
              <ul className="flags">{[...view.plan.default_rationale, ...view.plan.default_limitations].map((r) => <li key={r}>{r}</li>)}</ul>
            </details>
          )}
        </Card>
      </div>
      {pending && (
        <DropDialog pending={pending} onCancel={() => setPending(null)}
                    onConfirm={async (reason) => {
                      const error = await apply(() => planApi.place(projectId, pending.studyId, pending.to, reason));
                      if (!error) setPending(null);
                      return error;
                    }} />
      )}
    </PageShell>
  );
}
