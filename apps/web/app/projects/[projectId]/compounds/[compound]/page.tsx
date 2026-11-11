import type { ReactNode } from "react";

import { ApiProblem, Card, Completeness, ProvenanceChip } from "@/components/ui";
import { MEASURED_SOURCES } from "@/lib/types";
import { getCompoundCpf } from "@/lib/reads";
import { breakable, Hero } from "@/components/kit";
import { Clip } from "@/components/kit/Clip";
import { SortableTable } from "@/components/kit/SortableTable";
import { numericKey } from "@/lib/tableSort";

// The Value cell says the stored value as it is (the 2026-11-11 audit 2, item 3). A number is never split or rounded: the
// CPF is the system of record, so it shows at full stored precision on one line. A structured value (a published
// expression profile is thousands of characters of JSON) is one line saying what it is, built only from the keys the
// document holds, with the verbatim text one click away. Other text wraps as text.
type Shown = { cell: ReactNode; className: string | undefined };

function summary(text: string): string | null {
  let doc: unknown;
  try { doc = JSON.parse(text); } catch { return null; }
  if (Array.isArray(doc)) return `structured value · ${doc.length} entries`;
  if (doc === null || typeof doc !== "object") return null;
  const entries = Object.entries(doc as Record<string, unknown>);
  const parts = entries.flatMap(([k, v]) =>
    typeof v === "string" && v && v.length <= 40 ? [`${k} ${v}`] : Array.isArray(v) ? [`${k}: ${v.length} entries`] : []);
  return ["structured value", ...(parts.length ? parts.slice(0, 4) : [`${entries.length} entries`])].join(" · ");
}

function shown(value: number | string | null): Shown {
  if (value === null || value === "") return { cell: <span className="muted">—</span>, className: "num" };
  if (typeof numericKey(value) === "number") return { cell: <span className="cpf-number">{String(value)}</span>, className: "num" };
  const text = String(value);
  const lead = /^\s*[[{]/.test(text) ? summary(text) : null;
  return { cell: lead ? <Clip text={text} lead={lead} testId="cpf-structured" /> : text, className: "cpf-text" };
}

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
                       rows={cpf.parameters.map((p) => { const value = shown(p.value); return {
                         key: p.id,
                         cells: [
                           <code key="id">{breakable(p.id)}</code>, value.cell, p.unit || <span className="muted">—</span>,
                           <ProvenanceChip key="src" source={p.source} />, <Clip key="ref" text={p.reference} max={90} />,
                           p.fittableStages.length ? p.fittableStages.join(", ") : <span className="muted">fixed</span>,
                         ],
                         // fixed parameters sort after the fittable ones
                         sort: [p.id, numericKey(p.value), p.unit || null, p.source, p.reference || null,
                                p.fittableStages.length ? p.fittableStages.join(", ") : null],
                         filter: [p.id, p.unit, p.source, p.reference, p.fittableStages.join(" ")].filter(Boolean).join(" "),
                         cellClassName: [undefined, value.className],
                       }; })} />
      </Card>
    </main>
  );
}
