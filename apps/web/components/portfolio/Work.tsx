"use client";

// Your work (P-02, the console redesign's slice 2): one list of links to everything that waits on this person across
// their projects. Nothing is decided here (the owner's decision G1-3): Open goes to the page where it is decided, with
// its own checks and, for a signature or a decision, the step-up.

import Link from "next/link";
import { useState } from "react";

import { Table } from "@/components/kit/Table";
import type { WorkItem, WorkKind } from "@/lib/portfolio";

const KIND_CLASS: Record<WorkKind, string> = { "To decide": "medium", "To sign": "brand", "To confirm": "neutral" };

export function WorkKindChip({ kind }: { kind: WorkKind }) {
  return <span className={`chip ${KIND_CLASS[kind]}`}>{kind}</span>;
}

export function Work({ items }: { items: WorkItem[] }) {
  const [kind, setKind] = useState<WorkKind | "">("");
  const [project, setProject] = useState("");
  const projects = [...new Map(items.filter((w) => w.projectId).map((w) => [w.projectId!, w.projectName ?? w.projectId!])).entries()];
  const rows = items.filter((w) => (!kind || w.kind === kind) && (!project || w.projectId === project));
  return (
    <Table caption="Your work" rows={rows} rowKey={(w) => w.key} rowTestId={(w) => `work-row-${w.key}`} testId="work-table"
           filter={{ placeholder: "Filter by text", text: (w) => `${w.what} ${w.detail ?? ""} ${w.projectName ?? ""} ${w.step}` }}
           tools={<>
             <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value as WorkKind | "")} data-testid="work-kind">
               <option value="">All kinds</option><option>To sign</option><option>To decide</option><option>To confirm</option>
             </select>
             <select aria-label="Project" value={project} onChange={(e) => setProject(e.target.value)} data-testid="work-project">
               <option value="">All projects</option>
               {projects.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
             </select>
           </>}
           columns={[
             { key: "what", label: "Item", sort: (w) => w.what, render: (w) => (
               <><strong>{w.what}</strong>{w.detail && <div className="muted fs-12">{w.detail}</div>}</>
             ) },
             { key: "project", label: "Project", sort: (w) => w.projectName ?? "", render: (w) => (w.projectId
               ? <Link href={`/projects/${encodeURIComponent(w.projectId)}`}>{w.projectName}</Link>
               : <span className="muted">Campaign not recorded yet</span>) },
             { key: "step", label: "Step", sort: (w) => w.step, render: (w) => w.step },
             { key: "kind", label: "Status", sort: (w) => w.kind, render: (w) => <WorkKindChip kind={w.kind} /> },
             { key: "open", label: "Open", render: (w) => (
               <Link className="btn small" href={w.href} data-testid={`work-open-${w.key}`} aria-label={`Open: ${w.what}${w.projectName ? `, ${w.projectName}` : ""}`}>Open</Link>
             ) },
           ]}
           empty={items.length === 0 ? "Nothing waits on you." : "Nothing of this kind waits on you."} />
  );
}
