import { AutoRefresh } from "@/components/AutoRefresh";
import { FoldError } from "@/components/FoldError";
import { PackageDownloads } from "@/components/PackageDownloads";
import { ApiProblem, Card, RiskChip, StatusChip } from "@/components/ui";
import { ConcentrationTimePlot } from "@/components/ConcentrationTimePlot";
import { getCampaign } from "@/lib/reads";

function mmss(s: number) {
  const m = Math.floor(s / 60);
  return `${m} min`;
}

export default async function CampaignPage({ params }: { params: Promise<{ campaignId: string }> }) {
  const { campaignId } = await params;
  const live = await getCampaign(campaignId);
  const c = live.data;
  if (!c) {
    // Never a sample campaign in its place: say what is actually the case, and keep checking.
    return (
      <main>
        <h1>Campaign <code>{campaignId}</code></h1>
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
  const fmt = (v: number) => (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toPrecision(3));

  return (
    <main>
      <div className="spread">
        <div style={{ minWidth: 0 }}>
          <h1>{c.compound}</h1>
          <p className="muted" style={{ margin: 0 }}>{c.question}</p>
        </div>
        <div className="row" style={{ gap: 8, flexShrink: 0 }}>
          {c.status && <StatusChip status={c.status} />}
          <RiskChip rating={c.modelRisk} />
        </div>
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
        Campaign <code>{c.id}</code> · acceptance within {foldLimit}-fold at {c.modelRisk} model risk
      </p>
      {c.engine && c.engine.kind !== "pksim" && (
        <div className="banner err" data-testid="engine-warning" style={{ marginBottom: 14 }}>
          {c.engine.kind === "software-fixture"
            ? <>Not a PBPK result: this campaign ran on a software test fixture (<code>{c.engine.command}</code>). Its
                curves are synthetic; it checks the software path only. Run on PK-Sim for model evidence.</>
            : <>The engine this campaign ran on is not identified as PK-Sim (<code>{c.engine.command}</code>). Treat
                its numbers as unverified.</>}
        </div>
      )}
      {c.engine?.kind === "pksim" && (
        <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>Engine: PK-Sim (<code>{c.engine.command}</code>)</p>
      )}
      <AutoRefresh active={c.status === "RUNNING" || c.status === "QUEUED"} />

      <Card title="Stage progress" action={<span className="muted">current: {c.currentStage}</span>}>
        <div className="timeline">
          {c.stages.map((s) => (
            <div key={s.stage} className={`stage ${s.status.toLowerCase()}`}>
              <div className="st-name">{s.stage}</div>
              <div className="st-sub">{s.label}</div>
              <div style={{ marginTop: 6 }}><StatusChip status={s.status === "PENDING" ? "PROPOSED" : s.status} /></div>
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
        <div style={{ marginTop: 18 }}>
          <div className="spread" style={{ marginBottom: 4 }}>
            <span className="muted">Time budget</span>
            <span className="muted" style={{ fontVariantNumeric: "tabular-nums" }}>
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
          <table>
            <thead>
              <tr><th>Stage</th><th className="num">Round</th><th>Action</th><th>AUC vs observed</th><th>Cmax vs observed</th><th>Verdict</th></tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>{r.stage}</td>
                  <td className="num">{r.round}</td>
                  <td><code>{r.action}</code></td>
                  <td><FoldError ratio={r.aucGmfe ?? null} limit={foldLimit} label={`${r.stage} round ${r.round} AUC`} /></td>
                  <td><FoldError ratio={r.cmaxGmfe ?? null} limit={foldLimit} label={`${r.stage} round ${r.round} Cmax`} /></td>
                  <td>{r.verdict === "passed" ? <span className="chip low">passed</span> : r.verdict}</td>
                </tr>
              ))}
            </tbody>
        </table>
      </Card>

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
            <table style={{ marginTop: 14 }}>
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

      {pkg && (
        <Card title="Report and package (S7)"
              action={pkg.reproduction?.passes
                ? <span className="chip low">reproduced · {pkg.reproduction.compared} tables</span>
                : <span className="chip high">not reproduced</span>}>
          <p className="muted" style={{ marginTop: 0 }}>
            {pkg.exportable
              ? "Every bundled simulation was re-run on a fresh engine and matched its recorded results, so the package is released."
              : "The re-run did not reproduce every recorded result, so the package is withheld; the report explains which table differed."}
          </p>
          {pkg.data_bundle_sha256 && (
            <p className="muted" style={{ fontSize: 12 }}>Data bundle <code>sha256 {pkg.data_bundle_sha256.slice(0, 16)}…</code>
              {pkg.files ? ` · ${pkg.files} files` : ""}</p>
          )}
          <PackageDownloads campaignId={c.id} artifacts={artifacts} />
        </Card>
      )}
    </main>
  );
}
