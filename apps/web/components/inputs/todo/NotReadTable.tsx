"use client";

// To do's "Numbers not read" (plan 2026-11-14 §2.1, slice 4; the design text's `NotReadTable`): one row per file with
// numbers no layout picked up. Its loose numbers (outside every table) are grouped by pattern ("12 like “vessel_1” …
// “vessel_12”", one sheet's cells) and marked as not data together: a file's in one go ("Mark as not data…"), or any
// picked across files from the bulk bar, with one reason; one `regions:exclude` per file (scope `outside`). A note a
// person marked as not data is given back with "Restore…" (the fill round's Restore), who marked it, when and why said
// above it. Under the row: the tables and texts not read ("Read this table…", or marked as not data), the tables with
// numbers no part of their layout reads, each cell listed with why (read-only: a single cell is not set aside here,
// per-cell "not data" waits for the owner's review of API 3), and why a file could not be read. Each answer is the page,
// written into the cache (writes.ts): nothing else is read again.
//
// Final review: a refusal is said on the row of the file it refused, never hidden by a later file's success (CODE-2);
// what was marked in this visit stays listed with "Restore…" and a line saying what was done, after the last row goes
// (To do keeps it: `visit.tsx`, CODE-3); a marked note says who, when and why (CODE-5); a row says only a reason its group
// does not (CODE-9); a batch is said by file (CODE-10); a table's layout opens at the version and on the table the row
// names, a table the newest approved version cannot read says why, and a read table of a file whose studies are all
// confirmed with the sheet form can be set aside whole (OWN-2 a, b).

import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { ReadTable, readable } from "@/components/delivery/ReadTable";
import { DecisionNote, RestoreForm, type Scope } from "@/components/delivery/Restore";
import { Problem, WITHHELD, tableName, useDecide, type FileRow, type Region } from "@/components/delivery/shared";
import { readPage, writePage } from "@/components/delivery/writes";
import { BulkBar } from "@/components/kit/BulkBar";
import { focusAfter, nextRow } from "@/components/kit/focus";
import { announce } from "@/components/kit/LiveRegion";
import { ReasonForm } from "@/components/kit/Reason";
import { send } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { markedText, noLayoutReads, notReadRows, type LooseGroup, type NotReadRow, type WorkItem } from "@/lib/inputsWork";
import { findingsInline, placeText, plural, unreadWhy, whereIs } from "@/lib/words";

import { useTodoVisit, type Marked } from "./visit";

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
const EXCLUDE = "/api/v1/projects/{project_id}/delivery/regions:exclude" as const;
const RUN = "/api/v1/projects/{project_id}/delivery:run" as const;
/** Reasons that fit loose numbers (template headers, notes), offered as chips the person still confirms. */
const LOOSE_REASONS = ["a column header, not a value", "a note, not data", "a label of the template, not data"];
const scopeOf = (r: Region): Scope => (r.kind === "prose" ? "unread_prose" : r.kind === "figure" ? "figures" : "regions");
const pickKey = (fileId: string, group: string) => `${fileId}|${group}`;
const SHOWN_CELLS = 8;   // the unread cells of one reason listed before "and n more"

/** A read table's numbers not read, by why: "Not a plain number: cell F7 “1,2”"; the cells of one sheet named once. */
function UnreadCells({ region, testId }: { region: Region; testId: string }) {
  const byWhy = new Map<string, Region["silent_cells"]>();
  for (const c of region.silent_cells ?? []) byWhy.set(c.why, [...(byWhy.get(c.why) ?? []), c]);
  const more = region.silent - (region.silent_cells ?? []).length;
  return (
    <ul className="plain-list notread-cells" data-testid={testId}>
      {[...byWhy.entries()].map(([why, cells]) => {
        const said = unreadWhy(why);
        const sheet = whereIs(cells[0].where).place.replace(/, cells? .*$/, "");
        return (
          <li key={why}>
            <strong>{said.charAt(0).toUpperCase()}{said.slice(1)}</strong> ({cells.length}): {sheet !== whereIs(cells[0].where).place ? `${sheet}, ` : ""}
            {cells.slice(0, SHOWN_CELLS).map((c) => {
              const place = whereIs(c.where).place;
              const cell = place.startsWith(`${sheet}, `) ? place.slice(sheet.length + 2) : place;
              return `${cell} ${c.text === null ? `(${WITHHELD})` : `“${c.text}”`}`;
            }).join(", ")}
            {cells.length > SHOWN_CELLS ? `, and ${cells.length - SHOWN_CELLS} more` : ""}
          </li>
        );
      })}
      {more > 0 && <li className="muted">and {plural(more, "more number")} not listed</li>}
    </ul>
  );
}

