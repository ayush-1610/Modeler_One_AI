import { ApiProblem, Card, Completeness, ProvenanceChip } from "@/components/ui";
import { MEASURED_SOURCES } from "@/lib/types";
import { getCompoundCpf } from "@/lib/reads";
import { Hero } from "@/components/kit";
import { Clip } from "@/components/kit/Clip";
import { SortableTable } from "@/components/kit/SortableTable";
import { numericKey } from "@/lib/tableSort";

export default async function CompoundPage({ params }: { params: Promise<{ projectId: string; compound: string }> }) {
  const { projectId, compound } = await params;
  // the segment arrives URL-encoded; the typed client encodes each path parameter itself
  const live = await getCompoundCpf(projectId, decodeURIComponent(compound));
  const cpf = live.data;
  if (!cpf) {
    return (
      <main>
        <Hero tone="inputs" eyebrow="Compound Parameter Framework" title={decodeURIComponent(compound)} />
        <ApiProblem problem={live.problem ?? `No CPF for ${decodeURIComponent(compound)} in project ${projectId} yet.`} />
      </main>
    );
  }
  const fitted = cpf.parameters.filter((p) => p.source === "ParameterIdentification").length;
  const measured = cpf.parameters.filter((p) => MEASURED_SOURCES.includes(p.source)).length;

  return (
    <main>
      <Hero tone="inputs" eyebrow={`Compound Parameter Framework · v${cpf.version}`} title={cpf.name}
            lede="The CPF is the system of record: every simulation is regenerated from it. Each parameter shows its value, provenance and the stages in which it may be fitted." />

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
        <div className="mt-12"><Completeness value={cpf.completeness} /></div>
      </Card>

      <Card title="Parameters">
        {/* sortable, filterable, 50 rows at a time (the 2026-11-11 audit, item 11); the default order is the CPF's */}
        <SortableTable testId="cpf-parameters" label="Parameters" noun="parameters" pageSize={50} tableClassName="cpf-table"
                       filterPlaceholder="Filter parameters: id, unit, provenance, reference…"
                       columns={[
                         { key: "id", label: "Parameter" }, { key: "value", label: "Value", numeric: true }, { key: "unit", label: "Unit" },
                         { key: "source", label: "Provenance" }, { key: "reference", label: "Reference", className: "muted cpf-ref" },
                         { key: "stages", label: "Fittable stages" },
                       ]}
                       rows={cpf.parameters.map((p) => ({
                         key: p.id,
                         cells: [
                           <code key="id">{p.id}</code>, p.value ?? "—", p.unit || <span className="muted">—</span>,
                           <ProvenanceChip key="src" source={p.source} />, <Clip key="ref" text={p.reference} max={90} />,
                           p.fittableStages.length ? p.fittableStages.join(", ") : <span className="muted">fixed</span>,
                         ],
                         // fixed parameters sort after the fittable ones
                         sort: [p.id, numericKey(p.value), p.unit || null, p.source, p.reference || null,
                                p.fittableStages.length ? p.fittableStages.join(", ") : null],
                         filter: [p.id, p.unit, p.source, p.reference, p.fittableStages.join(" ")].filter(Boolean).join(" "),
                       }))} />
      </Card>
    </main>
  );
}
