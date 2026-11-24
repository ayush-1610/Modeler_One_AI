"use client";

// The Data plan (P-13b, the console redesign's slice 4a; the owner's answer Q1 of 2026-11-23: yes, read-mostly): which
// data the project's applications require, who provides each item, what it is for, and whether it is covered, from the
// requirements derived from the brief (`GET /requirements`, re-derived on every brief save; never approved). Nothing is
// edited here: each item opens the area of Inputs where it is settled (one place per decision).

import Link from "next/link";
import { useState } from "react";

import { Table } from "@/components/kit/Table";
import type { Schema } from "@/lib/api";
import { inputsHref } from "@/lib/words";

type Page = Schema<"RequirementsPage">;
type Item = {
  req_id: string; label: string; kind: string; group: string; criticality: string; applies: string; condition_text?: string;
  needed_for?: string[]; provider: string; purpose?: string | null; status: string; satisfied_by?: string[]; note?: string;
};

const PROVIDER: Record<string, string> = {
  CLIENT: "The client", LITERATURE: "Literature", SPONSOR_TO_MEASURE: "The client, to measure", PREDICT: "Predicted",
  STRUCTURE: "From the structure", LIBRARY: "PK-Sim library", STUDY: "A clinical study", PROPOSAL: "The proposal",
  NOT_NEEDED: "Not needed", NOT_STATED: "Not stated",
};
// the plan's own states: OPEN is "not marked covered yet", not "no value exists" (Inputs may already hold the value),
// so it is not called Missing; Done where the plan records what covers it
const STATUS: Record<string, [string, string]> = {
  OPEN: ["Open", "medium"], SATISFIED: ["Done", "low"], NOT_AVAILABLE: ["Not available", "neutral"], WAIVED: ["Waived", "neutral"],
};
const said = (code: string) => code.replace(/_/g, " ");
const AREA: Record<string, string> = { parameter: "compound", system: "compound", formulation: "formulations", dataset: "studies" };
const AREA_WORD: Record<string, string> = { compound: "Compound", formulations: "Products and dissolution", studies: "Clinical studies", todo: "To do" };

export function DataPlan({ projectId, page }: { projectId: string; page: Page }) {
  const items = ((page.matrix as { items?: Item[] }).items ?? []).filter((i) => i.applies !== "no");
  const [status, setStatus] = useState("");
  const [provider, setProvider] = useState("");
  const providers = [...new Set(items.map((i) => i.provider))].sort();
  const rows = items.filter((i) => (!status || i.status === status) && (!provider || i.provider === provider));
  const open = items.filter((i) => i.status === "OPEN").length;
  return (
    <>
      <p className="muted" data-testid="data-plan-summary">
        {items.length} item{items.length === 1 ? "" : "s"} apply · {open} open · {page.counts.undetermined} may apply, depending on the brief.
        Edits are made where each item is settled, never here.
      </p>
      <Table caption="Data plan" rows={rows} rowKey={(i) => i.req_id} rowTestId={(i) => `plan-item-${i.req_id}`} testId="data-plan"
             filter={{ placeholder: "Find an item", text: (i) => `${i.label} ${i.group} ${(i.needed_for ?? []).join(" ")} ${i.purpose ?? ""}` }}
             tools={<>
               <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="data-plan-status">
                 <option value="">Every status</option>
                 {Object.entries(STATUS).map(([k, [w]]) => <option key={k} value={k}>{w}</option>)}
               </select>
               <select aria-label="Who provides it" value={provider} onChange={(e) => setProvider(e.target.value)}>
                 <option value="">Every provider</option>
                 {providers.map((p) => <option key={p} value={p}>{PROVIDER[p] ?? p}</option>)}
               </select>
             </>}
             columns={[
               { key: "item", label: "Item", sort: (i) => i.label, render: (i) => (
                 <><strong>{i.label}</strong><div className="muted fs-12">{i.group}{i.applies === "undetermined" ? ` · may apply${i.condition_text ? `: ${i.condition_text}` : ""}` : ""}</div></>
               ) },
               { key: "for", label: "Needed for", sort: (i) => (i.needed_for ?? []).join(", "), render: (i) => (i.needed_for ?? []).join(", ") || <span className="muted">—</span> },
               { key: "provider", label: "Who provides it", sort: (i) => PROVIDER[i.provider] ?? i.provider, render: (i) => PROVIDER[i.provider] ?? i.provider },
               { key: "purpose", label: "Purpose", render: (i) => (i.purpose ? said(i.purpose) : <span className="muted">—</span>) },
               { key: "status", label: "Status", sort: (i) => i.status, render: (i) => {
                 const [w, c] = STATUS[i.status] ?? [i.status, "neutral"];
                 return <><span className={`chip ${c}`}>{w}</span>{(i.satisfied_by ?? []).length > 0 && <div className="muted fs-12">by {i.satisfied_by!.join(", ")}</div>}</>;
               } },
               { key: "where", label: "Settled on", render: (i) => {
                 const area = AREA[i.kind] ?? "todo";
                 return <Link href={inputsHref(projectId, { area: area as never })} prefetch={false} data-testid={`plan-item-open-${i.req_id}`}>{AREA_WORD[area]}</Link>;
               } },
             ]}
             empty="No data requirement applies yet: the plan is derived from the brief on Start." />
    </>
  );
}