/** What was marked as not data in this visit, each with "Restore…", and a line that says what the last batch did: it
 *  stays after the table's last row goes (review CODE-3; owner-job gap 5). `alone`: shown by To do itself, its table gone. */
export function MarkedNow({ projectId, entries, said, alone = false, titleId }: {
  projectId: string; entries: Marked[]; said: string | null; alone?: boolean;
  /** its heading's id (tabIndex -1): where the focus goes when the last row it was marked from goes */
  titleId: string;
}) {
  const { unmark } = useTodoVisit();
  const [restoring, setRestoring] = useState<string | null>(null);
  if (!entries.length) return null;
  return (
    <div className={`notread-marked${alone ? " todo-group" : ""}`} data-testid="notread-marked">
      <strong id={titleId} tabIndex={-1}>Marked as not data just now</strong>
      {said && <p className="banner ok m-4-0-0" data-testid="notread-marked-said">{said}</p>}
      <ul className="plain-list">
        {entries.map((m) => (
          <li key={m.id}>
            {m.label}{" "}
            {restoring !== m.id ? (
              <button type="button" className="link-btn" onClick={() => setRestoring(m.id)} aria-label={`Restore ${m.label}`}
                      data-testid={`notread-undo-${m.id}`}>Restore…</button>
            ) : (
              <RestoreForm projectId={projectId} file={m.file} items={m.items} scope="outside" label={m.label} testId={`notread-undo-${m.id}`}
                           onDone={() => { setRestoring(null); unmark(m.id); }} />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function NotReadTable({ projectId, items, heading, group, shared }: {
  projectId: string;
  /** the work model's notread items shown (To do's filters applied) */
  items: WorkItem[];
  /** the group heading's element id: where the focus goes when the last row is settled */
  heading: string;
  /** the To do group the table is in (`notread`, or `tidy`): what it marks in this visit is listed under it */
  group: string;
  /** the reason the group says once for every row (not said again on a row) */
  shared?: string;
}) {
  const page = useResource(DELIVERY, { project_id: projectId }).data;
  const client = useQueryClient();
  const visit = useTodoVisit();
  const { decide, busy, problem } = useDecide();
  const rows = useMemo(() => notReadRows(items, page), [items, page]);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [marking, setMarking] = useState<string | null>(null);        // a file's "Mark as not data…" form
  const [aside, setAside] = useState<string | null>(null);            // an unread or read table's "not data" form
  const [restoring, setRestoring] = useState<string | null>(null);
  const [reading, setReading] = useState<{ file: FileRow; region: Region } | null>(null);
  // a refusal, said on the row of the file it refused (review CODE-2), until that file is marked or its row is gone
  const [problems, setProblems] = useState<Record<string, string>>({});
  const mine = visit.marked.filter((m) => m.group === group);
  if (!rows.length && !mine.length) return null;

  const order = rows.map((r) => `notread-${r.file.file_id}`);
  const groupsOf = (r: NotReadRow) => r.loose.filter((g) => picked.has(pickKey(r.file.file_id, g.key)));
  const toggle = (set: (f: (was: ReadonlySet<string>) => ReadonlySet<string>) => void, key: string) =>
    set((was) => { const n = new Set(was); if (!n.delete(key)) n.add(key); return n; });

  /** Mark loose numbers as not data: one `regions:exclude` per file, every picked note of the file in it. Each file's
   *  refusal is kept for its own row; one file's success never hides another's refusal (review CODE-2). */
  async function mark(list: { row: NotReadRow; groups: LooseGroup[] }[], why: string) {
    const done: { row: NotReadRow; groups: LooseGroup[] }[] = [];
    const refused: Record<string, string> = {};
    let left: number | null = null;
    for (const { row, groups } of list) {
      const wheres = groups.flatMap((g) => g.items.map((o) => o.where));
      const { data, problem: said } = await decide(() => send("post", EXCLUDE, { project_id: projectId },
        { file_sha256: row.file.sha256, regions: wheres, scope: "outside", why }), { refresh: false });
      if (!data) { refused[row.file.file_id] = said ?? "It was not marked."; continue; }
      writePage(client, projectId, data);
      done.push({ row, groups });
      left = data.totals.outside_numeric;
    }
    const doneIds = new Set(done.map((d) => d.row.file.file_id));
    setProblems((was) => ({ ...Object.fromEntries(Object.entries(was).filter(([fid]) => !doneIds.has(fid))), ...refused }));
    setPicked((was) => new Set([...was].filter((k) => !doneIds.has(k.split("|")[0]))));
    setMarking(null);
    const text = markedText(done.map((d) => ({ file: d.row.file.name, groups: d.groups })), left ?? 0, Object.keys(refused).length);
    if (done.length) {
      visit.mark(done.map((d) => ({ file: d.row.file, group, items: d.groups.flatMap((g) => g.items.map((o) => o.where)),
                                    label: `${d.groups.map((g) => g.label).join(", ")} in ${d.row.file.name}` })), text);
    }
    announce(text);
    if (!done.length) return;
    const decided = done.filter((d) => d.row.loose.length === d.groups.length && !d.row.unread.length && !d.row.silent.length && !d.row.failed)
      .map((d) => `notread-${d.row.file.file_id}`);
    focusAfter(decided, decided.length ? nextRow(order, decided) : `notread-${done[0].row.file.file_id}`, [heading, `notread-marked-${group}-title`, "notread-marked-title", "todo-title"]);
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
  const refusedRows = rows.filter((r) => problems[r.file.file_id]);
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
                  {r.item.blocked && <span className="chip neutral">can&apos;t be acted on here</span>}
                  {!r.item.blocked && r.item.why && r.item.group !== "tidy" && r.item.why !== shared && (
                    <span className="chip neutral" title={r.item.why}>holds up nothing yet</span>
                  )}
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
              {r.item.blocked && <p className="muted fs-13 m-0" data-testid={`notread-blocked-${fid}`}>{r.item.blocked}</p>}
              <Problem text={problems[fid] ?? null} testId={`notread-row-problem-${fid}`} />
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
                      <h4 className="delivery-sub">Numbers in tables no part of the layout reads</h4>
                      <ul className="plain-list">
                        {r.silent.map((g) => {
                          const none = noLayoutReads(g);
                          return (
                            <li key={g.region_id} data-testid={`notread-silent-${g.region_id}`}>
                              {plural(g.silent, "number")} in {tableName(g.where, r.file.name)} <span className="muted">({placeText(g.where)})</span>,
                              {" "}read with version {g.mapping_version} of its layout:
                              <UnreadCells region={g} testId={`notread-cells-${g.region_id}`} />
                              {g.newer && (
                                <p className="m-0" data-testid={`notread-newer-${g.region_id}`}>Version {g.newer.version} of its layout, the newest approved,
                                  {" "}does not read this table: {findingsInline(g.newer.findings, g.newer.constants)}.
                                  {" "}Correct the layout for this table, or say where the table states what it misses.</p>
                              )}
                              <p className="muted m-0">{none ? "No table layout reads these: they are not plain numbers. Setting a single cell aside as not data waits for the owner's decision; correct the file and send it again, or set the whole table aside."
                                : "Correct its layout so a column or a row rule reads them, or leaves them out with a reason."}</p>
                              <span className="row gap-8">
                                {g.mapping_id && (
                                  <button type="button" className="link-btn" data-testid={`notread-layout-${g.region_id}`}
                                          aria-label={`Check the layout of ${tableName(g.where, r.file.name)}, version ${g.mapping_version}`}
                                          onClick={() => visit.walk({ queue: false, at: 0, heading, list: [{
                                            id: g.mapping_id!, version: g.mapping_version!, at: { file_sha256: r.file.sha256, region_id: g.region_id },
                                          }] })}>Check its layout</button>
                                )}
                                {r.elsewhere && aside !== g.region_id && (
                                  <button type="button" className="link-btn" onClick={() => setAside(g.region_id)} data-testid={`notread-aside-${g.region_id}`}
                                          aria-label={`Mark ${tableName(g.where, r.file.name)} as not data`}>Not data…</button>
                                )}
                              </span>
                              {r.elsewhere && aside === g.region_id && (
                                <ReasonForm action="Mark as not data" actionLabel={`Mark ${tableName(g.where, r.file.name)} as not data`}
                                            label={`Why ${tableName(g.where, r.file.name)} is not data`} busy={busy} autoFocus kind="not data"
                                            suggestions={["its study is confirmed with the sheet form"]} testId={`notread-aside-${g.region_id}`}
                                            onCancel={() => setAside(null)} onSubmit={(why) => setAsideRegion(r.file, g, why)}>
                                  <span className="muted">Every study and product read from {r.file.name} is confirmed with the sheet form: setting the
                                    whole table aside loses nothing that is loaded. &quot;Restore…&quot; in Client files gives it back.</span>
                                </ReasonForm>
                              )}
                            </li>
                          );
                        })}
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
                            {restoring !== `${fid}|${o.where}` && (
                              <button type="button" className="link-btn" onClick={() => setRestoring(`${fid}|${o.where}`)}
                                      aria-label={`Restore the note at ${whereIs(o.where).place} of ${r.file.name}`}
                                      data-testid={`notread-restore-${fid}-${i}`}>Restore…</button>
                            )}
                            {/* who marked it, when and why, above its Restore form (review CODE-5), as Client files says it */}
                            <DecisionNote decision={o.decision} restored={o.restored} testId={`notread-decision-${fid}-${i}`} />
                            {restoring === `${fid}|${o.where}` && (
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
      {/* a refusal a row says is said there; one the row cannot say (no row is left) is said here */}
      {!refusedRows.length && <Problem text={problem} testId="notread-problem" />}
      <MarkedNow projectId={projectId} entries={mine} said={visit.said} titleId={`notread-marked-${group}-title`} />
      <BulkBar count={pickedRows.length} noun="file" label="Mark the picked loose numbers as not data" onClear={() => setPicked(new Set())}
               testId="bulk-notread-bar">
        <ReasonForm action="Mark as not data" actionLabel={`Mark the ${plural(pickedCount, "picked loose number")} as not data`}
                    label="Why the picked loose numbers are not data" busy={busy} kind="not data" suggestions={LOOSE_REASONS} testId="bulk-notread"
                    onSubmit={(why) => mark(pickedRows, why)}>
          <span className="muted">{plural(pickedCount, "loose number")} in {plural(pickedRows.length, "file")}: one decision per file.</span>
        </ReasonForm>
        {refusedRows.length > 0 && (
          <ul className="bulk-problems" data-testid="bulk-notread-problems">
            {refusedRows.map((r) => <li key={r.file.file_id}>{r.file.name}: {problems[r.file.file_id]}</li>)}
          </ul>
        )}
      </BulkBar>
      {reading && <ReadTable projectId={projectId} file={reading.file} region={reading.region} onClose={() => setReading(null)}
                             onStored={(id) => { setReading(null); visit.walk({ queue: false, at: 0, heading, list: [{
                               id, at: { file_sha256: reading.file.sha256, region_id: reading.region.region_id } }] }); }} />}
    </div>
  );
}
