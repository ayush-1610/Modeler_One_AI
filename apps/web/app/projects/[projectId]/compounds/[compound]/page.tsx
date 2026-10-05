import { ApiProblem, Card, Completeness, ProvenanceChip } from "@/components/ui";
import { MEASURED_SOURCES } from "@/lib/types";
import { getCompoundCpf } from "@/lib/reads";

export default async function CompoundPage({ params }: { params: Promise<{ projectId: string; compound: string }> }) {
  const { projectId, compound } = await params;
  const live = await getCompoundCpf(projectId, compound);
  const cpf = live.data;
  if (!cpf) {
    return (
      <main>
        <h1>{decodeURIComponent(compound)} — Compound Parameter Framework</h1>
        <ApiProblem problem={live.problem ?? `No CPF for ${decodeURIComponent(compound)} in project ${projectId} yet.`} />
      </main>
    );
  }
  const fitted = cpf.parameters.filter((p) => p.source === "ParameterIdentification").length;
  const measured = cpf.parameters.filter((p) => MEASURED_SOURCES.includes(p.source)).length;

  return (
    <main>
      <div className="spread">
        <h1>{cpf.name} — Compound Parameter Framework</h1>
        <span className="chip brand">CPF v{cpf.version}</span>
      </div>
      <p className="muted">
        The CPF is the system of record: every simulation is regenerated from it. Each parameter shows its value,
        provenance and the stages in which it may be fitted.
      </p>

      <Card>
        <div className="kpi">
          <div className="k"><div className="v">{cpf.parameters.length}</div><div className="l">parameters</div></div>
          <div className="k"><div className="v">{measured}</div><div className="l">measured / literature</div></div>
          <div className="k"><div className="v">{fitted}</div><div className="l">fitted (PI)</div></div>
          <div className="k">
            <div className="v">{Math.round(cpf.completeness * 100)}%</div>
            <div className="l">S0 readiness</div>
          </div>
        </div>
        <div style={{ marginTop: 12 }}><Completeness value={cpf.completeness} /></div>
      </Card>

      <Card title="Parameters">
        <table>
          <thead>
            <tr>
              <th>Parameter</th><th className="num">Value</th><th>Unit</th><th>Provenance</th>
              <th>Reference</th><th>Fittable stages</th>
            </tr>
          </thead>
          <tbody>
            {cpf.parameters.map((p) => (
              <tr key={p.id}>
                <td><code>{p.id}</code></td>
                <td className="num">{p.value ?? "—"}</td>
                <td>{p.unit || <span className="muted">—</span>}</td>
                <td><ProvenanceChip source={p.source} /></td>
                <td className="muted">{p.reference || "—"}</td>
                <td>{p.fittableStages.length ? p.fittableStages.join(", ") : <span className="muted">fixed</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </main>
  );
}
