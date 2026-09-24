import { ApiProblem, Card } from "@/components/ui";
import { EscalationDecision } from "@/components/EscalationDecision";
import { getEscalations, getProposals } from "@/lib/reads";

export default async function ReviewInbox() {
  const [liveProposals, liveEscalations] = await Promise.all([getProposals(), getEscalations()]);
  const problem = liveEscalations.problem ?? liveProposals.problem;
  const proposals = liveProposals.data ?? [];
  const escalations = liveEscalations.data ?? [];

  return (
    <main>
      <h1>Review inbox</h1>
      <p className="muted">Curator and reviewer actions: agent parameter proposals awaiting acceptance, and campaign
        escalations that resume only through a signed decision.</p>
      {problem && <ApiProblem problem={problem} />}

      <Card
        title="Parameter proposals"
        action={proposals.length > 0 ? <span className="chip medium">{proposals.length} pending</span> : <span className="chip neutral">none</span>}
      >
        {proposals.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>
            Nothing awaiting review. When the literature-curation agent proposes a parameter value, it appears
            here with its exact citation for a curator to accept or reject before it can enter a model.
          </p>
        ) : (
          <>
            <table>
              <thead>
                <tr><th>Parameter</th><th className="num">Value</th><th>Citation</th><th>Agent</th><th></th></tr>
              </thead>
              <tbody>
                {proposals.map((p) => (
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
          </>
        )}
      </Card>

      {escalations.length === 0 ? (
        <Card title="Escalations" action={<span className="chip neutral">none</span>}>
          <p className="muted" style={{ margin: 0 }}>
            No campaign is waiting on a decision. When a stage exhausts its permitted actions or its budget, the
            campaign pauses here for a signed decision — it is never silently continued.
          </p>
        </Card>
      ) : (
        escalations.map((e) => (
          <Card key={e.id} title={`Escalation — campaign ${e.campaignId}, stage ${e.stage}`}>
            <EscalationDecision escalation={e} />
          </Card>
        ))
      )}
    </main>
  );
}
