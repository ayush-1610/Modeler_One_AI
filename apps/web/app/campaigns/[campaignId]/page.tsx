import { AutoRefresh } from "@/components/AutoRefresh";
import { FoldError } from "@/components/FoldError";
import { Card, RiskChip, StatusChip } from "@/components/ui";
import { ConcentrationTimePlot } from "@/components/ConcentrationTimePlot";
import { CAMPAIGN, GOF } from "@/lib/fixtures";
import { getCampaign } from "@/lib/reads";

function mmss(s: number) {
  const m = Math.floor(s / 60);
  return `${m} min`;
}

export default async function CampaignPage({ params }: { params: Promise<{ campaignId: string }> }) {
  const { campaignId } = await params;
  const live = await getCampaign(campaignId);
  const c = live ?? CAMPAIGN;
  const gof = live?.gof ?? GOF;
  const budgetPct = Math.min(100, Math.round((c.elapsedSeconds / c.budgetSeconds) * 100));
  // ICH M15 acceptance tiers: the stricter the model risk, the tighter the fold limit the model must meet.
  const foldLimit = c.modelRisk === "high" ? 1.25 : c.modelRisk === "low" ? 2 : 1.5;
  const rows = c.stages.flatMap((s) => s.rounds.map((r) => ({ stage: s.stage, ...r })));

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
      {!live && <div className="banner warn" style={{ marginBottom: 14 }}>Showing sample data — the API is not reachable.</div>}
      <AutoRefresh active={!!live && (c.status === "RUNNING" || c.status === "QUEUED")} />

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
    </main>
  );
}
