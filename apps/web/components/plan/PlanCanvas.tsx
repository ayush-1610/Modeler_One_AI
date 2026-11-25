"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { InlineIssue, PageShell } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { TabPanel, Tabs } from "@/components/kit/Tabs";
import { D3Dag, STUDY_MIME, StudyChip } from "@/components/plan/D3Dag";
import { D1Disposition, D2Absorption } from "@/components/plan/Diagrams";
import { PlanReadOnly, useReadOnly } from "@/components/plan/ReadOnly";
import { Credibility, StudiesTable } from "@/components/review/Credibility";
import { EstimationPlan } from "@/components/review/EstimationPlan";
import { ReviewTable } from "@/components/review/ReviewTable";
import { Applications } from "@/components/review/Applications";
import { ValidationPlan } from "@/components/review/ValidationPlan";
import type { Envelope, Schema } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";
import { PLAN_CHANGED, ROLE_LABEL, planApi, type DiffRow, type PlanView, type Role, type Violation } from "@/lib/plan";
import { readinessText } from "@/lib/words";
import { startCampaign } from "@/lib/writes";
import { toast } from "@/components/kit/Toast";
import { StepBlocked } from "@/components/kit/StepBlocked";

type Pending = { studyId: string; from: Role; to: Role; where: string; preview: Violation[] | null; problem: string | null;
                 deviation?: boolean };
type Unlocking = { studyId: string; preview: Schema<"PlacementPreview"> | null; problem: string | null };
const TABS = ["D3 · development and validation", "D1 · disposition", "D2 · absorption and formulation"] as const;

// The page's tabs (the console redesign's slice 5, P-14): one part of the review at a time, the signature above them.
// The tab is in the address (?tab=), and an old link to a section (#review-studies) opens its tab.
const REVIEW_TABS = [
  ["studies", "Studies and roles"], ["inputs", "The inputs"], ["estimation", "The estimation plan"],
  ["validation", "The validation plan"], ["applications", "Applications"], ["credibility", "Credibility"],
  ["validator", "Validator and changes"],
] as const;
type ReviewTab = (typeof REVIEW_TABS)[number][0];
const asTab = (text: string | null | undefined): ReviewTab | null =>
  REVIEW_TABS.find(([id]) => id === text)?.[0] ?? null;

/** What a dry run of a change says it changes: the study's role from what it is to what it would be. */
function RoleChange({ studyId, from, to, deviation }: { studyId: string; from: Role | null; to: Role; deviation: boolean }) {
  return (
    <p className="m-0" data-testid="change-what">
      <strong>What this changes:</strong> {studyId} {from ? <>from {ROLE_LABEL[from]} </> : null}to {ROLE_LABEL[to]}
      {deviation ? "; the signed MAP stands until the MIDD lead signs this deviation into a new MAP version." : "."}
    </p>
  );
}

/** "Back to the MS-01 default" (`:unlock`): a study a person placed is given back to the role MS-01 gives it. Its dry run
 *  says first what it changes and the validator's answer; nothing is saved until it is confirmed. */
