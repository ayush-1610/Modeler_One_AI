"use client";

// To do's "Check how tables are read" (plan 2026-11-14 §2.1, slice 4; the design text's `LayoutQueue`): the table layouts
// to check as a queue, one row per layout version, ordered by how many files use it. A row says what table it reads and
// where, and opens on its columns in one line ("time ← 'Time (h)' · concentration ← 'Conc (ng/mL)'", read from the
// layout at that version, only when opened). "Check layout" opens the layout at the row's version in queue mode:
// approve ("Approve and next"), reject with the reason, correct it in the layout form, Previous and Next. Checking each
// layout is the default; only the layouts that read a table as not data can be approved together, each approval's note
// saying it was "approved with N other layouts". Decisions answer the layout, written into the cache; the page is read
// again once (its files are read again with the decision).

import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { MappingReview } from "@/components/delivery/MappingReview";
import { Problem, useDecide } from "@/components/delivery/shared";
import { writeMapping } from "@/components/delivery/writes";
import { announce } from "@/components/kit/LiveRegion";
import { ReasonForm } from "@/components/kit/Reason";
import { send } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { columnSummary, layoutRows, type LayoutRow, type WorkItem } from "@/lib/inputsWork";
import { plural, tableKindText } from "@/lib/words";

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
const MAPPING = "/api/v1/projects/{project_id}/delivery/mappings/{mapping_id}" as const;
const APPROVE = `${MAPPING}:approve` as const;

/** A layout's columns in one line, read from the layout at the row's version once the row is opened. */
function Columns({ projectId, row }: { projectId: string; row: LayoutRow }) {
  const read = useResource(MAPPING, { project_id: projectId, mapping_id: row.mapping.mapping_id }, { query: { version: String(row.mapping.version) } });
  const m = read.data;
  if (read.problem) return <Problem text={read.problem} />;
  if (!m) return <p className="muted m-0">Reading its columns…</p>;
  return (
    <p className="layout-columns m-0" data-testid={`todo-layout-columns-${row.mapping.mapping_id}`}>
      {m.not_data_reason ? `Read as not data: ${m.not_data_reason}` : columnSummary(m.columns)}
    </p>
  );
}

