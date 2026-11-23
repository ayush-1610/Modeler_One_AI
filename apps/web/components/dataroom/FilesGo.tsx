"use client";

// Where this project's client files may go for an AI model to read (the governance review of model failover,
// 2026-11-22): in-house only until a cloud service has the client's written permission, recorded here with its
// reference and its end. The agents that read client files follow it from their next request; a model the project does
// not allow is left out, and with none left the run stops and says so. A change is confirmed with the step-up and
// audited.

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { send } from "@/lib/api";
import { readAgain, useResource } from "@/lib/hooks";

import { ROOM, RUN } from "./acts";

const PERMISSIONS = "/api/v1/projects/{project_id}/data-permissions" as const;

type Grant = { on: boolean; reference: string; expires: string };

export function FilesGo({ projectId }: { projectId: string }) {
  const params = { project_id: projectId };
  const client = useQueryClient();
  const page = useResource(PERMISSIONS, params);
  const [open, setOpen] = useState(false);
  const [grants, setGrants] = useState<Record<string, Grant>>({});
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (!page.data) return null;
  const p = page.data;
  const inForce = p.grants.filter((g) => g.in_force && !p.in_house_only);
  const said = inForce.length === 0
    ? "In-house only: the client's files are read on your server and sent to no cloud service."
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
    const env = await send("put", PERMISSIONS, params, {
      in_house_only: chosen.length === 0, reason: reason.trim(),
      services: Object.fromEntries(chosen.map(([s, g]) => [s, { reference: g.reference.trim(), expires: g.expires.trim() }])),
    });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setOpen(false);
    await readAgain(client, [PERMISSIONS, ROOM, RUN]);
  }

  const missingReference = Object.values(grants).some((g) => g.on && !g.reference.trim());
  return (
    <section className="dr-files-go" data-testid="files-go" aria-label="Where this project's files may go">
      <p>
        <strong>Where the files may go:</strong> <span data-testid="files-go-said">{said}</span>{" "}
        {!open && <button type="button" className="btn small" onClick={start} data-testid="files-go-change">Change</button>}
      </p>
      {open && (
        <div className="dr-files-go-form">
          <p className="muted">
            Tick a cloud service only with the client&apos;s written permission, and name it (a letter, an email, a contract
            clause). Each service&apos;s own terms are on Admin → Agents. The agents follow this from their next step.
          </p>
          <ul className="plain-list">
            {p.services.map((s) => {
              const g = grants[s.service] ?? { on: false, reference: "", expires: "" };
              const set = (patch: Partial<Grant>) => setGrants({ ...grants, [s.service]: { ...g, ...patch } });
              return (
                <li key={s.service} className="dr-files-go-row">
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
          <label className="dr-files-go-why">Why<input value={reason} onChange={(e) => setReason(e.target.value)}
                                                        placeholder="kept with the change" data-testid="files-go-reason" /></label>
          <div className="dr-files-go-acts">
            <button type="button" className="btn primary" disabled={busy || !reason.trim() || missingReference}
                    onClick={() => void save()} data-testid="files-go-save">Save</button>
            <button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button>
          </div>
          {problem && <div className="banner err" role="alert" data-testid="files-go-problem">{problem}</div>}
          {p.history.length > 0 && (
            <details className="dr-files-go-history" data-testid="files-go-history">
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
        </div>
      )}
    </section>
  );
}