function UnlockDialog({ view, unlocking, onConfirm, onCancel }: {
  view: PlanView; unlocking: Unlocking; onConfirm: () => Promise<string | null>; onCancel: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const { studyId, preview } = unlocking;
  const now = view.overall_data.studies.find((s) => s.study_id === studyId)?.role ?? null;
  const back = (preview?.diff ?? []).some((d) => d.kind === "role" && d.target === studyId) ? null
    : view.diff.find((d) => d.kind === "role" && d.target === studyId)?.from as Role | undefined;
  // the validator's errors about this study (as a move's dialog says them): the plan's other open items stay on Validator
  const errors = (preview?.violations ?? []).filter((v) => v.severity === "error" && v.target === studyId);
  return (
    <Dialog title={`${studyId}: back to the MS-01 default`} size="narrow" onClose={onCancel} testId="unlock-dialog">
      <p className="muted mt-0">A person placed it; it goes back to the role MS-01 gives it, and its reason leaves the changes.</p>
      {unlocking.problem && <div className="banner err">{unlocking.problem}</div>}
      {!preview && !unlocking.problem && <p className="muted">checking…</p>}
      {preview && back && <RoleChange studyId={studyId} from={now} to={back} deviation={preview.deviation} />}
      {preview?.deviation && (
        <div className="banner warn mt-8" data-testid="unlock-deviation">The MAP is signed: this is a MAP deviation. It is recorded
          and applies only once the MIDD lead signs it into a new MAP version.</div>
      )}
      {preview && (errors.length === 0
        ? <div className="banner ok mt-8" data-testid="unlock-ok">No MS-01 rule is broken for {studyId} by it.</div>
        : <ul className="flags" data-testid="unlock-errors">{errors.map((v) => <li key={v.id}>{v.message}</li>)}</ul>)}
      {error && <div className="banner err mt-8">{error}</div>}
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button type="button" className="btn primary" disabled={!preview} data-testid="unlock-confirm"
                onClick={async () => setError(await onConfirm())}>Put it back</button>
      </div>
    </Dialog>
  );
}

function DropDialog({ pending, onConfirm, onCancel }: { pending: Pending; onConfirm: (reason: string) => Promise<string | null>; onCancel: () => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mine = (pending.preview ?? []).filter((v) => v.target === pending.studyId || !["error"].includes(v.severity));
  const errors = mine.filter((v) => v.severity === "error");
  return (
    <Dialog title={`${pending.studyId}: ${ROLE_LABEL[pending.from]} → ${ROLE_LABEL[pending.to]}`} size="narrow" onClose={onCancel}
            testId="drop-dialog">
        <p className="muted mt-0">Dropped on {pending.where}. The validator&apos;s answer for this move:</p>
        {pending.preview !== null && <RoleChange studyId={pending.studyId} from={pending.from} to={pending.to}
                                                 deviation={pending.deviation ?? false} />}
        {pending.problem && <div className="banner err">{pending.problem}</div>}
        {pending.deviation && (
          <div className="banner warn" data-testid="move-deviation">The MAP is signed: this move is a MAP deviation. It is
            recorded and applies only once the MIDD lead signs it into a new MAP version.</div>
        )}
        {pending.preview === null && !pending.problem && <p className="muted">checking…</p>}
        {pending.preview !== null && (errors.length === 0
          ? <div className="banner ok" data-testid="move-ok">No MS-01 rule is broken by this move.</div>
          : <ul className="flags" data-testid="move-errors">{errors.map((v) => <li key={v.id}>{v.message}</li>)}</ul>)}
        {pending.preview && mine.filter((v) => v.severity === "warning" && !v.acknowledged).length > 0 && (
          <ul className="flags warn">{mine.filter((v) => v.severity === "warning" && !v.acknowledged).map((v) => <li key={v.id}>{v.message}</li>)}</ul>
        )}
        <label className="muted fs-13 mt-8" htmlFor="move-reason">Why (at least one sentence; it goes into the MAP)</label>
        <textarea id="move-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={3} className="w-full" data-testid="move-reason" />
        {error && <div className="banner err">{error}</div>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn primary" disabled={reason.trim().length < 8} data-testid="move-confirm"
                  onClick={async () => setError(await onConfirm(reason))}>
            {errors.length ? "Place it anyway (blocks signing)" : "Place it"}
          </button>
        </div>
    </Dialog>
  );
}

function DiffView({ rows, onDecide }: { rows: DiffRow[]; onDecide: (id: string, accept: boolean, reason: string) => Promise<string | null> }) {
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const readOnly = useReadOnly();
  if (!rows.length) return <p className="muted m-0" data-testid="diff-empty">The plan is the MS-01 default: no departure.</p>;
  return (
    <>
      <div className="tbl-scroll"><table data-testid="diff">
        <thead><tr><th>Change</th><th>MS-01 default</th><th>Plan</th><th>By · why</th><th /></tr></thead>
        <tbody>
          {rows.map((d, i) => (
            <tr key={`${d.kind}-${d.target}-${i}`} className={d.status === "PENDING" ? "pending" : ""} data-testid={`diff-${d.target}`}>
              <td><span className="chip neutral">{d.kind}</span> <code>{d.target}</code></td>
              <td className="diff-from">{String(d.from)}</td>
              <td className="diff-to">{String(d.to)}</td>
              <td className="fs-13">{d.by}{d.status === "PENDING" ? " (proposed)" : ""}<div className="muted">{d.reason}</div></td>
              <td>
                {d.status === "PENDING" && d.proposal && readOnly ? <span className="chip medium">proposed</span>
                  : d.status === "PENDING" && d.proposal ? (
                  <div className="row gap-4">
                    <input placeholder="why" value={reasons[d.proposal] ?? ""} className="w-120"
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
      </table></div>
      {error && <div className="banner err">{error}</div>}
    </>
  );
}

function ValidatorPanel({ view, onAcknowledge }: { view: PlanView; onAcknowledge: (id: string, reason: string) => Promise<string | null> }) {
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const readOnly = useReadOnly();
  const open = view.violations.filter((v) => v.severity === "error" || !v.acknowledged);
  const done = view.violations.filter((v) => v.severity === "warning" && v.acknowledged);
  return (
    <div data-testid="validator">
      {open.length === 0 ? <div className="banner ok" data-testid="validator-green">Green: no open MS-01 rule violation.</div> : (
        <ul className="violations">
          {open.map((v) => (
            <li key={v.id} className={v.severity} data-testid={`violation-${v.id}`}>
              <span className={`chip ${v.severity === "error" ? "high" : "medium"}`}>{v.severity}</span> {v.message}
              {v.severity === "warning" && !readOnly && (
                <span className="row gap-4 mt-4">
                  <input placeholder="accept it because…" value={reasons[v.id] ?? ""} className="flex-1"
                         onChange={(e) => setReasons({ ...reasons, [v.id]: e.target.value })} />
                  <button className="btn tiny" disabled={!reasons[v.id]?.trim()}
                          onClick={async () => setError(await onAcknowledge(v.id, reasons[v.id]))}>Acknowledge</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {done.length > 0 && <p className="muted fs-12">Acknowledged (they become MAP limitations): {done.map((v) => v.message).join(" · ")}</p>}
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
  const readOnly = useReadOnly();
  if (!state) return null;
  return (
    <div data-testid="blinding" className="fs-12">
      <h3>Blinding</h3>
      <p className="muted m-0-0-4">
        {state.map_signed ? "Lifted: the MAP is signed." : state.on
          ? `On — ${state.blinded.length} external stud${state.blinded.length === 1 ? "y's" : "ies'"} values withheld until the MAP is signed.`
          : "Off — external values are visible."} <span className="muted">({state.source}{state.reason ? `: ${state.reason}` : ""})</span>
      </p>
      {!state.map_signed && !readOnly && (
        <div className="row gap-4">
          <input placeholder="reason (MIDD lead)" value={reason} onChange={(e) => setReason(e.target.value)} className="flex-1 minw-100" />
          <button className="btn tiny" disabled={!reason.trim()} data-testid="blinding-toggle" onClick={async () => {
            const { problem } = await run(() => planApi.setBlinding(projectId, !state.on, reason), PLAN_CHANGED);
            if (!problem) setReason("");
            setError(problem);
          }}>{state.on ? "Turn off" : "Turn on"}</button>
        </div>
      )}
      {error && <div className="banner err mt-4">{error}</div>}
    </div>
  );
}

/** The roles that change and sign a plan (the API's `deps.WRITE_ROLES`); any other role reads it. */
const WRITE_ROLES = ["modeler-curator", "modeler-reviewer"];

/** Step 3 · Review & sign (redesign §3.3; plan §11; the console redesign's slice 5, P-14): the one review D-27 relies
 *  on. The signature on top, as a panel; below it one tab at a time: the studies and their roles on the MS-01 canvas
 *  (the three diagrams, "Overall Data"), every input with its source, the estimation and validation plans (R4b), the
 *  applications, credibility (the model risk, the tier's acceptance criteria, the budget split, the limitations), and
 *  the live validator with the changes from the MS-01 default. A member who may not change the plan reads all of it
 *  with no control (`PlanReadOnly`). */
export function PlanCanvas({ projectId, steps }: { projectId: string; steps?: ReactNode }) {
  // A viewer reads the plan through `plan:view`: `GET /plan` is a writer's (it makes the MS-01 default plan when there is
  // none), and a viewer got its 403 instead of the plan (redesign review R-S03). The roles are the API's own answer.
  // (unknown until /me answers; if /me fails, the writer's read runs and its own answer says what is wrong)
  const me = useResource("/api/v1/me", {}, { select: (d) => d.roles });
  const writer = me.data ? me.data.some((r) => WRITE_ROLES.includes(r)) : me.problem ? true : null;
  const edit = useResource("/api/v1/projects/{project_id}/plan", { project_id: projectId },
                           { poll: (d) => d.running, enabled: writer === true });
  const read = useResource("/api/v1/projects/{project_id}/plan:view", { project_id: projectId },
                           { poll: (d) => d.running, enabled: writer === false });
  const page = writer === false ? read : edit;
  const review = useResource("/api/v1/projects/{project_id}/plan/review", { project_id: projectId }, { enabled: page.data !== null });
  const mutation = useMutation();
  const pathname = usePathname();
  const search = useSearchParams();
  const [reviewTab, setReviewTab] = useState<ReviewTab>(() => asTab(search.get("tab")) ?? "studies");
  const [tab, setTab] = useState<(typeof TABS)[number]>(TABS[0]);
  const [pending, setPending] = useState<Pending | null>(null);
  const [unlocking, setUnlocking] = useState<Unlocking | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [signature, setSignature] = useState<Schema<"SignatureView"> | null>(null);
  // a link to a section of the one-page review (#review-studies, Inputs' blinded study) opens its tab
  useEffect(() => {
    const at = asTab(window.location.hash.replace(/^#review-/, ""));
    if (at) setReviewTab(at);
  }, []);
  // the tab in the address, the history entry replaced (as Inputs' areas): the page is the same, nothing is drawn again
  const showTab = (t: ReviewTab) => {
    setReviewTab(t);
    window.history.replaceState(null, "", `${pathname}?tab=${t}`);
  };
  const view = page.data;
  const readOnly = writer === false;

  if (page.problem || !view) {
    return (
      <PageShell tone="review" steps={steps} eyebrow="Step 3 of 4" title="Review & sign" slim>
        {page.problem && /^the (model )?inputs /i.test(page.problem)
          // the plan is made from ready inputs (`inputs_ready`'s 409: not ready, not put together, changed, no CPF or no
          // study): say what Inputs still waits on and go there, in words, not an error on an empty page (round 3, OWN-8)
          ? <StepBlocked projectId={projectId} step="review" title="Review & sign opens when the inputs are ready"
                         detail={page.problem} testId="plan-blocked" />
          : page.problem && writer === false && /no model plan yet/i.test(page.problem)
          ? <p className="muted" data-testid="plan-none-yet">No model plan yet. It is made by a curator once the inputs are ready.</p>
          : page.problem ? <div className="banner err" data-testid="plan-problem">{page.problem}</div>
          : <p className="muted">{writer === false ? "Reading the model plan…" : "Computing the MS-01 default plan…"}</p>}
      </PageShell>
    );
  }

  // a change to the plan, then the plan and the phase rail read again; answers the API's reason when it refused
  // a refusal because the inputs changed or are not ready (`inputs_ready`) is said in words, never as the API wrote it
  // ("S0 completeness (MS-01 §2.2); …": round 3, OWN-8); any other refusal reads as it came
  const apply = async <T,>(call: () => Promise<Envelope<T>>, ok?: string) => {
    const { problem } = await mutation.run(call, PLAN_CHANGED);
    if (!problem && ok) setMessage(ok);
    return problem ? readinessText(problem) : problem;
  };
  const onDrop = async (studyId: string, role: Role, where: string) => {
    if (readOnly) return;
    const from = view.overall_data.studies.find((s) => s.study_id === studyId)?.role ?? "SUPPORTIVE";
    setPending({ studyId, from, to: role, where, preview: null, problem: null });
    // the dry run saves nothing, so it is a plain call, not a change
    const env = await planApi.place(projectId, studyId, role, "preview of the move", true);
    const preview = env.data && "deviation" in env.data ? env.data : null;
    setPending((p) => p && p.studyId === studyId ? { ...p, preview: preview?.violations ?? null, problem: env.errors?.[0]?.message ?? null,
                                                      deviation: preview?.deviation ?? false } : p);
  };
  const onUnlock = async (studyId: string) => {
    setUnlocking({ studyId, preview: null, problem: null });
    // its dry run says what it changes first; nothing is saved
    const env = await planApi.unlock(projectId, studyId, true);
    const preview = env.data && "deviation" in env.data ? env.data : null;
    setUnlocking((u) => u && u.studyId === studyId ? { ...u, preview, problem: env.errors?.[0]?.message ?? null } : u);
  };
  const stale = view.artifact.status === "STALE";
  const signed = view.signed ?? view.map?.status === "APPROVED";
  const pendingDeviations = (view.deviations ?? []).filter((d) => !d.signature_id);
  // before the first signature: sign the plan; after it: sign the deviations (D-14), nothing else to sign
  const canSign = view.blocking === 0 && !stale && (!signed || pendingDeviations.length > 0);
  const studies = view.overall_data.studies;
  const placed = new Set(studies.filter((s) => s.userLocked).map((s) => s.study_id));
  const openViolations = view.violations.filter((v) => v.severity === "error" || !v.acknowledged).length;
  const tabs = REVIEW_TABS.map(([id, label]) => ({
    id, label, testId: `review-tab-${id}`,
    ...(id === "studies" ? { count: studies.length, countLabel: "studies" } : {}),
    ...(id === "validator" && openViolations ? { count: openViolations, countLabel: "open" } : {}),
  }));
  const loading = <p className="muted">Loading the review…</p>;
  const problem = review.problem ? <InlineIssue severity="error">{readinessText(review.problem)}</InlineIssue> : null;

  return (
    <PlanReadOnly.Provider value={readOnly}>
    <PageShell
      tone="review" steps={steps} slim
      eyebrow="Step 3 of 4"
      title="Review & sign"
      lede={<>{view.plan.compound} · the model analysis plan (MAP), the one review before the run. The plan starts as the MS-01
        default; each change has a reason, and the MAP is generated from it and signed only when the validator has nothing open.</>}
      actions={<span className={`chip ${view.blocking ? "high" : "low"}`} data-testid="blocking-chip">
        {view.blocking ? `Validator: ${view.blocking} open violation${view.blocking === 1 ? "" : "s"}` : "Validator: no open violation"}</span>}
    >
      <section className="panel" aria-labelledby="signature-title" data-testid="plan-signature">
        <div className="panel-head">
          <h2 id="signature-title">Model plan v{view.artifact.version} · the signature</h2>
          <span className="grow" />
          {signed && <span className="chip low">MAP signed</span>}
        </div>
        <div className="panel-body">
          {stale && (
            <div className="banner warn" data-testid="plan-stale">
              The inputs changed since this plan ({view.artifact.stale_reasons.join("; ")}).
              {!readOnly && <button className="btn tiny ml-8" onClick={() => apply(() => planApi.rebase(projectId), "Plan brought up to date; your choices kept.")}>
                Bring it up to date</button>}
            </div>
          )}
          <p className="muted m-0-0-8 fs-13">
            {view.plan.structure.objective} · {view.plan.structure.context_of_use}
          </p>
          {readOnly && (
            <div className="banner warn mb-8" data-testid="plan-read-only">
              You can read this plan. Changing it and signing it take a curator or a reviewer.</div>
          )}
          {!readOnly && <div className="row">
            <button className="btn" disabled={!view.agents.enabled || view.running || signed}
                    onClick={async () => setMessage(await apply(() => planApi.draft(projectId)) ?? "A5 is drafting the rationale; proposals appear in the changes.")}>
              Draft with A5</button>
            <input placeholder="signature note" aria-label="signature note" value={note} onChange={(e) => setNote(e.target.value)} className="flex-1 minw-140" />
            <button className="btn primary" disabled={!canSign} data-testid="approve-and-sign"
                    title={canSign ? "generate the MAP from this plan and sign it (MIDD lead)"
                      : signed ? "the MAP is signed; a change now is a deviation to sign" : "resolve or acknowledge every violation first"}
                    onClick={async () => {
                      const done = pendingDeviations.length
                        ? `Deviations signed: MAP v${(view.map?.map_version ?? 1) + 1} supersedes v${view.map?.map_version ?? 1}.`
                        : "MAP generated from the plan and signed.";
                      const { data, problem } = await mutation.run(() => planApi.sign(projectId, note), PLAN_CHANGED);
                      if (data) { setSignature(data.signature); toast(done); }
                      setMessage(problem ? readinessText(problem) : done);
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
          </div>}
          {!canSign && !signed && view.blocking > 0 && (
            <p className="muted fs-12 m-6-0-0">
              <button type="button" className="link-btn" onClick={() => showTab("validator")} data-testid="go-validator">The live
                validator</button> lists what is still open.</p>
          )}
          {signed && <p className="muted fs-13" data-testid="map-signed">MAP v{view.map?.map_version ?? view.map?.version} signed{signature ? `: ${signature.manifestation}` : ""} · {view.map?.map_sha256.slice(0, 12)}{view.map?.supersedes ? " · supersedes the earlier version" : ""}</p>}
          {signed && pendingDeviations.length > 0 && (
            <div className="banner warn mt-8" data-testid="deviations-pending">
              <strong>MAP deviations pending signature (ICH M15).</strong> They apply to campaigns once the MIDD
              lead signs them into a new MAP version; until then the signed MAP stands.
              <ul className="plain mt-6">
                {pendingDeviations.map((d, i) => <li key={i}><code>{d.target}</code> {d.change} — {d.reason}</li>)}
              </ul>
            </div>
          )}
          {signed && !pendingDeviations.length && !readOnly && (
            <p className="muted fs-12 m-4-0-0">A change now is a MAP deviation: it is recorded and
              waits for the MIDD lead&apos;s signature.</p>
          )}
          {message && <div className="banner ok mt-8">{message}</div>}
        </div>
      </section>

      <div className="area-bar review-bar" data-testid="review-tabs">
        <Tabs label="Review sections" prefix="review" value={reviewTab} onChange={showTab} tabs={tabs} className="area-tabs" />
      </div>

      {reviewTab === "studies" && (
        <TabPanel prefix="review" id="studies">
          <section className="review-block" id="review-studies" aria-labelledby="review-studies-title">
            <h2 id="review-studies-title" className="sr-only">Studies and roles</h2>
            <div className="plan-layout">
              <aside className="overall-data panel" data-testid="overall-data" aria-label="Overall Data"
                     onDragOver={(e) => { if (!readOnly && e.dataTransfer.types.includes(STUDY_MIME)) e.preventDefault(); }}>
                <h2>Overall Data</h2>
                <p className="muted fs-12 mt-0">CPF v1 and the study catalog.{readOnly ? "" : " Drag a dataset onto a D3 node, an arrow or the training layer."}</p>
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
              <section className="plan-main panel" aria-label="The MS-01 canvas">
                <div className="panel-head">
                  <div className="view-switch" role="group" aria-label="Diagram">
                    {TABS.map((t) => <button key={t} type="button" aria-pressed={tab === t} onClick={() => setTab(t)}>{t}</button>)}
                  </div>
                </div>
                <div className="panel-body">
                  {tab === TABS[0] && <D3Dag view={view} onDrop={onDrop}
                                             onLayout={(layout) => { if (!readOnly) void apply(() => planApi.layout(projectId, layout)); }} />}
                  {tab === TABS[1] && <D1Disposition view={view} onFit={(pid, fit) => apply(() => planApi.fit(projectId, pid, fit))}
                                                     onUnfit={(pid, reason) => apply(() => planApi.unfit(projectId, pid, reason))} />}
                  {tab === TABS[2] && <D2Absorption view={view} onFit={(pid, fit) => apply(() => planApi.fit(projectId, pid, fit))}
                                                    onUnfit={(pid, reason) => apply(() => planApi.unfit(projectId, pid, reason))}
                                                    onStructure={(key, value, reason) => apply(() => planApi.structure(projectId, key, value, reason))} />}
                </div>
              </section>
            </div>
            <section className="panel" aria-labelledby="review-studies-table-title">
              <div className="panel-head"><h2 id="review-studies-table-title">Studies</h2></div>
              <div className="panel-body">
                {review.data ? <StudiesTable projectId={projectId} review={review.data} run={mutation.run} busy={mutation.busy}
                                             placed={placed} onUnlock={(id) => void onUnlock(id)} /> : problem ?? loading}
              </div>
            </section>
          </section>
        </TabPanel>
      )}
      {reviewTab === "inputs" && (
        <TabPanel prefix="review" id="inputs">
          <section className="review-block" id="review-inputs" aria-labelledby="review-inputs-title">
            <h2 id="review-inputs-title">The inputs</h2>
            <p className="muted review-lede">Every value the model takes, with the source the CPF keeps.{readOnly ? "" : <> Exclude a value with a
              reason: the next source takes its place, and the plan asks to be brought up to date.</>}</p>
            {problem ?? (review.data ? <ReviewTable projectId={projectId} review={review.data} run={mutation.run} busy={mutation.busy} /> : loading)}
          </section>
        </TabPanel>
      )}
      {reviewTab === "estimation" && (
        <TabPanel prefix="review" id="estimation">
          <section className="review-block" id="review-estimation" aria-labelledby="review-estimation-title">
            <h2 id="review-estimation-title">The estimation plan</h2>
            <p className="muted review-lede">Each parameter fixed or estimated, its start value and source, and its bounds. Estimating one
              is a person&apos;s choice, with a reason; MS-01&apos;s default bounds are proposed and the validator checks them.</p>
            {review.data ? <EstimationPlan projectId={projectId} review={review.data} apply={apply} /> : problem ?? loading}
          </section>
        </TabPanel>
      )}
      {reviewTab === "validation" && (
        <TabPanel prefix="review" id="validation">
          <section className="review-block" id="review-validation" aria-labelledby="review-validation-title">
            <h2 id="review-validation-title">The validation plan</h2>
            <p className="muted review-lede">What validates the model under this MAP, and what happens if it fails.</p>
            {review.data ? <ValidationPlan review={review.data} /> : problem ?? loading}
          </section>
        </TabPanel>
      )}
      {reviewTab === "applications" && (
        <TabPanel prefix="review" id="applications">
          <section className="review-block" id="review-applications" aria-labelledby="review-applications-title">
            <h2 id="review-applications-title">Applications</h2>
            <p className="muted review-lede">What S6 runs after validation, with its inputs, and what the campaign does with each application
              the brief names. One it cannot run yet is said here; acknowledged, it becomes a limitation of the MAP.</p>
            {review.data ? <Applications projectId={projectId} view={view} review={review.data} apply={apply} /> : problem ?? loading}
          </section>
        </TabPanel>
      )}
      {reviewTab === "credibility" && (
        <TabPanel prefix="review" id="credibility">
          <section className="review-block" id="review-credibility" aria-labelledby="review-credibility-title">
            <h2 id="review-credibility-title">Credibility (ICH M15)</h2>
            {review.data ? <Credibility projectId={projectId} view={view} review={review.data} apply={apply} /> : problem ?? loading}
          </section>
        </TabPanel>
      )}
      {reviewTab === "validator" && (
        <TabPanel prefix="review" id="validator">
          <div className="cols-2" id="review-validator">
            <section className="panel" aria-labelledby="validator-title">
              <div className="panel-head"><h2 id="validator-title">Live validator (MS-01)</h2></div>
              <div className="panel-body">
                <ValidatorPanel view={view} onAcknowledge={(id, reason) => apply(() => planApi.acknowledge(projectId, id, reason))} />
              </div>
            </section>
            <section className="panel" aria-labelledby="changes-title">
              <div className="panel-head"><h2 id="changes-title">Changes from the MS-01 default</h2></div>
              <div className="panel-body">
                <DiffView rows={view.diff} onDecide={(id, accept, reason) => apply(() => planApi.decide(projectId, id, accept, reason))} />
                {view.plan.default_rationale.length > 0 && (
                  <details className="mt-8"><summary className="muted">MS-01 split rationale and limitations</summary>
                    <ul className="flags">{[...view.plan.default_rationale, ...view.plan.default_limitations].map((r) => <li key={r}>{r}</li>)}</ul>
                  </details>
                )}
              </div>
            </section>
          </div>
        </TabPanel>
      )}
      {pending && (
        <DropDialog pending={pending} onCancel={() => setPending(null)}
                    onConfirm={async (reason) => {
                      const error = await apply(() => planApi.place(projectId, pending.studyId, pending.to, reason));
                      if (!error) setPending(null);
                      return error;
                    }} />
      )}
      {unlocking && (
        <UnlockDialog view={view} unlocking={unlocking} onCancel={() => setUnlocking(null)}
                      onConfirm={async () => {
                        const error = await apply(() => planApi.unlock(projectId, unlocking.studyId),
                                                  `${unlocking.studyId} is back on its MS-01 default role.`);
                        if (!error) setUnlocking(null);
                        return error;
                      }} />
      )}
    </PageShell>
    </PlanReadOnly.Provider>
  );
}
