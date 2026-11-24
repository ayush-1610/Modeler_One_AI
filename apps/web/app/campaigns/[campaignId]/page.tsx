import Link from "next/link";
import type { ReactNode } from "react";

import { AutoRefresh } from "@/components/AutoRefresh";
import { FoldError } from "@/components/FoldError";
import { PackageDownloads } from "@/components/PackageDownloads";
import { RiskBadge } from "@/components/kit/Badge";
import { StatusIndicator } from "@/components/kit/StatusIndicator";
import { FeedbackDiagnosisView, FeedbackTimeline } from "@/components/campaign/Feedback";
import { InfluenceHeatMap, LedgerTable } from "@/components/campaign/History";
import { VbeCard } from "@/components/campaign/Vbe";
import { OpenDecisionButton } from "@/components/campaign/OpenDecisionButton";
import { Chart } from "@/components/kit/Chart";
import { getCampaign, getCampaignPackage } from "@/lib/reads";
import { ApiProblem, Hero } from "@/components/kit";
import { SortableTable } from "@/components/kit/SortableTable";

// A campaign (P-16, the console redesign's slice 6): what it is and whether its numbers are PBPK evidence, said above
// everything (the fixture and test-data banners stay, mandatory), then one part at a time in tabs whose choice is in
// the address (?tab=): the stages, the fit, the rounds, the external-validation feedback, the S6 prediction when there
// is one, and the S7 package (`GET /campaigns/{id}/package`). A waiting decision is asked from the flash bar above the
// page (EscalationPopup), the feedback tab's banner opening the same dialog. Raw run results (the "Runs" tab of the
// page inventory) wait for the multi-server deployment (R-N08), so no tab promises them.

// the stages in pipeline order, for sorting the round history by stage
const STAGE_ORDER = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"];
const TABS = ["stages", "fit", "rounds", "feedback", "prediction", "package"] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = {
  stages: "Stages", fit: "Fit", rounds: "Rounds", feedback: "Feedback", prediction: "Prediction (S6)", package: "Package (S7)",
};

function minutes(s: number) {
  return `${Math.floor(s / 60)} min`;
}

