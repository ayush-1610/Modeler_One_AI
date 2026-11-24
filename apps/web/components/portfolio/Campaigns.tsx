"use client";

// Campaigns (P-05, the console redesign's slice 2): every campaign of the projects this person is a member of (the API
// filters by membership since R-S01), without opening each project. A campaign's numbers on a software fixture are not
// PBPK results; its own page says so.

import Link from "next/link";
import { useState } from "react";

import { Table } from "@/components/kit/Table";
import { StatusChip } from "@/components/ui";
import type { Campaign } from "@/lib/types";

const pct = (c: Campaign) => (c.budgetSeconds > 0 ? Math.min(100, Math.round((100 * c.elapsedSeconds) / c.budgetSeconds)) : 0);

export function Campaigns({ campaigns, names }: { campaigns: Campaign[]; names: Record<string, string> }) {
  const [status, setStatus] = useState("");
  const statuses = [...new Set(campaigns.map((c) => c.status))].sort();
  const rows = status ? campaigns.filter((c) => c.status === status) : campaigns;
  return (
    <Table caption="Campaigns" rows={rows} rowKey={(c) => c.id} rowTestId={(c) => `campaign-row-${c.id}`} testId="campaigns-table"
           filter={{ placeholder: "Filter campaigns", text: (c) => `${c.id} ${names[c.project] ?? c.project} ${c.compound} ${c.currentStage}` }}
           tools={statuses.length > 1 && (
             <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
               <option value="">All statuses</option>
               {statuses.map((s) => <option key={s} value={s}>{s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, " ")}</option>)}
             </select>
           )}
           columns={[
             { key: "id", label: "Campaign", sort: (c) => c.id, render: (c) => <Link href={`/campaigns/${encodeURIComponent(c.id)}`}><code>{c.id}</code></Link> },
             { key: "project", label: "Project", sort: (c) => names[c.project] ?? c.project,
               // a campaign started outside a project (a reference run, a seeded one) has no project page to link to
               render: (c) => c.project ? <Link href={`/projects/${encodeURIComponent(c.project)}`}>{names[c.project] ?? c.project}</Link>
                 : <span className="muted">not in a project</span> },
             { key: "compound", label: "Compound", sort: (c) => c.compound, render: (c) => c.compound },
             { key: "status", label: "Status", sort: (c) => c.status, render: (c) => <StatusChip status={c.status} /> },
             { key: "stage", label: "Current stage", sort: (c) => c.currentStage, render: (c) => c.currentStage },
             { key: "budget", label: "Budget used", num: true, sort: pct, render: (c) => `${pct(c)} %` },
           ]}
           empty="No campaign has run yet. A campaign runs once the project's plan is signed." />
  );
}
