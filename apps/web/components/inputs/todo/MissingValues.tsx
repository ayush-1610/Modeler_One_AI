"use client";

// To do's compound values no source gives (plan 2026-11-14 slice 4; the design text's `MissingValues`): the minimum
// compound data still missing, entered together with one citation. One row per value, named as its row on Compound
// names it (the parameter's id from the API, in words); the value and its unit are typed as the source states them
// (the row's unit stands in the field when the API gives one: a missing row gives none, and the web never supplies a
// unit), with the sentence that states it. The source (its kind, title, DOI or URL) is given once for all of them. Each
// value goes in through the same `POST /evidence` its row on Compound uses, one by one; a refusal is said on its row in
// the server's words, and the values sent stay sent. A pKa is then called acidic or basic under "Settle disagreements".
// The data plan's "an elimination pathway" asks for the pathway first (final review OWN-5): one of the pathways the API
// names on its item (`pathways`: each placed by the model builder, with the unit its value is stored in, which then
// stands in the unit field); the value is filed under that pathway, never under the placeholder itself.

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Problem } from "@/components/delivery/shared";
import { focusAfter } from "@/components/kit/focus";
import { announce } from "@/components/kit/LiveRegion";
import { send, type Schema } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";
import type { WorkItem } from "@/lib/inputsWork";
import { paramLabel, plural } from "@/lib/words";

import { PathwayPick, type TodoItem } from "../InputsTodo";

const INPUTS = "/api/v1/projects/{project_id}/inputs" as const;
const EVIDENCE = "/api/v1/projects/{project_id}/evidence" as const;
// the sources a person may cite (modeler_project.evidence.SourceType), as the row's own form on Compound offers them
const SOURCE_TYPES = [["PUBLICATION", "publication"], ["CLIENT_REPORT", "client report"], ["REGULATORY_REVIEW", "regulatory review"],
                      ["DATABASE", "database"], ["ASSUMPTION", "assumption (no source)"]] as const;
type Row = Schema<"CompoundRow">;
type Entry = { value: string; unit: string; quote: string; pathway: string };
type Line = { item: WorkItem; row: Row };

/** The pathways a value for the data plan's "elim" is filed under (none for any other row). */
const pathwaysOf = (item: WorkItem) => (item.todo as TodoItem | undefined)?.pathways ?? [];