function Panel({ title, aside, children, testId }: { title: string; aside?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <section className="panel" data-testid={testId}>
      <div className="panel-head"><h2>{title}</h2><span className="grow" />{aside && <span className="muted fs-13">{aside}</span>}</div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export default async function CampaignPage({ params, searchParams }: {
  params: Promise<{ campaignId: string }>; searchParams: Promise<{ tab?: string }>;
}) {
  const { campaignId } = await params;
  const { tab: asked } = await searchParams;
  const live = await getCampaign(campaignId);
  const c = live.data;
  if (!c) {
    // Never a sample campaign in its place: say what is actually the case, and keep checking.
    return (
      <main>
        <Hero tone="run" eyebrow="Campaign" title={<code>{campaignId}</code>} />
        {live.notFound ? (
          <div className="banner warn" data-testid="campaign-pending">
            This campaign is not recorded yet. A campaign you have just started appears within a few seconds;
            this page checks again on its own. If it never appears, the API log says why it did not start.
          </div>
        ) : (
          <ApiProblem problem={live.problem ?? "The campaign could not be read."} />
        )}
        <AutoRefresh active />
      </main>
    );
  }
  const gof = c.gof ?? [];
  const budgetPct = c.budgetSeconds > 0 ? Math.min(100, Math.round((c.elapsedSeconds / c.budgetSeconds) * 100)) : 0;
  // ICH M15 acceptance tiers: the stricter the model risk, the tighter the fold limit the model must meet.
  const foldLimit = c.modelRisk === "high" ? 1.25 : c.modelRisk === "low" ? 2 : 1.5;
  const rows = c.stages.flatMap((s) => s.rounds.map((r) => ({ stage: s.stage, ...r })));
  const prediction = c.prediction ?? null;
  const testOnly = Object.entries(c.realData ?? {}).filter(([, d]) => d.judged > 0 && !d.passable);
  const fmt = (v: number) => (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toPrecision(3));
  const cycles = (c.cycle ?? 1) > 1; // a feedback cycle ran: rounds and changes say which cycle they belong to
  const feedbackCount = c.feedback?.length ?? 0;

  // the tabs this campaign has: Prediction only once S6 has given one
  const tabs = TABS.filter((t) => t !== "prediction" || prediction);
  const tab: Tab = tabs.find((t) => t === asked) ?? "stages";
  const count: Partial<Record<Tab, ReactNode>> = {
    rounds: rows.length, feedback: c.feedbackPending ? "decision waiting" : feedbackCount || null,
  };
  // the package as the API answers it (its issues, its PK-Sim projects), read only on its tab
  const pkgLive = tab === "package" && c.package ? await getCampaignPackage(c.id) : null;
  const pkg = pkgLive?.data ?? null;
  const base = `/campaigns/${encodeURIComponent(c.id)}`;

  return (
    <main>
      <Hero tone="run" eyebrow="Campaign" title={c.compound} lede={c.question}
            actions={<>{c.status && <span data-testid="campaign-status"><StatusIndicator status={c.status} /></span>}
              <RiskBadge rating={c.modelRisk} /></>} />
      <dl className="kv-list kv-inline" data-testid="campaign-facts">
        <dt>Campaign</dt><dd><code>{c.id}</code></dd>
        <dt>Acceptance</dt><dd>within {foldLimit}-fold at {c.modelRisk} model risk
          {c.internalTargetPe != null && (
            <span data-testid="internal-target"> and, for the internal studies, |prediction error| ≤ {c.internalTargetPe} % (the signed MAP)</span>
          )}</dd>
        <dt>Current stage</dt><dd>{c.currentStage}</dd>
        {c.engine?.kind === "pksim" && <><dt>Engine</dt><dd>PK-Sim (<code>{c.engine.command}</code>)</dd></>}
      </dl>
      {c.engine && c.engine.kind !== "pksim" && (
        <div className="banner err mb-14" data-testid="engine-warning">
          {c.engine.kind === "software-fixture"
            ? <>Not a PBPK result: this campaign ran on a software test fixture (<code>{c.engine.command}</code>). Its
                curves are synthetic; it checks the software path only. Run on PK-Sim for model evidence.</>
            : <>The engine this campaign ran on is not identified as PK-Sim (<code>{c.engine.command}</code>). Treat
                its numbers as unverified.</>}
        </div>
      )}
      {testOnly.length > 0 && (
        <div className="banner err mb-14" data-testid="real-data-warning">
          <strong>TEST ONLY: no real observed data.</strong> {testOnly.map(([stage, d]) => `${stage}: ${d.label}`).join(" · ")}.
          {" "}A verdict judged on synthetic, illustrative or unrecorded data is not evidence; the S4/S5 evaluation cannot be
          signed in a project that is not exploratory.
        </div>
      )}
      <AutoRefresh active={c.status === "RUNNING" || c.status === "QUEUED"} />

      <nav className="tabs page-tabs" aria-label="Campaign" data-testid="campaign-tabs">
        {tabs.map((t) => (
          <Link key={t} href={`${base}?tab=${t}`} prefetch={false} scroll={false} aria-current={t === tab ? "page" : undefined}
                data-testid={`campaign-tab-${t}`}>
            {TAB_LABEL[t]}{count[t] != null && count[t] !== 0 && <span className="tab-count">{count[t]}</span>}
          </Link>
        ))}
      </nav>

      {tab === "stages" && (
        <>
          <Panel title="Stages" aside={`current: ${c.currentStage}`}>
            <div className="tbl-scroll">
              <table data-testid="campaign-stages">
                <thead><tr><th scope="col">Stage</th><th scope="col">What it does</th><th scope="col">Status</th>
                  <th scope="col" className="num">Rounds</th></tr></thead>
                <tbody>
                  {c.stages.map((s) => (
                    <tr key={s.stage} className={s.stage === c.currentStage ? "current" : undefined} data-testid={`campaign-stage-${s.stage}`}>
                      <td><strong>{s.stage}</strong></td><td>{s.label}</td>
                      <td><StatusIndicator status={s.status === "PENDING" ? "PROPOSED" : s.status} /></td>
                      <td className="num">{s.rounds.length || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
          </Panel>
          <Panel title="Time budget" aside="the signed MAP's">
            <div className="spread mb-4">
              <span className="muted">Used</span>
              <span className="muted tnum">{minutes(c.elapsedSeconds)} / {minutes(c.budgetSeconds)} ({budgetPct}%)</span>
            </div>
            <div className="meter" role="meter" aria-label="Time budget used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={budgetPct}>
              <span style={{ width: `${budgetPct}%` }} />
            </div>
          </Panel>
        </>
      )}

      {tab === "fit" && (
        <Panel title="Goodness of fit" aside="predicted against observed">
          <Chart series={gof} label="Goodness of fit: predicted and observed plasma concentrations" testId="gof-chart"
                 empty="No fit yet: the predicted and observed concentrations appear once a stage has run." />
        </Panel>
      )}

      {tab === "rounds" && (
        <>
          <Panel title="Round history" aside="each round's agreement with the observed data">
            {/* sortable by its heads; the default is the order the rounds ran, the newest 20 shown first (audit item 11) */}
            {rows.length === 0 ? <p className="muted m-0">No round has run yet.</p> : (
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
            )}
          </Panel>
          {(c.ledger?.entries.length ?? 0) > 0 && (
            <Panel title="Model development history" aside="each parameter change and the verdicts it moved">
              <LedgerTable entries={c.ledger!.entries} />
            </Panel>
          )}
          {c.influence && c.influence.parameters.length > 0 && (
            <Panel title="Influence map" aside="parameters × studies">
              <InfluenceHeatMap map={c.influence} />
            </Panel>
          )}
        </>
      )}

      {tab === "feedback" && (
        <Panel title="External-validation feedback" aside={`cycle ${c.cycle ?? 1}`}>
          {!c.feedbackPending && feedbackCount === 0 && (
            <p className="muted m-0" data-testid="feedback-none">No external-validation feedback: S5 has not failed in this campaign.</p>
          )}
          {feedbackCount > 0 && <FeedbackTimeline decisions={c.feedback!} />}
          {c.feedbackPending && (
            <>
              <div className="banner warn m-8-0" data-testid="feedback-pending">
                External validation failed: a signed decision is needed — record a limitation, learn from the failing
                study, bring new evidence, or stop. <OpenDecisionButton campaignId={c.id} />
              </div>
              <FeedbackDiagnosisView diagnosis={c.feedbackPending} />
            </>
          )}
        </Panel>
      )}

      {tab === "prediction" && prediction && (
        <>
          <Panel title="Prediction (S6)" aside="what the validated model's predictions rest on">
            {Object.entries(prediction.sensitivity ?? {}).length > 0 && (
              <div className="tbl-scroll">
                <table>
                  <caption className="sr-only">The most influential parameters of each study</caption>
                  <thead><tr><th scope="col">Study</th><th scope="col">Most influential parameter</th><th scope="col">PK parameter</th>
                    <th scope="col" className="num">Sensitivity</th></tr></thead>
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
              </div>
            )}
            {Object.entries(prediction.intervals ?? {}).length > 0 && (
              <div className="tbl-scroll mt-14">
                <table>
                  <caption className="sr-only">Prediction intervals</caption>
                  <thead><tr><th scope="col">Study</th><th scope="col">Quantity</th><th scope="col" className="num">5th percentile</th>
                    <th scope="col" className="num">Median</th><th scope="col" className="num">95th percentile</th><th scope="col" className="num">Runs</th></tr></thead>
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
              </div>
            )}
          </Panel>
          {prediction.vbe && <VbeCard vbe={prediction.vbe} />}
        </>
      )}

      {tab === "package" && (
        !c.package ? (
          <Panel title="Report and package (S7)">
            <p className="muted m-0" data-testid="package-none">No package yet: S7 writes the report and the package once the
              campaign reaches it.</p>
          </Panel>
        ) : !pkg ? (
          <Panel title="Report and package (S7)">
            <ApiProblem problem={pkgLive?.problem ?? "The package could not be read."} />
          </Panel>
        ) : (
          <Panel title="Report and package (S7)" testId="campaign-package"
                 aside={pkg.reproduction?.passes ? "reproduced" : "not reproduced"}>
            <p className="muted mt-0">
              {pkg.exportable
                ? "Every bundled simulation was re-run on a fresh engine and matched its recorded results, so the package is released."
                : "The re-run did not reproduce every recorded result, so the package is withheld; the report explains which table differed."}
            </p>
            <dl className="kv-list" data-testid="package-facts">
              <dt>Reproduction</dt>
              <dd>{pkg.reproduction?.passes
                ? <span className="chip low">reproduced · {String(pkg.reproduction.compared ?? "")} tables</span>
                : <span className="chip high">not reproduced</span>}</dd>
              <dt>Released</dt><dd>{pkg.exportable ? "yes" : "no: offered only when every bundled simulation re-runs identically"}</dd>
              {pkg.package_sha256 && <><dt>Package</dt><dd><code>sha256 {pkg.package_sha256.slice(0, 16)}…</code></dd></>}
              {pkg.data_bundle_sha256 && <><dt>Data bundle</dt><dd><code>sha256 {pkg.data_bundle_sha256.slice(0, 16)}…</code>
                {pkg.files ? ` · ${pkg.files} files` : ""}</dd></>}
              <dt>PK-Sim projects</dt>
              <dd data-testid="package-pksim">{pkg.pksim_projects.length
                ? <ul className="list-plain">{pkg.pksim_projects.map((p) => <li key={p}><code>{p}</code></li>)}</ul>
                : <span className="muted">none in the package</span>}
                {pkg.project_notes.length > 0 && <ul className="flags">{pkg.project_notes.map((n) => <li key={n}>{n}</li>)}</ul>}</dd>
            </dl>
            {pkg.report_issues.length > 0 && (
              <div className="tbl-scroll mt-14" data-testid="package-issues">
                <table>
                  <caption className="sr-only">What the report check found</caption>
                  <thead><tr><th scope="col">Issue</th><th scope="col">Where</th><th scope="col">Detail</th></tr></thead>
                  <tbody>
                    {pkg.report_issues.map((i, n) => (
                      <tr key={n}><td>{i.kind.replace(/_/g, " ")}</td><td><code>{i.location}</code></td><td>{i.detail}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {pkg.report_notes.length > 0 && <ul className="flags mt-8">{pkg.report_notes.map((n) => <li key={n}>{n}</li>)}</ul>}
            <div className="mt-14"><PackageDownloads campaignId={c.id} artifacts={pkg.artifacts} /></div>
          </Panel>
        )
      )}
    </main>
  );
}
