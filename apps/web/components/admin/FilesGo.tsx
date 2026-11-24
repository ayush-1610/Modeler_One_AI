"use client";

// Where a company's client files may go for an AI model to read (the governance review of model failover, 2026-11-22),
// set by the administrator for all of the company's people and projects at once (the owner, 2026-11-24; it was a panel
// on each project's Data room and Settings before, and the company's people no longer see it). In-house only until a
// cloud service has the client's written permission, recorded here with its reference and its end. The agents that
// read client files follow it from their next request. A fresh step-up and a reason; on the company's audit trail.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card } from "@/components/ui";
import { send, type Schema } from "@/lib/api";

type Permissions = Schema<"DataPermissionsView">;
type Grant = { on: boolean; reference: string; expires: string };

export function FilesGo({ tenantId, permissions: p }: { tenantId: string; permissions: Permissions }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [grants, setGrants] = useState<Record<string, Grant>>({});
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const inForce = p.grants.filter((g) => g.in_force && !p.in_house_only);
  const said = inForce.length === 0
    ? "In-house only: the company's files are read on your server and sent to no cloud service."
    : `On your server, and to ${inForce.map((g) => `${g.label} (${g.reference}${g.expires ? `, until ${g.expires}` : ""})`).join(", ")}.`;

  function start() {
    setGrants(Object.fromEntries(p.services.map((s) => {
      const g = p.grants.find((x) => x.service === s.service);
      return [s.service, { on: Boolean(g) && !p.in_house_only, reference: g?.reference ?? "", expires: g?.expires ?? "" }];
    })));
    setReason("");
    setProblem(null);
    setOpen(true);
  }

  async function save() {
    setBusy(true);
    setProblem(null);
    const chosen = Object.entries(grants).filter(([, g]) => g.on);
    const env = await send("put", "/api/v1/admin/companies/{tenant_id}/data-permissions", { tenant_id: tenantId }, {
      in_house_only: chosen.length === 0, reason: reason.trim(),
      services: Object.fromEntries(chosen.map(([s, g]) => [s, { reference: g.reference.trim(), expires: g.expires.trim() }])),
    });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setOpen(false);
    router.refresh();
  }

  const missingReference = Object.values(grants).some((g) => g.on && !g.reference.trim());
  return (
    <Card title="Where its files may go">
      <section className="files-go" data-testid="files-go" aria-label="Where this company's files may go">
        <p className="muted m-0">
          For every person and project of this company: the AI agents that read its client files use only the services
          allowed here. Its people do not see this setting.
        </p>
        <p className="m-0">
          <span data-testid="files-go-said">{said}</span>{" "}
          {!open && <button type="button" className="btn small" onClick={start} data-testid="files-go-change">Change</button>}
        </p>
        {open && (
          <div className="files-go-form">
            <p className="muted m-0">
              Tick a cloud service only with the client&apos;s written permission, and name it (a letter, an email, a
              contract clause). Each service&apos;s own terms are on Agents and models. The agents follow this from their next
              step.
            </p>
            <ul className="plain-list">
              {p.services.map((s) => {
                const g = grants[s.service] ?? { on: false, reference: "", expires: "" };
                const set = (patch: Partial<Grant>) => setGrants({ ...grants, [s.service]: { ...g, ...patch } });
                return (
                  <li key={s.service} className="files-go-row">
                    <label><input type="checkbox" checked={g.on} onChange={(e) => set({ on: e.target.checked })}
                                  data-testid={`files-go-${s.service}`} /> {s.label}</label>
                    {g.on && (
                      <>
                        <label>The client&apos;s permission<input value={g.reference} onChange={(e) => set({ reference: e.target.value })}
                                                                  placeholder="e.g. letter of 2026-11-20" data-testid={`files-go-ref-${s.service}`} /></label>
                        <label>Until (optional)<input type="date" value={g.expires} onChange={(e) => set({ expires: e.target.value })}
                                                       data-testid={`files-go-until-${s.service}`} /></label>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
            <label className="files-go-why">Why<input value={reason} onChange={(e) => setReason(e.target.value)}
                                                       placeholder="kept on its audit trail" data-testid="files-go-reason" /></label>
            <div className="files-go-acts">
              <button type="button" className="btn primary" disabled={busy || !reason.trim() || missingReference}
                      onClick={() => void save()} data-testid="files-go-save">Save</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button>
            </div>
            {problem && <div className="banner err" role="alert" data-testid="files-go-problem">{problem}</div>}
          </div>
        )}
        {p.history.length > 0 && (
          <details className="files-go-history" data-testid="files-go-history">
            <summary>Changes ({p.history.length})</summary>
            <ul className="plain-list">
              {p.history.map((h) => (
                <li key={h.at + h.by}>
                  {h.at.slice(0, 10)}, {h.by}: {h.in_house_only || h.services.length === 0 ? "in-house only" : h.services.join(", ")}. {h.reason}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </Card>
  );
}
