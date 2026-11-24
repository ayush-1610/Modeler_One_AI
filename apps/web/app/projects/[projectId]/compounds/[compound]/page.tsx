import { Panel } from "@/components/kit/Panel";
import { ProvenanceBadge } from "@/components/kit/Badge";
import { MEASURED_SOURCES } from "@/lib/types";
import { getCompoundCpf } from "@/lib/reads";
import { ApiProblem, Hero } from "@/components/kit";
import { Clip } from "@/components/kit/Clip";
import { SortableTable } from "@/components/kit/SortableTable";
import { numericKey } from "@/lib/tableSort";
import { paramLabel, unitText } from "@/lib/words";

export default async function CompoundPage({ params }: { params: Promise<{ projectId: string; compound: string }> }) {
  const { projectId, compound } = await params;
  // the segment arrives URL-encoded; the typed client encodes each path parameter itself
  const live = await getCompoundCpf(projectId, decodeURIComponent(compound));
  const cpf = live.data;
  if (!cpf) {
    return (
      <main>
        <Hero tone="inputs" eyebrow="Compound Parameter Framework" title={decodeURIComponent(compound)} />
        <ApiProblem problem={live.problem ?? `No values for ${decodeURIComponent(compound)} in this project yet: they are filled in on Inputs.`} />
      </main>
    );
  }
  const fitted = cpf.parameters.filter((p) => p.source === "ParameterIdentification").length;
  const measured = cpf.parameters.filter((p) => MEASURED_SOURCES.includes(p.source)).length;

  return (
    <main>
      <Hero tone="inputs" eyebrow={`Compound Parameter Framework · v${cpf.version}`} title={cpf.name}
            lede="The CPF is the system of record: every simulation is regenerated from it. Each parameter shows its value, provenance and the stages in which it may be fitted." />

      <Panel>
        <div className="kpi">
          <div className="k"><div className="v">{cpf.parameters.length}</div><div className="l">parameters</div></div>
          <div className="k"><div className="v">{measured}</div><div className="l">measured / literature</div></div>
          <div className="k"><div className="v">{fitted}</div><div className="l">fitted (PI)</div></div>
          <div className="k">
            <div className="v">{Math.round(cpf.completeness * 100)}%</div>
            <div className="l">S0 readiness</div>
          </div>
        </div>
        <div className="row gap-8 mt-12">
          <div className="meter w-120"><span style={{ width: `${Math.round(cpf.completeness * 100)}%` }} /></div>
          <span className="muted tnum">{Math.round(cpf.completeness * 100)}%</span>
        </div>
      </Panel>

      <Panel title="Parameters">
        {/* sortable, filterable, 50 rows at a time (the 2026-11-11 audit, item 11); the default order is the CPF's. Each
            parameter by its name in words (final review OWN-8); the CPF's own names are under "Technical detail" */}
        <SortableTable testId="cpf-parameters" label="Parameters" noun="parameters" pageSize={50} tableClassName="cpf-table"
                       filterPlaceholder="Filter parameters: name, unit, provenance, reference…"
                       columns={[
                         { key: "id", label: "Parameter" }, { key: "value", label: "Value", numeric: true }, { key: "unit", label: "Unit" },
                         { key: "source", label: "Provenance" }, { key: "reference", label: "Reference", className: "muted cpf-ref" },
                         { key: "stages", label: "Fittable stages" },
                       ]}
                       rows={cpf.parameters.map((p) => ({
                         key: p.id,
                         cells: [
                           <span key="id">{paramLabel(p.id)}</span>, p.value ?? "—", unitText(p.unit) || <span className="muted">—</span>,
                           <ProvenanceBadge key="src" source={p.source} />, <Clip key="ref" text={p.reference} max={90} />,
                           p.fittableStages.length ? p.fittableStages.join(", ") : <span className="muted">fixed</span>,
                         ],
                         // fixed parameters sort after the fittable ones
                         sort: [paramLabel(p.id), numericKey(p.value), unitText(p.unit) || null, p.source, p.reference || null,
                                p.fittableStages.length ? p.fittableStages.join(", ") : null],
                         filter: [paramLabel(p.id), p.id, unitText(p.unit), p.source, p.reference, p.fittableStages.join(" ")].filter(Boolean).join(" "),
                       }))} />
        <details className="mt-12" data-testid="cpf-technical">
          <summary>Technical detail: the CPF&apos;s own names</summary>
          <table>
            <thead><tr><th>Parameter</th><th>Name in the CPF</th></tr></thead>
            <tbody>{cpf.parameters.map((p) => <tr key={p.id}><td>{paramLabel(p.id)}</td><td><code>{p.id}</code></td></tr>)}</tbody>
          </table>
        </details>
      </Panel>
    </main>
  );
}
