"use client";

// Give a person another person's projects, or every project of the company (the admin console): how the projects made
// under the pilot's DEV sign-in reach the people who now sign in through Keycloak. A fresh step-up and a reason; each
// membership is on the company's audit trail.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card } from "@/components/ui";
import { send } from "@/lib/api";

type Person = { subject: string; name: string; projects: string[] };

export function GiveProjects({ tenantId, people }: { tenantId: string; people: Person[] }) {
  const router = useRouter();
  const [to, setTo] = useState("");
  const [from, setFrom] = useState("");
  const [reason, setReason] = useState("");
  const [owner, setOwner] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function give() {
    setBusy(true);
    setProblem(null);
    setDone(null);
    const env = await send("post", "/api/v1/admin/companies/{tenant_id}:give-projects", { tenant_id: tenantId },
                           { to, from, owner, reason: reason.trim() });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setReason("");
    const who = people.find((p) => p.subject === to)?.name ?? to;
    setDone(`${who} now has ${from ? "those projects" : "every project"}${owner ? ", as their owner" : ", to read"}.`);
    router.refresh();
  }

  return (
    <Card title="Give a person projects">
      <p className="muted mt-0">
        Makes a person a member of another person&apos;s projects, or of every project of this company: for example the
        projects made under the pilot&apos;s development sign-in (&ldquo;Dev User&rdquo;), for the people who now sign in
        through Keycloak. They must have signed in once. Without &ldquo;owner&rdquo;, the projects are shared with them to
        read (a reviewer among them can still sign).
      </p>
      <form className="admin-filter" onSubmit={(e) => { e.preventDefault(); void give(); }} data-testid="give-projects">
        <label>To
          <select value={to} onChange={(e) => setTo(e.target.value)} data-testid="give-to">
            <option value="">choose a person</option>
            {people.map((p) => <option key={p.subject} value={p.subject}>{p.name} ({p.subject})</option>)}
          </select>
        </label>
        <label>Projects
          <select value={from} onChange={(e) => setFrom(e.target.value)} data-testid="give-from">
            <option value="">every project of this company</option>
            {people.filter((p) => p.subject !== to && p.projects.length > 0).map((p) => (
              <option key={p.subject} value={p.subject}>{p.name}&apos;s ({p.projects.length})</option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={owner} onChange={(e) => setOwner(e.target.checked)} data-testid="give-owner" />
          and make them the owner (the only one who changes each project)
        </label>
        <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="kept with each membership"
                         data-testid="give-reason" /></label>
        <button type="submit" className="btn primary" disabled={busy || !to || !reason.trim()} data-testid="give-submit">Give</button>
      </form>
      {problem && <div className="banner err mt-10">{problem}</div>}
      {done && <div className="banner ok mt-10" data-testid="give-done">{done}</div>}
    </Card>
  );
}
