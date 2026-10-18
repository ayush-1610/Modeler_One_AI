"use client";

// The data checklist (map rows p1-derive, p1-provider, p1-crosscheck, p3-expected): every input and dataset the model
// needs, who provides it, and for the client's items what has arrived. It is derived from the brief at every change
// and never approved (D-27); the PK-Sim columns are not shown here (p1-pksim-cols).

import { useMemo, useState } from "react";

import { EmptyState, InlineIssue } from "@/components/kit";
import type { Run } from "@/components/start/Fields";
import { send } from "@/lib/api";
import { ITEM_STATUS, PROVIDER_LABEL, PROVIDERS, type ChecklistItem, type StartPage } from "@/lib/start";

function need(item: ChecklistItem): { label: string; chip: string } {
  if (item.applies === "undetermined") return { label: `if ${item.condition || "the brief says so"}`, chip: "neutral" };
  if (item.criticality === "REQUIRED") return { label: "needed", chip: "high" };
  return { label: item.criticality === "CONDITIONAL" ? "needed here" : "optional", chip: "medium" };
}

function Arrival({ item }: { item: ChecklistItem }) {
  const shownFor = item.provider === "CLIENT" || ["NOT_AVAILABLE", "WAIVED", "SATISFIED"].includes(item.status);
  if (!shownFor) return null;
  const state = ITEM_STATUS[item.status] ?? { label: item.status.toLowerCase(), chip: "neutral" };
  return (
    <span className={`chip ${state.chip}`} title={[item.detail, ...item.delivered].filter(Boolean).join("\n") || undefined}>
      {item.status === "DELIVERED" ? "✓ " : ""}{state.label}
    </span>
  );
}

export function ChecklistBlock({ projectId, view, run, busy }: { projectId: string; view: StartPage; run: Run; busy: boolean }) {
  const { checklist } = view;
  const [problem, setProblem] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const groups = useMemo(() => {
    const out = new Map<string, ChecklistItem[]>();
    checklist.items.forEach((i) => out.set(i.group, [...(out.get(i.group) ?? []), i]));
    return [...out.entries()];
  }, [checklist.items]);
  const client = checklist.items.filter((i) => i.provider === "CLIENT");
  const byProvider = checklist.items.reduce<Record<string, number>>((acc, i) => ({ ...acc, [i.provider]: (acc[i.provider] ?? 0) + 1 }), {});

  async function change(item: ChecklistItem, body: { provider?: (typeof PROVIDERS)[number]; cross_check?: boolean }) {
    const what = body.provider ? `provider set to ${PROVIDER_LABEL[body.provider]}` :
      body.cross_check ? "cross-checked in the literature" : "no literature cross-check";
    const { problem: failed } = await run(() => send("put", "/api/v1/projects/{project_id}/requirements/{req_id}",
      { project_id: projectId, req_id: item.req_id }, { ...body, reason: `${item.label}: ${what} at Start` }));
    setProblem(failed);
  }

  async function rederive() {
    const { problem: failed } = await run(() => send("post", "/api/v1/projects/{project_id}/requirements:derive", { project_id: projectId }));
    setProblem(failed);
  }

  if (checklist.version === null) {
    return <EmptyState title="No checklist yet">It is derived from the brief as soon as the brief is stored.</EmptyState>;
  }
  return (
    <div className="checklist" data-testid="checklist">
      <p className="muted checklist-summary">
        {checklist.items.length} inputs and datasets ·{" "}
        {Object.entries(byProvider).map(([p, n]) => `${n} ${PROVIDER_LABEL[p] ?? p.toLowerCase()}`).join(", ")}
        {client.length > 0 && <> · <strong data-testid="client-arrived">{checklist.delivered_by_client} of {client.length}</strong> client items arrived</>}
      </p>
      {checklist.stale && (
        <InlineIssue>
          The checklist was derived from an earlier version of the brief.{" "}
          <button type="button" className="link-btn" disabled={busy} onClick={rederive}>Bring it up to date</button>
        </InlineIssue>
      )}
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      {client.length > 0 && (
        <section className="checklist-client" aria-label="Expected from the client">
          <h3>Expected from the client</h3>
          <ul>
            {client.map((i) => (
              <li key={i.req_id} data-testid={`expected-${i.req_id}`}><Arrival item={i} /> {i.label}
                {i.provider_statement && <span className="muted"> · “{i.provider_statement}”</span>}</li>
            ))}
          </ul>
        </section>
      )}
      {groups.map(([group, items]) => {
        const listed = showAll ? items : items.filter((i) => i.applies === "yes");
        if (!listed.length) return null;
        return (
          <section key={group} className="checklist-group">
            <h3>{group}</h3>
            <ul>
              {listed.map((i) => {
                const n = need(i);
                return (
                  <li key={i.req_id} data-testid={`req-${i.req_id}`} className={i.applies === "undetermined" ? "maybe" : ""}>
                    <span className="item-label">{i.label}</span>
                    <span className={`chip ${n.chip}`}>{n.label}</span>
                    <select aria-label={`Who provides ${i.label}`} value={i.provider} disabled={busy}
                            onChange={(e) => change(i, { provider: e.target.value as (typeof PROVIDERS)[number] })}
                            title={i.provider_source === "override" ? "set by a person" : i.provider_statement
                              ? `the proposal: “${i.provider_statement}”` : "the template's default"}>
                      {[...new Set([i.provider, ...PROVIDERS])].map((p) => <option key={p} value={p}>{PROVIDER_LABEL[p] ?? p.toLowerCase()}</option>)}
                    </select>
                    {i.provider === "CLIENT" && (
                      <label className="cross-check">
                        <input type="checkbox" checked={i.cross_check} disabled={busy}
                               onChange={(e) => change(i, { cross_check: e.target.checked })} /> literature cross-check
                      </label>
                    )}
                    <Arrival item={i} />
                    {i.needed_for.length > 0 && <span className="stages">{i.needed_for.join(" ")}</span>}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      <label className="row muted" style={{ gap: 6, fontSize: 13 }}>
        <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
        also show the items the brief does not decide yet ({checklist.items.filter((i) => i.applies === "undetermined").length})
      </label>
    </div>
  );
}
