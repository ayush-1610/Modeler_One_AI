"use client";

// The Delivery section on Inputs (contracts 2026-11-12 §8.10): what arrived from the client, read by code and reviewed
// by exception. On Inputs it sits in the Client files area (plan 2026-11-14 slice 1), under the one table of files
// (slice 2: each file's own reading, `FileItem`, opens under that file's row there, so no second list of files is kept
// here): when the files arrived and what of them was read (the totals behind "Details"), and one line saying where each
// study, product and the compound is confirmed: on its card in its area (plan 2026-11-14 slice 3, components/inputs/cards).
// The table layouts to check, the values to link and the numbers not read are settled in To do, in its batch tables
// (slice 4: one home per decision); what to ask the client is in To do too. The section is not shown while the pipeline
// is off (`enabled` false); the page is read again every few seconds while a file is being read (`useDeliveryRefresh`,
// once for the page), and not while nothing is.

import { hashKey, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { send } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { WorkItem, WorkModel } from "@/lib/inputsWork";
import {
  AREA_NAME, type Tab, engineWords, whereIs, findingsInline, layoutOrigin, plural as count, regionKindText, rulesText, stageText, whenText,
} from "@/lib/words";

import { FileLinks } from "./LinkElsewhere";
import type { MappingOpen } from "./MappingReview";
import { ReadTable, readable } from "./ReadTable";
import { DecisionNote, NotDataNote, RestoreForm, restorable, restorableNote } from "./Restore";
import {
  ChipFor, FILE_STATE, MAPPING_STATE, Problem, REGION_STATE, WITHHELD, Why, fieldText, plural, tableName,
  useDecide, when, type FileRow, type Page, type Region,
} from "./shared";
import { pageKey, readPage, writePage } from "./writes";

const RUN = "/api/v1/projects/{project_id}/delivery:run" as const;
const EXCLUDE = "/api/v1/projects/{project_id}/delivery/regions:exclude" as const;
type Decide = ReturnType<typeof useDecide>["decide"];

/** The decision's scope for a region of this kind: a table's numbers leave silent loss only as a region. */
const scopeOf = (r: Region) => (r.kind === "prose" ? "unread_prose" : r.kind === "figure" ? "figures" : "regions");

/** Why a region is not read, or set aside by a rule, in plain words; the reader's own text stays in its tooltip. */
function reasonWords(r: Region): string {
  const rule = /^coverage\.excluded_by_rule\.[a-z_]+: ([\s\S]*)$/.exec(r.reason);
  if (rule) return `set aside by the intake rules: ${rule[1]}`;
  if (r.state !== "unread") return r.reason;
  if (r.kind === "table") return r.mapping_status === "rejected" ? "its layout was rejected: no layout reads it now" : "no layout reads it yet";
  return /no model is configured/.test(r.reason) ? "not read: no text reader is set up" : "not read yet";
}

function coverageLine(f: FileRow): string {
  const c = f.coverage;
  if (!c) return "";
  return [`${plural(c.regions, "table or text", "tables and texts")}: ${c.regions_mapped} read, ${c.regions_excluded} not data, ${c.regions_unread} not read`,
          c.silent_loss ? `${plural(c.silent_loss, "number")} in tables not read` : "", c.outside_numeric ? plural(c.outside_numeric, "loose number") : "",
          c.values_unassigned ? `${plural(c.values_unassigned, "value")} not linked to a study` : "",
          c.needs_ocr_pages.length ? `${plural(c.needs_ocr_pages.length, "page")} to read as images` : "",
          c.anchors_unresolved ? `${plural(c.anchors_unresolved, "place")} not found again` : ""].filter(Boolean).join(" · ");
}

function FileItem({ projectId, file, first, decide, busy, onMapping, inRow = false }: {
  projectId: string; file: FileRow;
  /** a repeat's regions are listed on the first arrival of the same bytes */
  first: FileRow | undefined; decide: Decide; busy: boolean; onMapping: (open: MappingOpen) => void;
  /** under the file's row in the table of files, which says its name and its one status (plan 2026-11-14 §2 rule 4) */
  inRow?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [aside, setAside] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<string | null>(null);   // a region's id, or a note's place
  const [reading, setReading] = useState<Region | null>(null);       // a table given its first layout
  const client = useQueryClient();
  const shown = file.repeat && first ? first : file;
  // a note stops counting by a person's "not data" (its `decision`: who, when, why), which can be restored, or when a
  // table that is read cites it (no decision: a fact read once for the table)
  const marked = restorableNote;
  const noteName = (o: FileRow["outside"][number]) => (o.text ? `the note “${o.text}” of ${file.name}` : `the note at ${whereIs(o.where).place} of ${file.name}`);
  // the answer is the page, written into the cache: only the cards it changed are read again (writes.ts)
  const exclude = (regions: string[], scope: "regions" | "unread_prose" | "figures" | "outside") => async (why: string) => {
    const { data } = await decide(() => send("post", EXCLUDE, { project_id: projectId }, { file_sha256: file.sha256, regions, scope, why }),
                                  {});
    if (data) { writePage(client, projectId, data); setAside(null); }
    return Boolean(data);
  };
  const readAgain = async () => {
    const { data } = await decide(() => send("post", RUN, { project_id: projectId }, { files: [file.sha256] }), {});
    if (data !== null) readPage(client, projectId);
  };
  return (
    <li className="delivery-file" data-testid={`delivery-file-${file.file_id}`} data-state={file.state}>
      <div className="delivery-file-line">
        {!inRow && <ChipFor state={file.state} table={FILE_STATE} testId={`delivery-file-state-${file.file_id}`} />}
        {!inRow && <span className="delivery-file-name">{file.name}</span>}
        {file.container && <span className="muted">in {file.container.name}</span>}
        {file.repeat && <span className="chip neutral">the same file arrived before</span>}
        {file.blinded && <span className="chip neutral" data-testid={`delivery-file-blinded-${file.file_id}`}>holds a blinded study</span>}
        <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)} data-testid={`delivery-file-toggle-${file.file_id}`}>
          {open ? "Hide its tables and texts" : "Show its tables and texts"}</button>
        <button type="button" className="btn tiny" disabled={busy} aria-label={`Read ${file.name} again`} data-testid={`delivery-file-run-${file.file_id}`}
                onClick={() => void readAgain()}>Read again</button>
      </div>
      {file.reason && <p className="delivery-file-why" data-testid={`delivery-file-reason-${file.file_id}`}>{file.reason}</p>}
      {file.coverage && <p className="muted fs-13 m-0" data-testid={`delivery-file-coverage-${file.file_id}`}>{coverageLine(file)}</p>}
      {/* where a person linked its values, and "Link elsewhere…" (review INT-5: a link is changed by linking again) */}
      <FileLinks projectId={projectId} file={file} />
      {file.legacy_refusal && <p className="muted fs-13 m-0">Not read onto the cards below: {file.legacy_refusal}</p>}
      {file.run?.state === "failed" && file.run.error && <p className="delivery-file-why">{file.run.error}</p>}
      {open && (
        <div className="delivery-file-detail">
          {shown.regions.length > 0 ? (
            <div className="table-scroll">
              <table className="delivery-regions" data-testid={`delivery-regions-${file.file_id}`}>
                <caption className="sr-only">The tables and texts of {file.name}</caption>
                <thead><tr><th>Where</th><th>What</th><th>State</th><th>Layout</th><th className="num">Numbers</th><th /></tr></thead>
                <tbody>
                  {shown.regions.map((r) => (
                    <tr key={r.region_id} data-testid={`delivery-region-${r.region_id}`}>
                      <td data-label="Where">{whereIs(r.where).place}</td>
                      <td data-label="What">{regionKindText(r.kind, r.table_kind)}
                        <div className="muted fs-12">{r.caption === null ? WITHHELD : r.caption}</div></td>
                      <td data-label="State"><ChipFor state={r.state} table={REGION_STATE} />
                        {!restorable(r) && r.reason && <div className="muted fs-12" title={r.reason} data-testid={`delivery-region-reason-${r.region_id}`}>{reasonWords(r)}</div>}
                        {/* the person's decision in force, or else the restore that gave the region back (it stays its record) */}
                        <NotDataNote region={r} testId={`delivery-region-decision-${r.region_id}`} /></td>
                      <td data-label="Layout">
                        {r.mapping_id ? (
                          <button type="button" className="delivery-chip-btn"
                                  onClick={() => onMapping({ id: r.mapping_id as string, version: r.mapping_version ?? undefined,
                                                             at: { file_sha256: shown.sha256, region_id: r.region_id } })}
                                  data-testid={`delivery-region-mapping-${r.region_id}`} title="Review how this table is read">
                            <ChipFor state={r.mapping_status} table={MAPPING_STATE} /> version {r.mapping_version}{r.origin ? ` · ${layoutOrigin(r.origin)}` : ""}
                          </button>
                        ) : null}
                        {/* the newest approved version cannot read this table, so it stays with this one (review OWN-2 a) */}
                        {r.newer && (
                          <div className="muted fs-12" data-testid={`delivery-region-newer-${r.region_id}`}>Version {r.newer.version} does not read it:{" "}
                            {findingsInline(r.newer.findings, r.newer.constants)}.</div>
                        )}
                      </td>
                      <td className="num" data-label="Numbers">{r.numeric_cells ? `${r.used} read · ${r.excluded} not data · ${r.silent} not read` : ""}</td>
                      <td>
                        {readable(r) && (
                          <button type="button" className="link-btn" onClick={() => setReading(r)} aria-label={`Read ${tableName(r.where, file.name)}`}
                                  data-testid={`delivery-region-read-${r.region_id}`}>Read this table…</button>
                        )}
                        {r.state !== "excluded" && r.state !== "waiting" && aside !== r.region_id && (
                          <button type="button" className="link-btn" onClick={() => setAside(r.region_id)}
                                  aria-label={`Mark ${tableName(r.where, file.name, r.kind)} as not data`}
                                  data-testid={`delivery-region-aside-${r.region_id}`}>Not data…</button>
                        )}
                        {restorable(r) && restoring !== r.region_id && (
                          <button type="button" className="link-btn" onClick={() => setRestoring(r.region_id)}
                                  aria-label={`Restore ${tableName(r.where, file.name, r.kind)}`}
                                  data-testid={`delivery-region-restore-${r.region_id}`}>Restore…</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="muted m-0">No region was found in this file.</p>}
          {shown.regions.filter((r) => r.region_id === aside).map((r) => (
            <Why key={r.region_id} action="Mark as not data" actionLabel={`Mark ${tableName(r.where, file.name, r.kind)} as not data`}
                 label={`Why ${tableName(r.where, file.name, r.kind)} is not data`} busy={busy} onCancel={() => setAside(null)}
                 testId="delivery-region-aside" onSubmit={exclude([r.region_id], scopeOf(r))} autoFocus kind="not data"
                 suggestions={["a scratch table, not data", "a note, not data"]}>
              <span className="muted">{whereIs(r.where).place}: what was read from it is set aside too; &quot;Restore…&quot; gives it back.</span>
            </Why>
          ))}
          {shown.regions.filter((r) => r.region_id === restoring).map((r) => (
            <RestoreForm key={r.region_id} projectId={projectId} file={shown} items={[r.region_id]} scope={scopeOf(r)}
                         label={tableName(r.where, file.name, r.kind)} onDone={() => setRestoring(null)} testId="delivery-region-restore" />
          ))}
          {shown.outside.length > 0 && (
            <>
              <h4 className="delivery-sub">Loose numbers: text with a number outside every table</h4>
              <ul className="delivery-plain">
                {shown.outside.map((o, i) => (
                  <li key={o.where} className={o.counted ? "delivery-check open" : "delivery-check"}>
                    <div className="delivery-check-line">
                      <span className={`chip ${o.counted ? "high" : "neutral"}`} data-testid={`delivery-outside-state-${file.file_id}-${i}`}
                            title={!o.counted && !marked(o) ? "The table's layout reads this note: a fact stated once for the table" : undefined}>
                        {o.counted ? "not read" : marked(o) ? "not data" : "read with its table"}</span>
                      <span className="delivery-check-text">“{o.text ?? WITHHELD}” <span className="muted">{whereIs(o.where).place}</span></span>
                      {marked(o) && restoring !== o.where && (
                        <button type="button" className="link-btn" onClick={() => setRestoring(o.where)} aria-label={`Restore ${noteName(o)}`}
                                data-testid={`delivery-outside-restore-${file.file_id}-${i}`}>Restore…</button>
                      )}
                    </div>
                    <DecisionNote decision={o.decision} restored={o.restored} testId={`delivery-outside-decision-${file.file_id}-${i}`} />
                    {o.counted && <Why action="It is not data" actionLabel={`Mark ${noteName(o)} as not data`} label={`Why ${noteName(o)} is not data`}
                                       busy={busy} testId="delivery-file-outside-accept" onSubmit={exclude([o.where], "outside")} kind="not data"
                                       suggestions={["a column header, not a value", "a note, not data"]} />}
                    {marked(o) && restoring === o.where && (
                      <RestoreForm projectId={projectId} file={shown} items={[o.where]} scope="outside" label={noteName(o)}
                                   onDone={() => setRestoring(null)} testId="delivery-outside-restore-form" />
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          {file.run && file.run.stages.length > 0 && (
            <details className="delivery-tech">
              <summary>Technical details: how long each step of the reading took <span className="muted">reading {file.run.attempt}, {when(file.run.finished_at ?? file.run.started_at ?? file.run.queued_at)}</span></summary>
              <ul className="delivery-stages" data-testid={`delivery-stages-${file.file_id}`}>
                {file.run.stages.map((s) => (
                  <li key={s.stage} className={s.ok ? undefined : "failed"} title={engineWords(s.detail)}>
                    <strong>{stageText(s.stage)}</strong> {s.seconds < 0.01 ? "< 0.01" : s.seconds.toFixed(2)} s
                    <span className="muted"> {engineWords(s.detail)}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      {reading && <ReadTable projectId={projectId} file={shown} region={reading} onClose={() => setReading(null)}
                             onStored={(id) => { setReading(null); onMapping({ id, at: { file_sha256: shown.sha256, region_id: reading.region_id } }); }} />}
    </li>
  );
}

function Coverage({ page }: { page: Page }) {
  const t = page.totals;
  const states = Object.entries(t.files_by_state).map(([state, n]) => `${n} ${FILE_STATE[state]?.label ?? fieldText(state)}`).join(", ");
  const tiles: [string, number, string, string][] = [
    ["files", t.files, t.files === 1 ? "file" : "files", states],
    ["regions", t.regions, t.regions === 1 ? "table or text found" : "tables and texts found",
     `${t.regions_mapped} read, ${t.regions_excluded} not data, ${t.regions_unread} not read`],
    ["silent-loss", t.silent_loss, "numbers not read", "in tables, but no column picked them up"],
    ["outside", t.outside_numeric, "loose numbers", "in notes or text, outside any table"],
    ["unassigned", t.values_unassigned, "values not linked to a study", "say which study or product they belong to"],
    ["values", t.values, "values read", "what was read and is in use"],
  ];
  if (t.needs_ocr_pages) tiles.push(["ocr", t.needs_ocr_pages, "pages to read as images", "scanned pages no text was read from"]);
  if (t.anchors_unresolved) tiles.push(["anchors", t.anchors_unresolved, "places not found again", "a value whose place in its file no longer resolves"]);
  return (
    <dl className="delivery-tiles" data-testid="delivery-coverage">
      {tiles.map(([id, n, label, note]) => (
        <div key={id} className={n > 0 && ["silent-loss", "outside", "unassigned", "ocr", "anchors"].includes(id) ? "delivery-tile warn" : "delivery-tile"}>
          <dd data-testid={`delivery-total-${id}`}>{n}</dd>
          <dt>{label}<span className="muted">{note}</span></dt>
        </div>
      ))}
    </dl>
  );
}

// what a reading's end changes: the delivery and its cards, the sheet form's reading, the client's files, the inputs
const AFTER_READING = ["/api/v1/projects/{project_id}/delivery", "/api/v1/projects/{project_id}/client-review",
                       "/api/v1/projects/{project_id}/client-data", "/api/v1/projects/{project_id}/inputs",
                       "/api/v1/projects/{project_id}/reading-queue"];

/** What the delivery page says has been read: each file's latest run, by its id and state. A reading that ended since
 *  the page last looked changes it, whether or not an answer in between said a file was being read. */
export function readMark(page: Page): string {
  return page.deliveries.flatMap((d) => d.files).map((f) => `${f.sha256}:${f.run?.run_id ?? ""}:${f.run?.state ?? ""}`).sort().join("|");
}

/** A file read while Inputs is open brings values onto the cards: what the reading changes is read again when it ends
 *  (the cards and layouts, the sheet form, the client's files, the inputs; plan 2026-11-14 slice 4: not every read of
 *  the page). The page is read every 3 s while a file is being read, and not otherwise. A reading has ended when the
 *  page, no longer reading, names other runs than when the page was last brought up to date: followed by what was read,
 *  not by catching the moment the flag turned, so a reading that starts and ends between two reads (one a decision
 *  asked for, read back once) is followed too (final review round 4: To do kept a table's row the reading had cleared).
 *  The page itself is current then: the API reads the runs before what they write, so "not reading" holds what the
 *  last reading wrote. Used by the Inputs workspace, so it holds on every area. Answers the delivery as read, null until
 *  read. */
export function useDeliveryRefresh(projectId: string): Page | null {
  const read = useResource("/api/v1/projects/{project_id}/delivery", { project_id: projectId }, { poll: (d) => d.running, interval: 3000 });
  const client = useQueryClient();
  const page = read.data;
  const mark = page ? readMark(page) : null;
  const settled = useRef<string | null>(null);         // the runs named when the page was last brought up to date
  useEffect(() => {
    if (!page || mark === null) return;
    if (settled.current === null) settled.current = mark;               // the visit's first answer: read with the rest
    if (page.running || mark === settled.current) return;
    settled.current = mark;
    const own = pageKey(projectId);
    void client.invalidateQueries({ predicate: (q) => typeof q.queryKey[0] === "string" && q.queryHash !== hashKey(own)
                                                 && AFTER_READING.some((r) => (q.queryKey[0] as string).startsWith(r)) });
  }, [mark, page?.running]); // eslint-disable-line react-hooks/exhaustive-deps
  return page;
}

export function DeliverySection({ projectId, work, focus, onOpenGroup, onItem }: {
  projectId: string;
  /** the one list of work (lib/inputsWork.ts): each subject's one card, for its standing */
  work?: WorkModel;
  /** a subject's card a To do row or "Next" opened: the section unfolds (the cards themselves are in their areas since
   *  plan 2026-11-14 slice 3) */
  focus?: { subject: string; at: number } | null;
  /** open an area where the delivery's studies, products and compound are confirmed on their cards (`group` "": the area) */
  onOpenGroup?: (group: string, tab: Tab) => void;
  /** open where a work item is settled (the workspace's own, which drops the filters that would hide it) */
  onItem?: (item: WorkItem) => void;
}) {
  // the page as the workspace reads it (`useDeliveryRefresh` polls it while a file is read): no second poll here
  const read = useResource("/api/v1/projects/{project_id}/delivery", { project_id: projectId });
  const client = useQueryClient();
  const { decide, busy, problem } = useDecide();
  const [folded, setFolded] = useState(false);
  const page = read.data;
  const running = page?.running ?? false;
  useEffect(() => {
    if (focus) setFolded(false);
  }, [focus]);

  if (!page) return read.problem ? <section className="delivery"><Problem text={`The delivery review could not be read: ${read.problem}`} /></section> : null;
  if (!page.enabled) return null;

  const files = page.deliveries.flatMap((d) => d.files);
  const t = page.totals;
  // when each delivery arrived and who sent it: every one of them, the files read counted over all
  const arrived = page.deliveries.map((d) => `${whenText(d.at)} by ${d.by}`);
  const received = arrived.length === 1 ? `Received ${arrived[0]}` : arrived.length ? `Received in ${arrived.length} deliveries: ${arrived.join("; ")}` : "";
  const summary = files.length
    ? [received, `${count(t.files, "file")} read`,
       t.silent_loss ? `${count(t.silent_loss, "number")} not read` : "", t.outside_numeric ? count(t.outside_numeric, "loose number") : "",
       t.values_unassigned ? `${count(t.values_unassigned, "value")} not linked to a study` : ""].filter(Boolean).join(" · ")
    : "no client file has arrived yet";
  // where the delivery's studies, products and compound are confirmed: on their cards, by area
  const areas = [...new Set((work?.subjects ?? []).filter((u) => u.row).map((u) => u.area))];
  const waits = work ? work.items.some((i) => i.open && i.pipeline === "delivery" && i.area === "files")
    : page.mappings.length > 0 || page.unassigned.length > 0;
  // the first of that work in To do's order (unfolding "Blocks nothing" when it is there)
  const first = work?.items.find((i) => i.pipeline === "delivery" && /^(layout|link|alias|notread):/.test(i.id) && i.status !== "done" && !i.blocked);
  const cleanUp = [page.mappings.length ? count(page.mappings.length, "table layout") + " to check" : "",
                   page.unassigned.length ? count(page.unassigned.length, "value") + " to link" : "",
                   t.silent_loss || t.outside_numeric ? "numbers not read" : ""].filter(Boolean);
  async function readAll() {
    const { data } = await decide(() => send("post", RUN, { project_id: projectId }, { files: [] }), {});
    if (data !== null) readPage(client, projectId);
  }

  return (
    <section className={`delivery${waits ? " waits" : ""}`} data-testid="delivery-section">
      <div className="delivery-head">
        <strong>The delivery</strong>
        <span className="muted" data-testid="delivery-counts" role="status" aria-live="polite">{summary}</span>
        {running && <span className="chip neutral" data-testid="delivery-running">Reading…</span>}
        <span className="chip neutral" data-testid="delivery-rules"
              title={`The intake rules the files were read with (sha256 ${page.rules.sha256}); UNVERIFIED until an expert signs them`}>{rulesText(page.rules)}</span>
        {files.length > 0 && (
          <span className="delivery-head-actions">
            <button type="button" className="btn tiny" disabled={busy || running} data-testid="delivery-run" onClick={() => void readAll()}>Read again</button>
            <button type="button" className="link-btn" aria-expanded={!folded} onClick={() => setFolded(!folded)} data-testid="delivery-toggle">
              {folded ? "Show the review" : "Hide the review"}</button>
          </span>
        )}
      </div>
      <Problem text={problem} testId="delivery-problem" />
      {files.length > 0 && !folded && (
        <div className="delivery-body">
          <details className="delivery-details">
            <summary>Details: what was read from the files</summary>
            <Coverage page={page} />
          </details>
          {cleanUp.length > 0 && (
            <p className="muted fs-13 m-0" data-testid="delivery-in-todo">
              {cleanUp.join(" · ")}: settled in {first && onItem ? (
                <button type="button" className="link-btn" onClick={() => onItem(first)} data-testid="delivery-in-todo-open"
                        aria-label={`Open To do on the first of them: ${first.label}`}>To do</button>
              ) : <Link href="?tab=todo" prefetch={false}>To do</Link>}, together, a file or a layout at a time.</p>
          )}

          {/* each study, product and the compound is confirmed on its card in its area (plan 2026-11-14 slice 3): no
              second list of them here */}
          {page.subjects.length > 0 && (
            <p className="muted fs-13 m-0" data-testid="delivery-subjects">
              {[count(page.subjects.filter((s) => s.subject_type === "study").length, "study", "studies"),
                count(page.subjects.filter((s) => s.subject_type === "product").length, "product"),
                page.subjects.some((s) => s.subject_type === "compound") ? "the compound's values" : ""]
                .filter((w) => w && !w.startsWith("0 ")).join(", ")} read from these files: each is confirmed on its card in its area
              {areas.length ? ": " : "."}
              {areas.map((a, i) => (
                <span key={a}>{i > 0 && " · "}
                  {onOpenGroup ? <button type="button" className="link-btn" onClick={() => onOpenGroup("", a)} data-testid={`delivery-subjects-${a}`}>
                    {AREA_NAME[a]} ({(work?.subjects ?? []).filter((u) => u.row && u.area === a).length})</button>
                    : AREA_NAME[a]}
                </span>
              ))}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

// a file's own reading (its tables and texts, loose numbers, stage times, read again) opens under that file's row in the
// Client files table (components/inputs/ClientFilesTab.tsx): the only list of files on Inputs (plan 2026-11-14 slice 2)
export { FileItem };
