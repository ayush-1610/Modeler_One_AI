"use client";

import { DataTable, EmptyState, InlineIssue, type Column } from "@/components/kit";
import { Block } from "@/components/start/Blocks";
import type { Schema } from "@/lib/api";
import type { FeasibilityLine, Item, PlanView } from "@/lib/data-plan";

type Reconciled = Schema<"ReconciledRow">;

const PROVIDER_LABEL: Record<string, string> = {
  CLIENT: "client", LITERATURE: "literature", SPONSOR_TO_MEASURE: "sponsor to measure", PREDICT: "predicted",
  STRUCTURE: "from the structure", LIBRARY: "library", STUDY: "study", PROPOSAL: "proposal", NOT_NEEDED: "not needed",
  NOT_STATED: "not stated",
};
const ARRIVED: Record<string, { label: string; tone: string }> = {
  DELIVERED: { label: "arrived", tone: "low" }, PARTIAL: { label: "part arrived", tone: "medium" },
  MISSING: { label: "expected", tone: "neutral" },
};
// the scope gates show their own lines (block 4); the checklist shows the rest of what the builder cannot provide
const GATE_PATHS = new Set(["drug.modality", "scope.pbpk_model", "scope.site_of_action", "scope.formulation_types"]);

/** Block 5: the data checklist, derived from the brief whenever it changes (no button, no approval). Each item says who
 *  provides it; what the client is expected to send is ticked off as their files arrive; what the builder cannot
 *  provide yet is said inline. */
export function DataChecklist({ plan, planProblem, reconciliation }: {
  plan: PlanView | null; planProblem: string | null; reconciliation: Reconciled[] | null;
}) {
  if (!plan) {
    return (
      <Block n={5} title="The data checklist" testId="start-checklist">
        {planProblem ? <EmptyState title="No checklist yet">It is derived from the brief as soon as the brief is saved.</EmptyState>
          : <p className="muted">Loading the checklist…</p>}
      </Block>
    );
  }
  const items = plan.matrix.items.filter((i) => i.applies !== "no");
  const arrived = new Map((reconciliation ?? []).map((r) => [r.req_id, r]));
  const warnings = plan.feasibility.lines.filter((l: FeasibilityLine) => l.status !== "SUPPORTED" && l.status !== "UNDETERMINED"
    && !GATE_PATHS.has(l.needed_because) && !l.feature.startsWith("route:"));
  const counts = Object.entries(plan.counts.by_provider).sort((a, b) => b[1] - a[1]);
  const columns: Column<Item>[] = [
    { key: "item", label: "What the model needs", render: (i) => (
      <span data-testid={`check-${i.req_id}`}>{i.label}{i.criticality === "REQUIRED" ? "" : <span className="muted"> · {i.criticality.toLowerCase()}</span>}
        {i.applies === "undetermined" && <span className="muted"> · depends on the brief</span>}</span>) },
    { key: "from", label: "From", render: (i) => (
      <span className="row" style={{ gap: 4 }}>
        <span className="chip neutral">{PROVIDER_LABEL[i.provider] ?? i.provider.toLowerCase()}</span>
        {i.cross_check && <span className="chip brand" title="the client's value is checked against the literature">cross-check</span>}
      </span>) },
    { key: "arrived", label: "Status", render: (i) => {
      const row = arrived.get(i.req_id);
      if (!row) return <span className="muted">—</span>;
      const tag = ARRIVED[row.status] ?? { label: row.status.toLowerCase(), tone: "neutral" };
      return <span className={`chip ${tag.tone}`} title={[...row.delivered, row.detail].filter(Boolean).join("; ")}
                   data-testid={`arrived-${i.req_id}`}>{tag.label}</span>;
    } },
  ];
  return (
    <Block n={5} title="The data checklist" testId="start-checklist"
           lede={<>Derived from the brief, and kept up to date as it changes: {counts.map(([p, n]) => `${n} ${PROVIDER_LABEL[p] ?? p.toLowerCase()}`).join(" · ")}.</>}>
      {warnings.map((l) => (
        <InlineIssue key={l.feature} severity={l.status === "LIMITED" ? "warn" : "error"} testId="checklist-warning">
          <strong>{l.feature}</strong>: {l.route}
        </InlineIssue>
      ))}
      <DataTable columns={columns} rows={items} rowKey={(i) => i.req_id} testId="checklist-table"
                 empty={<EmptyState title="Nothing applies yet">Fill the short brief: the checklist follows it.</EmptyState>} />
    </Block>
  );
}