export function MissingValues({ projectId, items, onOpen, heading }: {
  projectId: string;
  /** the work model's missing compound values with nothing to accept (To do's filters applied) */
  items: WorkItem[];
  /** open a value's row on Compound */
  onOpen: (item: WorkItem) => void;
  heading: string;
}) {
  const inputs = useResource(INPUTS, { project_id: projectId }).data;
  const client = useQueryClient();
  const router = useRouter();
  const mutation = useMutation();
  const [entries, setEntries] = useState<Record<string, Entry>>({});
  const [type, setType] = useState<(typeof SOURCE_TYPES)[number][0]>("PUBLICATION");
  const [title, setTitle] = useState("");
  const [link, setLink] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [said, setSaid] = useState<string | null>(null);
  const [lacking, setLacking] = useState<string | null>(null);
  const compound = (inputs?.compound ?? []) as Row[];
  const rows: Line[] = items.flatMap((item) => {
    const row = compound.find((r) => r.id === item.todo?.target && r.state === "missing" && r.req_id);
    return row ? [{ item, row }] : [];
  });
  if (!rows.length) return null;

  const entry = (id: string): Entry => entries[id] ?? { value: "", unit: rows.find((r) => r.row.id === id)?.row.unit ?? "", quote: "", pathway: "" };
  const set = (id: string, patch: Partial<Entry>) => setEntries((was) => ({ ...was, [id]: { ...entry(id), ...patch } }));
  // the parameter a row's value is filed under: its own, or the pathway chosen for the data plan's "elim"
  const targetOf = (r: Line) => (pathwaysOf(r.item).length ? entry(r.row.id).pathway : r.row.id);
  const filled = rows.filter((r) => entry(r.row.id).value.trim());
  const cited = type === "ASSUMPTION" || link.trim() !== "";

  async function add() {
    const missing = !filled.length ? "Type at least one value"
      : filled.some((r) => !targetOf(r)) ? "Choose the elimination pathway the value is for"
        : !cited ? "Give the source's DOI or URL, or call it an assumption" : null;
    setLacking(missing);
    if (missing) return;
    const sent: string[] = [];
    const named: string[] = [];
    const refused: Record<string, string> = {};
    for (const r of filled) {
      const { row } = r;
      const e = entry(row.id);
      const number = e.value.trim() !== "" && !Number.isNaN(Number(e.value));
      const { problem } = await mutation.run(() => send("post", EVIDENCE, { project_id: projectId }, {
        req_id: row.req_id as string, target: targetOf(r), value: number ? Number(e.value) : e.value.trim(), unit: e.unit.trim() || null,
        source_type: type, title, quote: e.quote, ...(link.startsWith("10.") ? { doi: link.trim() } : link.trim() ? { url: link.trim() } : {}),
      }), { refresh: false });
      if (problem) refused[row.id] = problem;
      else { sent.push(row.id); named.push(paramLabel(targetOf(r))); }
    }
    setProblems(refused);
    if (!sent.length) return;
    setEntries((was) => Object.fromEntries(Object.entries(was).filter(([id]) => !sent.includes(id))));
    // the compound's rows, the to-do and the model checks follow: the inputs and the evidence are read again, and the
    // step bar (drawn on the server) with them
    await client.invalidateQueries({ predicate: (q) => typeof q.queryKey[0] === "string" && (q.queryKey[0] === INPUTS || q.queryKey[0].startsWith(EVIDENCE)) });
    router.refresh();
    const text = `${named.join(", ")}: ${plural(sent.length, "value")} added with ${title.trim() ? `“${title.trim()}”` : "the source"}.`
      + `${Object.keys(refused).length ? ` ${plural(Object.keys(refused).length, "value")} not added: see its row.` : ""}`;
    setSaid(text);
    announce(text);
    focusAfter(sent.map((id) => `mv-row-${id}`), rows.map((r) => `mv-row-${r.row.id}`).find((id) => !sent.includes(id.slice(7))) ?? null, [heading, "todo-title"]);
  }

  return (
    <div className="batch missing-values" data-testid="missing-values">
      <p className="muted fs-13 m-0">The compound values no source gives yet: type each with its unit as the source states it, and give the
        source once for all of them.</p>
      <div className="table-scroll mv-scroll">
        <table className="mv-table">
          <caption className="sr-only">Compound values to type in</caption>
          <thead><tr><th>Value of</th><th>Value</th><th>Unit</th><th>The sentence that states it</th></tr></thead>
          <tbody>
            {rows.map(({ item, row }) => {
              const e = entry(row.id), name = paramLabel(row.id), pathways = pathwaysOf(item);
              return (
                <tr key={row.id} data-testid={`mv-row-${row.id}`}>
                  <th scope="row">
                    <button type="button" className="link-btn" onClick={() => onOpen(item)} data-testid={`missing-${item.todo!.kind}-${item.todo!.target}`}
                            title="Open its row on Compound">{name}</button>
                    {pathways.length > 0 && (
                      <div className="mt-4">
                        <PathwayPick pathways={pathways} value={e.pathway} label={`The elimination pathway of the value for ${name}`}
                                     testId={`mv-pathway-${row.id}`}
                                     onChange={(id) => set(row.id, { pathway: id, unit: pathways.find((p) => p.id === id)?.unit ?? "" })} />
                      </div>
                    )}
                    {problems[row.id] && <Problem text={problems[row.id]} testId={`mv-problem-${row.id}`} />}
                  </th>
                  <td><input value={e.value} onChange={(x) => set(row.id, { value: x.target.value })} className="mv-value" placeholder="value"
                             aria-label={`Value of ${name}`} data-testid={`mv-value-${row.id}`} /></td>
                  <td><input value={e.unit} placeholder={pathways.length && e.pathway ? "no unit" : "as stated"}
                             onChange={(x) => set(row.id, { unit: x.target.value })} className="mv-unit"
                             aria-label={`Unit of ${name}`} data-testid={`mv-unit-${row.id}`} /></td>
                  <td><input value={e.quote} onChange={(x) => set(row.id, { quote: x.target.value })} className="mv-quote"
                             placeholder="the sentence that states it" aria-label={`The sentence that states ${name}`}
                             data-testid={`mv-quote-${row.id}`} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <form className="mv-source" onSubmit={(e) => { e.preventDefault(); if (!mutation.busy) void add(); }}>
        <label className="add-field">Source
          <select value={type} onChange={(e) => setType(e.target.value as typeof type)} data-testid="mv-source">
            {SOURCE_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select></label>
        <label className="add-field flex-1 minw-140">Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} data-testid="mv-title" /></label>
        <label className="add-field">DOI or URL
          <input value={link} onChange={(e) => setLink(e.target.value)} className="w-170" data-testid="mv-link" /></label>
        <button type="submit" className="btn small" aria-disabled={mutation.busy || undefined} data-testid="mv-submit"
                aria-describedby={lacking ? "mv-lacking" : undefined}
                aria-label={`Add the ${plural(filled.length, "value")} typed, with this source`}>
          {filled.length > 1 ? `Add ${filled.length} values` : "Add"}</button>
        {lacking && <span id="mv-lacking" className="reason-missing" role="alert">{lacking}</span>}
      </form>
      {rows.some((r) => r.row.id === "phys.pka") && (
        <p className="muted fs-12 m-0">A pKa is then called acidic or basic, under &quot;Settle disagreements&quot;.</p>
      )}
      {rows.some((r) => pathwaysOf(r.item).length > 0) && (
        <p className="muted fs-12 m-0" data-testid="mv-pathway-note">An elimination value is given for its pathway, in the unit shown:
          the unit the model stores it in. Another unit is converted where it can be; where it cannot (an absolute clearance needs the
          body weight), you type the value in this unit when you check it under &quot;Settle disagreements&quot;. A clearance by a named
          enzyme (CLspec, CLint, Km, Vmax) also needs its enzyme: it comes with the literature search or the client&apos;s files, and is
          filed under its enzyme under &quot;Settle disagreements&quot;.</p>
      )}
      {said && <p className="banner ok m-0" role="status" data-testid="mv-said">{said}</p>}
    </div>
  );
}
