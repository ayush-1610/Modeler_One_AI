import { Card, RiskChip, StatusChip } from "@/components/ui";
import { ConcentrationTimePlot } from "@/components/ConcentrationTimePlot";
import { CAMPAIGN, GOF } from "@/lib/fixtures";

function mmss(s: number) {
  const m = Math.floor(s / 60);
  return `${m} min`;
}

export default async function CampaignPage({ params }: { params: Promise<{ campaignId: string }> }) {
  await params;
  const c = CAMPAIGN;
  const budgetPct = Math.min(100, Math.round((c.elapsedSeconds / c.budgetSeconds) * 100));
  const rows = c.stages.flatMap((s) => s.rounds.map((r) => ({ stage: s.stage, ...r })));

  return (
    <main>
      <div className="spread">
        <h1>Campaign {c.id}</h1>
        <RiskChip rating={c.modelRisk} />
      </div>
      <p className="muted">{c.question}</p>

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

      <div className="cols-2">
        <Card title="Goodness of fit — stage S2">
          <ConcentrationTimePlot series={GOF} />
        </Card>

        <Card title="Round history">
          <table>
            <thead>
              <tr><th>Stage</th><th className="num">Round</th><th>Action</th><th className="num">AUC GMFE</th><th className="num">Cmax GMFE</th><th>Verdict</th></tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>{r.stage}</td>
                  <td className="num">{r.round}</td>
                  <td><code>{r.action}</code></td>
                  <td className="num">{r.aucGmfe?.toFixed(2) ?? "—"}</td>
                  <td className="num">{r.cmaxGmfe?.toFixed(2) ?? "—"}</td>
                  <td>{r.verdict === "passed" ? <span className="chip low">passed</span> : r.verdict}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </main>
  );
}