export function LayoutQueue({ projectId, items, heading }: {
  projectId: string;
  /** the work model's layout items shown (To do's filters applied) */
  items: WorkItem[];
  /** the group heading's element id: where the focus goes when the dialog closes on a settled row */
  heading: string;
}) {
  const page = useResource(DELIVERY, { project_id: projectId }).data;
  const client = useQueryClient();
  const { decide, busy, problem } = useDecide();
  const rows = useMemo(() => layoutRows(items, page), [items, page]);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  // the queue the dialog walks: the rows as they were when it opened, so settled ones keep their place
  const [queue, setQueue] = useState<{ list: { id: string; version: number }[]; at: number } | null>(null);
  const [bulk, setBulk] = useState(false);
  if (!rows.length) return null;

  const notData = rows.filter((r) => r.notData && !r.item.blocked);
  const key = (r: LayoutRow) => `${r.mapping.mapping_id}@${r.mapping.version}`;
  const where = (r: LayoutRow) => r.mapping.used_in[0]?.file ?? "no file";

  /** Approve every layout that reads its table as not data, one by one, each note naming the others approved with it. */
  async function approveNotData(note: string) {
    const others = notData.length - 1;
    const said = others ? `approved with ${plural(others, "other layout")} that read a table as not data` : "";
    let approved = 0;
    for (const r of notData) {
      const { data } = await decide(() => send("post", APPROVE, { project_id: projectId, mapping_id: r.mapping.mapping_id },
        { version: r.mapping.version, note: [note.trim(), said].filter(Boolean).join(" · ") }), { refresh: false });
      if (!data) break;
      writeMapping(client, projectId, data);
      approved += 1;
    }
    if (approved) {
      setBulk(false);
      announce(`${plural(approved, "layout")} that read a table as not data approved. ${plural(rows.length - approved, "layout")} left to check.`);
      document.getElementById(heading)?.focus();
    }
  }

  return (
    <div className="batch layout-queue" data-testid="layout-queue">
      {notData.length > 0 && (
        <div className="layout-notdata">
          {!bulk ? (
            <button type="button" className="btn small" onClick={() => setBulk(true)} data-testid="layout-notdata-open"
                    aria-label={`Approve the ${plural(notData.length, "layout")} that read a table as not data`}>
              Approve the {notData.length === 1 ? "“not data” reading" : `${notData.length} “not data” readings`}…</button>
          ) : (
            <ReasonForm action={notData.length === 1 ? "Approve" : `Approve ${notData.length}`} optional busy={busy} onSubmit={approveNotData}
                        actionLabel={`Approve the ${plural(notData.length, "layout")} that read a table as not data`} kind="layout approved"
                        label="A note on the approvals" testId="layout-notdata" onCancel={() => setBulk(false)}
                        suggestions={["README and notes sheets, not data"]}>
              <span className="muted">{notData.map((r) => `${tableKindText(r.mapping.kind)} · ${r.mapping.used_in.map((u) => u.file).join(", ")}`).join("; ")}
                {notData.length > 1 && <>: each approval&apos;s note says it was approved with the others</>}</span>
            </ReasonForm>
          )}
        </div>
      )}
      <ul className="batch-rows">
        {rows.map((r, i) => {
          const shown = open.has(key(r));
          const rowId = r.item.where.anchor ?? `todo-layout-${r.mapping.mapping_id}`;
          return (
            <li key={key(r)} className={`batch-row${r.item.open ? "" : " quiet"}`} data-testid={rowId}>
              <div className="batch-line" data-testid={rowId.replace(/^todo-layout-/, "delivery-mapping-")}>
                <div className="batch-what">
                  <strong>{r.item.label}</strong>
                  <span className="muted">{r.item.detail}{r.mapping.used_in.length > 1 ? ` · used in ${plural(r.mapping.used_in.length, "table")}` : ""}</span>
                  {r.kept && <span className="chip neutral" title="Kept in the record; no dataset is made from it">kept, not used by the model</span>}
                  {r.item.blocked && <span className="chip neutral" title={r.item.blocked}>Reading…</span>}
                  {!r.item.blocked && r.item.why && <span className="chip neutral" title={r.item.why}>{r.item.group === "tidy" ? "blocks nothing" : "holds up nothing yet"}</span>}
                </div>
                <div className="batch-actions">
                  <button type="button" className="link-btn" aria-expanded={shown} data-testid={`todo-layout-show-${key(r)}`}
                          aria-label={`${shown ? "Hide" : "Show"} the columns of the ${tableKindText(r.mapping.kind)} layout in ${where(r)}`}
                          onClick={() => setOpen((was) => { const n = new Set(was); if (!n.delete(key(r))) n.add(key(r)); return n; })}>
                    {shown ? "Hide its columns" : "Its columns"}</button>
                  <button type="button" className="btn small" disabled={Boolean(r.item.blocked)}
                          data-testid={rowId.replace(/^todo-layout-/, "delivery-mapping-open-")}
                          aria-label={`Check the layout of the ${tableKindText(r.mapping.kind)} in ${where(r)}, version ${r.mapping.version}`}
                          onClick={() => setQueue({ list: rows.map((x) => ({ id: x.mapping.mapping_id, version: x.mapping.version })), at: i })}>
                    Check layout</button>
                </div>
              </div>
              {shown && <Columns projectId={projectId} row={r} />}
            </li>
          );
        })}
      </ul>
      <Problem text={problem} testId="layout-problem" />
      {queue && (
        <MappingReview projectId={projectId} mappingId={queue.list[queue.at].id} version={queue.list[queue.at].version}
                       onClose={() => setQueue(null)} returnFocus={() => document.getElementById(heading)}
                       queue={{
                         at: queue.at, total: queue.list.length,
                         go: (delta) => setQueue((q) => (q ? { ...q, at: Math.max(0, Math.min(q.list.length - 1, q.at + delta)) } : q)),
                         stored: (version) => setQueue((q) => (q ? { ...q, list: q.list.map((x, n) => (n === q.at ? { ...x, version } : x)) } : q)),
                       }} />
      )}
    </div>
  );
}
