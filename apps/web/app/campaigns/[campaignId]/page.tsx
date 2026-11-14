import Link from "next/link";

import { AutoRefresh } from "@/components/AutoRefresh";
import { FoldError } from "@/components/FoldError";
import { PackageDownloads } from "@/components/PackageDownloads";
import { ApiProblem, Card, RiskChip, StatusChip } from "@/components/ui";
import { ConcentrationTimePlot } from "@/components/ConcentrationTimePlot";
import { FeedbackDiagnosisView, FeedbackTimeline } from "@/components/campaign/Feedback";
import { InfluenceHeatMap, LedgerTable } from "@/components/campaign/History";
import { VbeCard } from "@/components/campaign/Vbe";
import { EscalationsExpected } from "@/components/campaign/EscalationPopup";
import { EngineWarning } from "@/components/campaign/EngineWarning";
import { OpenDecisionButton } from "@/components/campaign/OpenDecisionButton";
import { getCampaign, getEscalations } from "@/lib/reads";
import { reasonSentence } from "@/lib/reason";
import { Banner, Hero } from "@/components/kit";
import { SortableTable } from "@/components/kit/SortableTable";

// the stages in pipeline order, for sorting the round history by stage
const STAGE_ORDER = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"];

function mmss(s: number) {
  const m = Math.floor(s / 60);
  return `${m} min`;
}

