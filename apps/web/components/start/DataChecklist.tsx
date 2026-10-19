"use client";

import { useState } from "react";

import { DataTable, EmptyState, InlineIssue, type Column } from "@/components/kit";
import { Block } from "@/components/start/Blocks";
import { send, type Schema } from "@/lib/api";
import type { FeasibilityLine, Item, PlanView } from "@/lib/data-plan";
import type { useMutation } from "@/lib/hooks";

type Reconciled = Schema<"ReconciledRow">;
type Provider = NonNullable<Schema<"OverrideRequest">["provider"]>;
// who a person may say provides an item (the data plan's override, kept across re-derivations)
const PROVIDERS: Provider[] = ["CLIENT", "LITERATURE", "SPONSOR_TO_MEASURE", "PREDICT", "STRUCTURE", "LIBRARY", "STUDY",
                               "PROPOSAL", "NOT_NEEDED"];

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
 *  provides it, changed in place (map rows p1-provider, p1-crosscheck: a person's choice is kept across re-derivations);
 *  what the client is expected to send is ticked off as their files arrive; what the builder cannot provide yet is
 *  said inline. */
export function DataChecklist({ projectId, plan, planProblem, reconciliation, run, busy }: {
  projectId: string; plan: PlanView | null; planProblem: string | null; reconciliation: Reconciled[] | null;
  run: ReturnType<typeof useMutation>["run"]; busy: boolean;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  async function change(item: Item, body: { provider?: Provider; cross_check?: boolean }) {
    const what = body.provider ? `provided by ${PROVIDER_LABEL[body.provider] ?? body.provider.toLowerCase()}`
      : body.cross_check ? "cross-checked in the literature" : "no literature cross-check";
    const { problem: refused } = await run(() => send("put", "/api/v1/projects/{project_id}/requirements/{req_id}",
      { project_id: projectId, req_id: item.req_id }, { ...body, reason: `${item.label}: ${what} (set at Start)` }));
    setProblem(refused);
  }
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
      <span className="check-from">
        <select aria-label={`Who provides ${i.label}`} value={i.provider} disabled={busy} data-testid={`provider-${i.req_id}`}
                title={i.provider_source === "override" ? "set by a person" : i.provider_statement
                  ? `the proposal: “${i.provider_statement}”` : "the template's default"}
                onChange={(e) => change(i, { provider: e.target.value as Provider })}>
          {[...new Set([i.provider, ...PROVIDERS])].map((p) => <option key={p} value={p}>{PROVIDER_LABEL[p] ?? p.toLowerCase()}</option>)}
        </select>
        {i.provider === "CLIENT" && (
          <label title="the client's value is checked against the literature">
            <input type="checkbox" checked={i.cross_check} disabled={busy} data-testid={`cross-check-${i.req_id}`}
                   onChange={(e) => change(i, { cross_check: e.target.checked })} /> cross-check
          </label>
        )}
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
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
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
