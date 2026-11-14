"use client";

// To do's "Numbers not read" (plan 2026-11-14 §2.1, slice 4; the design text's `NotReadTable`): one row per file with
// numbers no layout picked up. Its loose numbers (outside every table) are grouped by pattern ("12 like “vessel_1” …
// “vessel_12”", one sheet's cells) and marked as not data together: a file's in one go ("Mark as not data…"), or any
// picked across files from the bulk bar, with one reason; one `regions:exclude` per file (scope `outside`). A note a
// person marked as not data is given back with "Restore…" (the fill round's Restore). Under the row: the tables and
// texts not read ("Read this table…", or marked as not data), the tables with numbers no column picks up (their layout
// is checked; a single cell is not set aside here: per-cell "not data" waits for the owner's review of API 3), and why a
// file could not be read. Each answer is the page, written into the cache (writes.ts): nothing else is read again.

import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { MappingReview } from "@/components/delivery/MappingReview";
import { ReadTable, readable } from "@/components/delivery/ReadTable";
import { RestoreForm, type Scope } from "@/components/delivery/Restore";
import { Problem, WITHHELD, tableName, useDecide, type FileRow, type Region } from "@/components/delivery/shared";
import { readPage, writePage } from "@/components/delivery/writes";
import { BulkBar } from "@/components/kit/BulkBar";
import { focusAfter, nextRow } from "@/components/kit/focus";
import { announce } from "@/components/kit/LiveRegion";
import { ReasonForm } from "@/components/kit/Reason";
import { send } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { notReadRows, type LooseGroup, type NotReadRow, type WorkItem } from "@/lib/inputsWork";
import { placeText, plural, whereIs } from "@/lib/words";

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
const EXCLUDE = "/api/v1/projects/{project_id}/delivery/regions:exclude" as const;
const RUN = "/api/v1/projects/{project_id}/delivery:run" as const;
/** Reasons that fit loose numbers (template headers, notes), offered as chips the person still confirms. */
const LOOSE_REASONS = ["a column header, not a value", "a note, not data", "a label of the template, not data"];
const scopeOf = (r: Region): Scope => (r.kind === "prose" ? "unread_prose" : r.kind === "figure" ? "figures" : "regions");
const pickKey = (fileId: string, group: string) => `${fileId}|${group}`;

/** What was marked in this visit, with "Restore…" beside it: the decision undone where it was made. */
type Marked = { id: string; file: FileRow; items: string[]; label: string };