export default async function CampaignPage({ params }: { params: Promise<{ campaignId: string }> }) {
  const { campaignId } = await params;
  const [live, liveEscalations] = await Promise.all([getCampaign(campaignId), getEscalations()]);
  const c = live.data;
  if (!c) {
    // Never a sample campaign in its place: say what is actually the case. A campaign just started is checked for half a
    // minute and then said not to be recorded (a mistyped or deleted id must not promise it will appear); an API that does
    // not answer is asked again less and less often, up to every 30 s.
    return (
      <main>
        <Hero tone="run" eyebrow="Campaign" title={<code>{campaignId}</code>} />
        {live.notFound ? (
          <AutoRefresh active giveUpAfterMs={30_000} gaveUp={
            <div className="banner warn" role="status" data-testid="campaign-not-found">
              No campaign with this id is recorded. Open it from its project&apos;s Run step, or from <Link href="/">Projects</Link>.
            </div>}>
            <Banner tone="warn" testId="campaign-pending">
              This campaign is not recorded yet. A campaign you have just started appears within a few seconds; this page
              checks again on its own for half a minute.
            </Banner>
          </AutoRefresh>
        ) : (
          <>
            <ApiProblem problem={live.problem ?? "The campaign could not be read."} />
            <AutoRefresh active backoff />
          </>
        )}
      </main>
    );
  }
  const gof = c.gof ?? [];
  const budgetPct = Math.min(100, Math.round((c.elapsedSeconds / c.budgetSeconds) * 100));
  // ICH M15 acceptance tiers: the stricter the model risk, the tighter the fold limit the model must meet.
  const foldLimit = c.modelRisk === "high" ? 1.25 : c.modelRisk === "low" ? 2 : 1.5;
  const rows = c.stages.flatMap((s) => s.rounds.map((r) => ({ stage: s.stage, ...r })));
  const prediction = c.prediction ?? null;
  const pkg = c.package ?? null;
  const artifacts = pkg
    ? [...(pkg.exportable ? ["package.zip"] : []),
       ...["pdf", "docx", "md"].filter((f) => pkg.report?.[f]).map((f) => `mar.${f}`)]
    : [];
  const testOnly = Object.entries(c.realData ?? {}).filter(([, d]) => d.judged > 0 && !d.passable);
  const fmt = (v: number) => (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toPrecision(3));
  // a decision this campaign waits for: the page says so and opens it (the dialog may have been put off); the
  // external-validation banner below already does when that is the reason
  const waitingOn = (liveEscalations.data ?? []).find((e) => e.campaignId === c.id) ?? null;
  const decisionBanner = !c.feedbackPending && (waitingOn !== null || (c.status === "ESCALATED" && liveEscalations.problem !== null));
  const cycles = (c.cycle ?? 1) > 1; // a feedback cycle ran: rounds and changes say which cycle they belong to

  return (
    <main>
      <Hero tone="run" eyebrow="Campaign" title={c.compound} lede={c.question}
            actions={<>{c.status && <span data-testid="campaign-status"><StatusChip status={c.status} /></span>}
              <RiskChip rating={c.modelRisk} /></>} />
      <p className="muted fs-12 mt-6">
        Campaign <code>{c.id}</code> · acceptance within {foldLimit}-fold at {c.modelRisk} model risk
        {c.internalTargetPe != null && (
          <span data-testid="internal-target"> and, for the internal studies, |prediction error| ≤ {c.internalTargetPe} % (the signed MAP)</span>
        )}
      </p>
      <EngineWarning engine={c.engine} />
      {c.engine?.kind === "pksim" && (
        <p className="muted fs-12 mt-0">Engine: PK-Sim (<code>{c.engine.command}</code>)</p>
      )}
      {testOnly.length > 0 && (
        <Banner tone="err" className="mb-14" testId="real-data-warning">
          <strong>TEST ONLY: no real observed data.</strong> {testOnly.map(([stage, d]) => `${stage}: ${d.label}`).join(" · ")}.
          {" "}A verdict judged on synthetic, illustrative or unrecorded data is not evidence; the S4/S5 evaluation cannot be
          signed in a project that is not exploratory.
        </Banner>
      )}
      {decisionBanner && (
        <div className="banner warn mb-14" role="status" data-testid="escalation-pending">
          {waitingOn
            ? <>Stage {waitingOn.stage} is waiting for your signed decision: {reasonSentence(waitingOn.reasonCode)}.{" "}
                <OpenDecisionButton campaignId={c.id} /></>
            : <>Stage {c.currentStage} stopped for a decision, but the open decisions could not be read
                {" "}({liveEscalations.problem}). <OpenDecisionButton campaignId={c.id} /></>}
        </div>
      )}
      <AutoRefresh active={c.status === "RUNNING" || c.status === "QUEUED"} />
      {(c.status === "RUNNING" || c.status === "QUEUED") && <EscalationsExpected />}

      <Card title="Stage progress" action={<span className="muted">current: {c.currentStage}</span>}>
        <div className="timeline">
          {c.stages.map((s) => (
            <div key={s.stage} className={`stage ${s.status.toLowerCase()}`} data-testid={`campaign-stage-${s.stage}`}>
              <div className="st-name">{s.stage}</div>
              <div className="st-sub">{s.label}</div>
              <div className="mt-6"><StatusChip status={s.status === "PENDING" ? "PROPOSED" : s.status} /></div>
            </div>
          ))}
        </div>
        {c.stages.some((s) => s.notes?.length) && (
          <ul className="stage-notes" aria-label="Stage notes">
            {c.stages.flatMap((s) =>
              (s.notes ?? []).map((note, i) => (
                <li key={`${s.stage}-${i}`}><span className="sn-stage">{s.stage}</span><span>{note}</span></li>
              )),
            )}
          </ul>
        )}
        <div className="mt-18">
          <div className="spread mb-4">
            <span className="muted">Time budget</span>
            <span className="muted tnum">
              {mmss(c.elapsedSeconds)} / {mmss(c.budgetSeconds)} ({budgetPct}%)
            </span>
          </div>
          <div className="meter"><span style={{ width: `${budgetPct}%` }} /></div>
        </div>
      </Card>

      <Card title="Goodness of fit" action={<span className="muted">predicted vs observed</span>}>
        <ConcentrationTimePlot series={gof} />
      </Card>

      <Card title="Round history" action={<span className="muted">each round&apos;s agreement with the observed data</span>}>
        {/* sortable by its heads; the default is the order the rounds ran, the newest 20 shown first (audit item 11) */}
        <SortableTable testId="round-history" label="Round history" noun="rounds" pageSize={20} tail
                       columns={[
                         { key: "stage", label: "Stage" },
                         ...(cycles ? [{ key: "cycle", label: "Cycle", numeric: true }] : []),
                         { key: "round", label: "Round", numeric: true }, { key: "action", label: "Action" },
                         { key: "auc", label: "AUC vs observed" }, { key: "cmax", label: "Cmax vs observed" },
                         { key: "judged", label: "Judged studies", className: "muted" }, { key: "verdict", label: "Verdict" },
                       ]}
                       rows={rows.map((r, i) => ({
                         key: String(i),
                         cells: [
                           r.stage,
                           ...(cycles ? [r.cycle ?? 1] : []),
                           r.round,
                           <code key="a">{r.action}</code>,
                           <FoldError key="auc" ratio={r.aucGmfe ?? null} limit={foldLimit} label={`${r.stage} round ${r.round} AUC`} />,
                           <FoldError key="cmax" ratio={r.cmaxGmfe ?? null} limit={foldLimit} label={`${r.stage} round ${r.round} Cmax`} />,
                           <span key="j" title={Object.entries(r.realData?.byOrigin ?? {}).map(([o, n]) => `${o.toLowerCase().replace("_", " ")} ${n}`).join(", ")}>
                             {r.realData ? `${r.realData.real} of ${r.realData.judged} real` : "—"}</span>,
                           r.verdict === "passed" ? <span key="v" className="chip low">passed</span>
                             : r.realData && r.realData.judged > 0 && !r.realData.passable ? <span key="v" className="chip high">{r.verdict}</span> : r.verdict,
                         ],
                         sort: [
                           STAGE_ORDER.indexOf(r.stage) < 0 ? STAGE_ORDER.length : STAGE_ORDER.indexOf(r.stage),
                           ...(cycles ? [r.cycle ?? 1] : []),
                           r.round, r.action, r.aucGmfe ?? null, r.cmaxGmfe ?? null,
                           r.realData ? r.realData.real : null, r.verdict ?? null,
                         ],
                       }))} />
      </Card>

      {(c.feedbackPending || (c.feedback?.length ?? 0) > 0) && (
        <Card title="External-validation feedback" action={<span className="muted">cycle {c.cycle ?? 1}</span>}>
          {(c.feedback?.length ?? 0) > 0 && <FeedbackTimeline decisions={c.feedback!} />}
          {c.feedbackPending && (
            <>
              <Banner tone="warn" className="m-8-0" testId="feedback-pending">
                External validation failed: a signed decision is needed — record a limitation, learn from the failing
                study, bring new evidence, or stop. <OpenDecisionButton campaignId={c.id} />
              </Banner>
              <FeedbackDiagnosisView diagnosis={c.feedbackPending} />
            </>
          )}
        </Card>
      )}

      {(c.ledger?.entries.length ?? 0) > 0 && (
        <Card title="Model development history" action={<span className="muted">each parameter change and the verdicts it moved</span>}>
          <LedgerTable entries={c.ledger!.entries} />
        </Card>
      )}

      {c.influence && c.influence.parameters.length > 0 && (
        <Card title="Influence map" action={<span className="muted">parameters × studies</span>}>
          <InfluenceHeatMap map={c.influence} />
        </Card>
      )}

      {prediction && (
        <Card title="Prediction (S6)" action={<span className="muted">what the validated model's predictions rest on</span>}>
          {Object.entries(prediction.sensitivity ?? {}).length > 0 && (
            <table>
              <thead><tr><th>Study</th><th>Most influential parameter</th><th>PK parameter</th><th className="num">Sensitivity</th></tr></thead>
              <tbody>
                {Object.entries(prediction.sensitivity ?? {}).flatMap(([study, ranked]) =>
                  ranked.slice(0, 3).map((r, i) => (
                    <tr key={`${study}-${i}`}>
                      <td>{i === 0 ? study : ""}</td><td><code>{r.parameter}</code></td><td>{r.pk_parameter}</td>
                      <td className="num">{r.value.toFixed(3)}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          )}
          {Object.entries(prediction.intervals ?? {}).length > 0 && (
            <table className="mt-14">
              <thead><tr><th>Study</th><th>Quantity</th><th className="num">5th percentile</th><th className="num">Median</th><th className="num">95th percentile</th><th className="num">Runs</th></tr></thead>
              <tbody>
                {Object.entries(prediction.intervals ?? {}).flatMap(([study, pk]) =>
                  (["AUC", "Cmax"] as const).filter((q) => pk[q]?.n).map((q) => (
                    <tr key={`${study}-${q}`}>
                      <td>{q === "AUC" ? study : ""}</td><td>{q}</td>
                      <td className="num">{fmt(pk[q]!.p5)}</td><td className="num">{fmt(pk[q]!.p50)}</td>
                      <td className="num">{fmt(pk[q]!.p95)}</td><td className="num">{pk[q]!.n}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {prediction?.vbe && <VbeCard vbe={prediction.vbe} />}

      {pkg && (
        <Card title="Report and package (S7)"
              action={pkg.reproduction?.passes
                ? <span className="chip low">reproduced · {pkg.reproduction.compared} tables</span>
                : <span className="chip high">not reproduced</span>}>
          <p className="muted mt-0">
            {pkg.exportable
              ? "Every bundled simulation was re-run on a fresh engine and matched its recorded results, so the package is released."
              : "The re-run did not reproduce every recorded result, so the package is withheld; the report explains which table differed."}
          </p>
          {pkg.data_bundle_sha256 && (
            <p className="muted fs-12">Data bundle <code>sha256 {pkg.data_bundle_sha256.slice(0, 16)}…</code>
              {pkg.files ? ` · ${pkg.files} files` : ""}</p>
          )}
          <PackageDownloads campaignId={c.id} artifacts={artifacts} />
        </Card>
      )}
    </main>
  );
}
