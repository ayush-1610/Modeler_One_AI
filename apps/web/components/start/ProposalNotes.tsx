"use client";

import Link from "next/link";

import { Fields, OpenQuestions } from "@/components/start/Blocks";
import { display, EMPTY_RECORD, type BriefView } from "@/lib/brief";
import type { Open, Save } from "@/lib/start";

const NOTE_GROUPS = ["products", "populations", "data_plan", "scenarios"];

/** Block 6, collapsed: everything else the proposal says (title, client, products, doses…), kept for the report and
 *  never required. Products move to the Formulations tab, populations and regimens to the Review applications (R3–R4);
 *  until then they are edited on the full brief page. */
export function ProposalNotes({ projectId, view, save, open, onAnswer }: {
  projectId: string; view: BriefView; save: Save; open: Open;
  onAnswer: (id: string, text: string, status: "answered" | "accepted_as_limitation") => void;
}) {
  const short = new Set(view.catalog.short_brief);
  const fields = view.catalog.fields.filter((f) => !short.has(f.id));
  const filled = fields.filter((f) => (view.brief.fields[f.id] ?? EMPTY_RECORD).status !== "MISSING").length;
  const noteFields = new Set(fields.map((f) => f.id));
  const shortGroup = view.catalog.short_group_fields;
  return (
    <details className="card start-notes" data-testid="start-notes">
      <summary>
        <span className="start-block-n" aria-hidden>6</span>
        <span><strong>Proposal notes</strong> <span className="muted">· {filled} of {fields.length} filled · optional, kept for the report</span></span>
      </summary>
      <Fields view={view} paths={fields.map((f) => f.id)} save={save} open={open} />
      {NOTE_GROUPS.map((gid) => {
        const group = view.catalog.groups.find((g) => g.id === gid);
        const items = view.brief.groups[gid] ?? [];
        if (!group || !items.length) return null;
        const shown = group.fields.filter((f) => !(shortGroup[gid] ?? []).includes(f.id));
        return (
          <div key={gid} className="note-group">
            <h3 className="start-sub">{group.label}</h3>
            <ul>
              {items.map((item, i) => (
                <li key={i}>{shown.map((f) => display(item[f.id] ?? EMPTY_RECORD, f)).filter(Boolean).join(" · ") || "—"}</li>
              ))}
            </ul>
          </div>
        );
      })}
      <p className="muted" style={{ fontSize: 13 }}>
        Products, populations and the stated data plan are edited on the <Link href={`/projects/${projectId}/brief`}>full
        brief</Link> until the Inputs step takes them over.
      </p>
      <OpenQuestions view={view} fields={noteFields} onAnswer={onAnswer} />
    </details>
  );
}