export function NotReadTable({ projectId, items, heading }: {
  projectId: string;
  /** the work model's notread items shown (To do's filters applied) */
  items: WorkItem[];
  /** the group heading's element id: where the focus goes when the last row is settled */
  heading: string;
}) {
  const page = useResource(DELIVERY, { project_id: projectId }).data;
  const client = useQueryClient();
  const { decide, busy, problem } = useDecide();
  const rows = useMemo(() => notReadRows(items, page), [items, page]);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [marking, setMarking] = useState<string | null>(null);        // a file's "Mark as not data…" form
  const [aside, setAside] = useState<string | null>(null);            // an unread table's "not data" form
  const [restoring, setRestoring] = useState<string | null>(null);
  const [reading, setReading] = useState<{ file: FileRow; region: Region } | null>(null);
  const [mapping, setMapping] = useState<string | null>(null);
  const [marked, setMarked] = useState<Marked[]>([]);
  if (!rows.length && !marked.length) return null;

  const order = rows.map((r) => `notread-${r.file.file_id}`);
  const groupsOf = (r: NotReadRow) => r.loose.filter((g) => picked.has(pickKey(r.file.file_id, g.key)));
  const toggle = (set: (f: (was: ReadonlySet<string>) => ReadonlySet<string>) => void, key: string) =>
    set((was) => { const n = new Set(was); if (!n.delete(key)) n.add(key); return n; });

  /** Mark loose numbers as not data: one `regions:exclude` per file, every picked note of the file in it. */
  async function mark(list: { row: NotReadRow; groups: LooseGroup[] }[], why: string) {
    const done: NotReadRow[] = [];
    let left = 0;
    for (const { row, groups } of list) {
      const wheres = groups.flatMap((g) => g.items.map((o) => o.where));
      const { data } = await decide(() => send("post", EXCLUDE, { project_id: projectId },
        { file_sha256: row.file.sha256, regions: wheres, scope: "outside", why }), { refresh: false });
      if (!data) continue;
      writePage(client, projectId, data);
      done.push(row);
      left = data.totals.outside_numeric;
      setMarked((was) => [...was, { id: `${row.file.file_id}-${was.length}`, file: row.file, items: wheres,
                                   label: `${groups.map((g) => g.label).join(", ")} in ${row.file.name}` }]);
    }
    setPicked((was) => new Set([...was].filter((k) => !done.some((r) => k.startsWith(`${r.file.file_id}|`)))));
    setMarking(null);
    if (!done.length) return;
    const said = list.filter((x) => done.includes(x.row)).flatMap((x) => x.groups.map((g) => g.label));
    announce(`${said.join(", ")} marked as not data. ${left ? `${plural(left, "loose number")} left.` : "No loose number is left."}`);
    const decided = done.filter((r) => r.loose.length === list.find((x) => x.row === r)!.groups.length && !r.unread.length && !r.silent.length && !r.failed)
      .map((r) => `notread-${r.file.file_id}`);
    focusAfter(decided, decided.length ? nextRow(order, decided) : `notread-${done[0].file.file_id}`, [heading, "todo-title"]);
  }

  async function setAsideRegion(file: FileRow, r: Region, why: string) {
    const { data } = await decide(() => send("post", EXCLUDE, { project_id: projectId },
      { file_sha256: file.sha256, regions: [r.region_id], scope: scopeOf(r), why }), { refresh: false });
    if (!data) return;
    writePage(client, projectId, data);
    setAside(null);
    announce(`${tableName(r.where, file.name, r.kind)} marked as not data.`);
  }

  async function readAgain(file: FileRow) {
    const { data } = await decide(() => send("post", RUN, { project_id: projectId }, { files: [file.sha256] }), { refresh: false });
    if (data !== null) readPage(client, projectId);
  }

  const pickedRows = rows.map((r) => ({ row: r, groups: groupsOf(r) })).filter((x) => x.groups.length);
  const pickedCount = pickedRows.reduce((n, x) => n + x.groups.reduce((m, g) => m + g.items.length, 0), 0);
  return (
    <div className="batch notread-table" data-testid="notread-table">
      <ul className="batch-rows">
        {rows.map((r) => {
          const fid = r.file.file_id;
          const all = r.loose.length > 0 && r.loose.every((g) => picked.has(pickKey(fid, g.key)));
          const some = r.loose.some((g) => picked.has(pickKey(fid, g.key)));
          const looseCount = r.loose.reduce((n, g) => n + g.items.length, 0);
          const shown = open.has(fid);
          const parts = r.item.label.slice(r.item.label.indexOf(": ") + 2);
          return (
            <li key={fid} className={`batch-row${shown ? " open" : ""}`} data-testid={`notread-${fid}`}>
              <div className="batch-line">
                {r.loose.length > 0 ? (
                  <input type="checkbox" checked={all} ref={(el) => { if (el) el.indeterminate = some && !all; }}
                         aria-label={`Pick the ${plural(looseCount, "loose number")} of ${r.file.name}`} data-testid={`notread-pick-${fid}`}
                         onChange={() => setPicked((was) => {
                           const n = new Set(was);
                           for (const g of r.loose) { if (all) n.delete(pickKey(fid, g.key)); else n.add(pickKey(fid, g.key)); }
                           return n;
                         })} />
                ) : <span className="batch-nopick" aria-hidden="true" />}
                <div className="batch-what">
                  <strong>{r.file.name}</strong>
                  <span className="muted">{parts}</span>
                  {r.item.blocked && <span className="chip neutral" title={r.item.blocked}>can&apos;t be acted on yet</span>}
                  {r.item.why && <span className="chip neutral" title={r.item.why}>{r.item.group === "tidy" ? "blocks nothing" : "holds up nothing yet"}</span>}
                </div>
                <div className="batch-actions">
                  {r.loose.length > 0 && marking !== fid && (
                    <button type="button" className="btn small" onClick={() => setMarking(fid)} data-testid={`notread-mark-open-${fid}`}
                            aria-label={`Mark the ${plural(looseCount, "loose number")} of ${r.file.name} as not data`}>Mark as not data…</button>
                  )}
                  <button type="button" className="link-btn" aria-expanded={shown} aria-controls={`notread-detail-${fid}`}
                          data-testid={`notread-open-${fid}`} aria-label={`${shown ? "Hide" : "Show"} the numbers not read in ${r.file.name}`}
                          onClick={() => toggle(setOpen, fid)}>{shown ? "Hide" : "Show them"}</button>
                </div>
              </div>
              {marking === fid && (
                <ReasonForm action="Mark as not data" actionLabel={`Mark ${some ? "the picked" : "every"} loose number of ${r.file.name} as not data`}
                            label={`Why the loose numbers of ${r.file.name} are not data`} busy={busy} kind="not data" autoFocus
                            suggestions={LOOSE_REASONS} testId={`notread-mark-${fid}`} onCancel={() => setMarking(null)}
                            onSubmit={(why) => mark([{ row: r, groups: some ? groupsOf(r) : r.loose }], why)}>
                  <span className="muted">{some ? `The ${plural(groupsOf(r).reduce((n, g) => n + g.items.length, 0), "picked loose number")}`
                    : `All ${plural(looseCount, "loose number")}`} of {r.file.name}: &quot;Restore…&quot; gives them back.</span>
                </ReasonForm>
              )}
              {shown && (
                <div className="batch-detail" id={`notread-detail-${fid}`}>
                  {r.failed && (
                    <p className="m-0">Could not be read: {r.failed}.{" "}
                      {r.file.state !== "unsupported" && (
                        <button type="button" className="link-btn" disabled={busy} onClick={() => void readAgain(r.file)}
                                aria-label={`Read ${r.file.name} again`} data-testid={`notread-run-${fid}`}>Read it again</button>
                      )}</p>
                  )}
                  {r.loose.length > 0 && (
                    <>
                      <h4 className="delivery-sub">Loose numbers: text with a number outside every table</h4>
                      <ul className="plain-list">
                        {r.loose.map((g, i) => (
                          <li key={g.key}>
                            <label className="notread-group">
                              <input type="checkbox" checked={picked.has(pickKey(fid, g.key))} onChange={() => toggle(setPicked, pickKey(fid, g.key))}
                                     aria-label={`Pick ${g.label} in ${r.file.name}`} data-testid={`notread-pick-${fid}-${i}`} />
                              <span>{g.label} <span className="muted">· {g.place}</span></span>
                            </label>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {r.unread.length > 0 && (
                    <>
                      <h4 className="delivery-sub">Tables and texts not read</h4>
                      <ul className="plain-list">
                        {r.unread.map((g) => (
                          <li key={g.region_id}>
                            {tableName(g.where, r.file.name, g.kind)} <span className="muted">{g.caption === null ? WITHHELD : g.caption}</span>{" "}
                            {readable(g) && (
                              <button type="button" className="link-btn" onClick={() => setReading({ file: r.file, region: g })}
                                      aria-label={`Read ${tableName(g.where, r.file.name)}`} data-testid={`notread-read-${g.region_id}`}>Read this table…</button>
                            )}{" "}
                            {aside !== g.region_id && (
                              <button type="button" className="link-btn" onClick={() => setAside(g.region_id)}
                                      aria-label={`Mark ${tableName(g.where, r.file.name, g.kind)} as not data`}
                                      data-testid={`notread-aside-${g.region_id}`}>Not data…</button>
                            )}
                            {aside === g.region_id && (
                              <ReasonForm action="Mark as not data" actionLabel={`Mark ${tableName(g.where, r.file.name, g.kind)} as not data`}
                                          label={`Why ${tableName(g.where, r.file.name, g.kind)} is not data`} busy={busy} autoFocus kind="not data"
                                          suggestions={["a scratch table, not data", "a note, not data"]} testId={`notread-aside-${g.region_id}`}
                                          onCancel={() => setAside(null)} onSubmit={(why) => setAsideRegion(r.file, g, why)} />
                            )}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {r.silent.length > 0 && (
                    <>
                      <h4 className="delivery-sub">Numbers in tables no column picks up</h4>
                      <ul className="plain-list">
                        {r.silent.map((g) => (
                          <li key={g.region_id}>
                            {plural(g.silent, "number")} in {tableName(g.where, r.file.name)} <span className="muted">({placeText(g.where)})</span>:
                            {" "}correct its layout so a column reads them.{" "}
                            {g.mapping_id && (
                              <button type="button" className="link-btn" onClick={() => setMapping(g.mapping_id)}
                                      aria-label={`Check the layout of ${tableName(g.where, r.file.name)}`}
                                      data-testid={`notread-layout-${g.region_id}`}>Check its layout</button>
                            )}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {r.marked.length > 0 && (
                    <>
                      <h4 className="delivery-sub">Marked as not data</h4>
                      <ul className="plain-list">
                        {r.marked.map((o, i) => (
                          <li key={o.where}>
                            “{o.text ?? WITHHELD}” <span className="muted">{whereIs(o.where).place}</span>{" "}
                            {restoring !== `${fid}|${o.where}` ? (
                              <button type="button" className="link-btn" onClick={() => setRestoring(`${fid}|${o.where}`)}
                                      aria-label={`Restore the note at ${whereIs(o.where).place} of ${r.file.name}`}
                                      data-testid={`notread-restore-${fid}-${i}`}>Restore…</button>
                            ) : (
                              <RestoreForm projectId={projectId} file={r.file} items={[o.where]} scope="outside" testId={`notread-restore-${fid}-${i}`}
                                           label={`the note at ${whereIs(o.where).place} of ${r.file.name}`} onDone={() => setRestoring(null)} />
                            )}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <Problem text={problem} testId="notread-problem" />
      {marked.length > 0 && (
        <div className="notread-marked" data-testid="notread-marked">
          <strong>Marked as not data just now</strong>
          <ul className="plain-list">
            {marked.map((m) => (
              <li key={m.id}>
                {m.label}{" "}
                {restoring !== m.id ? (
                  <button type="button" className="link-btn" onClick={() => setRestoring(m.id)} aria-label={`Restore ${m.label}`}
                          data-testid={`notread-undo-${m.id}`}>Restore…</button>
                ) : (
                  <RestoreForm projectId={projectId} file={m.file} items={m.items} scope="outside" label={m.label} testId={`notread-undo-${m.id}`}
                               onDone={() => { setRestoring(null); setMarked((was) => was.filter((x) => x.id !== m.id)); }} />
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <BulkBar count={pickedRows.length} noun="file" label="Mark the picked loose numbers as not data" onClear={() => setPicked(new Set())}
               testId="bulk-notread-bar">
        <ReasonForm action="Mark as not data" actionLabel={`Mark the ${plural(pickedCount, "picked loose number")} as not data`}
                    label="Why the picked loose numbers are not data" busy={busy} kind="not data" suggestions={LOOSE_REASONS} testId="bulk-notread"
                    onSubmit={(why) => mark(pickedRows, why)}>
          <span className="muted">{plural(pickedCount, "loose number")} in {plural(pickedRows.length, "file")}: one decision per file.</span>
        </ReasonForm>
      </BulkBar>
      {reading && <ReadTable projectId={projectId} file={reading.file} region={reading.region} onClose={() => setReading(null)}
                             onStored={(id) => { setReading(null); setMapping(id); }} />}
      {mapping && <MappingReview projectId={projectId} mappingId={mapping} onClose={() => setMapping(null)}
                                 returnFocus={() => document.getElementById(heading)} />}
    </div>
  );
}
