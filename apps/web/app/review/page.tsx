import { Card } from "@/components/ui";
import { EscalationDecision } from "@/components/EscalationDecision";
import { ESCALATIONS, PROPOSALS } from "@/lib/fixtures";

export default function ReviewInbox() {
  return (
    <main>
      <h1>Review inbox</h1>
      <p className="muted">Curator and reviewer actions: agent parameter proposals awaiting acceptance, and campaign
        escalations that resume only through a signed decision.</p>

      <Card title="Parameter proposals" action={<span className="chip medium">{PROPOSALS.length} pending</span>}>
        <table>
          <thead>
            <tr><th>Parameter</th><th className="num">Value</th><th>Citation</th><th>Agent</th><th></th></tr>
          </thead>
          <tbody>
            {PROPOSALS.map((p) => (
              <tr key={p.id}>
                <td><code>{p.parameterId}</code></td>
                <td className="num">{p.value} {p.unit}</td>
                <td>
                  <div>&ldquo;{p.quote}&rdquo;</div>
                  <div className="muted" style={{ fontSize: 12 }}>{p.reference}</div>
                </td>
                <td className="muted">{p.agent}</td>
                <td>
                  <div className="row">
                    <button className="btn primary">Accept</button>
                    <button className="btn">Reject</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
          Every proposal carries an exact citation checked deterministically; a curator accepts or rejects each one
          before it can enter a model.
        </p>
      </Card>

      {ESCALATIONS.map((e) => (
        <Card key={e.id} title={`Escalation — campaign ${e.campaignId}, stage ${e.stage}`}>
          <EscalationDecision escalation={e} />
        </Card>
      ))}
    </main>
  );
}
