"use client";

// The Delivery section on Inputs (contracts 2026-11-12 §8.10): what arrived from the client, read by code and reviewed
// by exception. On Inputs it sits in the Client files area (plan 2026-11-14 slice 1), under the one table of files
// (slice 2: each file's own reading, `FileItem`, opens under that file's row there, so no second list of files is kept
// here): when the files arrived and what of them was read (the totals behind "Details"), the table layouts that wait for
// a person and the values no file links to a study. Each study, product and the compound is confirmed on its card in its
// area (plan 2026-11-14 slice 3, components/inputs/cards): one line here says where. What to ask
// the client is in To do. The section is not shown while the pipeline is off (`enabled` false); it reads again every
// few seconds while a file is being read.

import { useEffect, useRef, useState } from "react";

import { send } from "@/lib/api";
import { useRefresh, useResource } from "@/lib/hooks";
import { layoutAnchor, type WorkItem, type WorkModel } from "@/lib/inputsWork";
import {
  AREA_NAME, type Tab, engineWords, whereIs, layoutOrigin, placeText, plural as count, rulesText, stageText, tableKindText, whenText,
} from "@/lib/words";

import { MappingReview } from "./MappingReview";
import { ReadTable, readable } from "./ReadTable";
import { NotDataNote, RestoreForm, restorable, useDecisionsWho } from "./Restore";
import {
  ChipFor, FILE_STATE, KIND_LABEL, MAPPING_STATE, Problem, REGION_STATE, WITHHELD, Why, fieldText, levelText, plural, tableName,
  useDecide, when, type FileRow, type Page, type Region, type SubjectRow,
} from "./shared";
import { Unassigned } from "./Unassigned";

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
  first: FileRow | undefined; decide: Decide; busy: boolean; onMapping: (id: string) => void;
  /** under the file's row in the table of files, which says its name and its one status (plan 2026-11-14 §2 rule 4) */
  inRow?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [aside, setAside] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<string | null>(null);   // a region's id, or a note's place
  const [reading, setReading] = useState<Region | null>(null);       // a table given its first layout
  const shown = file.repeat && first ? first : file;
  const who = useDecisionsWho(projectId, open && shown.regions.some(restorable));
  // a note stops counting when a table that is read cites it (a fact read once for the table), or by a person's "not
  // data": beside no table, or beside one no layout reads, only a person's decision explains it, which can be restored.
  // Beside a table that is read the page cannot tell which (an API follow-up: who marked a note and why).
  const regionState = new Map(shown.regions.map((r) => [r.region_id, r.state]));
  const read = (o: FileRow["outside"][number]) => o.region !== null && ["mapped", "waiting"].includes(regionState.get(o.region) ?? "");
  const marked = (o: FileRow["outside"][number]) => !o.counted && !read(o);
  const noteName = (o: FileRow["outside"][number]) => (o.text ? `the note “${o.text}” of ${file.name}` : `the note at ${whereIs(o.where).place} of ${file.name}`);
  const exclude = (regions: string[], scope: "regions" | "unread_prose" | "figures" | "outside") => async (why: string) => {
    const { data } = await decide(() => send("post", EXCLUDE, { project_id: projectId }, { file_sha256: file.sha256, regions, scope, why }));
    if (data) setAside(null);
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
                onClick={() => void decide(() => send("post", RUN, { project_id: projectId }, { files: [file.sha256] }))}>Read again</button>
      </div>
      {file.reason && <p className="delivery-file-why" data-testid={`delivery-file-reason-${file.file_id}`}>{file.reason}</p>}
      {file.coverage && <p className="muted fs-13 m-0" data-testid={`delivery-file-coverage-${file.file_id}`}>{coverageLine(file)}</p>}
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
                      <td>{whereIs(r.where).place}</td>
                      <td>{fieldText(r.kind)}{r.table_kind && r.table_kind !== "unknown" ? `, ${fieldText(r.table_kind)}` : ""}
                        <div className="muted fs-12">{r.caption === null ? WITHHELD : r.caption}</div></td>
                      <td><ChipFor state={r.state} table={REGION_STATE} />
                        {restorable(r) ? <NotDataNote region={r} who={who} testId={`delivery-region-decision-${r.region_id}`} />
                          : r.reason && <div className="muted fs-12" title={r.reason} data-testid={`delivery-region-reason-${r.region_id}`}>{reasonWords(r)}</div>}</td>
                      <td>
                        {r.mapping_id ? (
                          <button type="button" className="delivery-chip-btn" onClick={() => onMapping(r.mapping_id as string)}
                                  data-testid={`delivery-region-mapping-${r.region_id}`} title="Review how this table is read">
                            <ChipFor state={r.mapping_status} table={MAPPING_STATE} /> version {r.mapping_version}{r.origin ? ` · ${layoutOrigin(r.origin)}` : ""}
                          </button>
                        ) : null}
                      </td>
                      <td className="num">{r.numeric_cells ? `${r.used} read · ${r.excluded} not data · ${r.silent} not read` : ""}</td>
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
                 testId="delivery-region-aside" onSubmit={exclude([r.region_id], scopeOf(r))} autoFocus>
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
                      <span className={`chip ${o.counted ? "high" : "neutral"}`}>{o.counted ? "not read" : marked(o) ? "not data" : "accounted for"}</span>
                      <span className="delivery-check-text">“{o.text ?? WITHHELD}” <span className="muted">{whereIs(o.where).place}
                        {!o.counted && read(o) && <span title="Its table's layout reads this note, or a person marked it as not data: the page does not say which">
                          {" "}· beside a table that is read</span>}</span></span>
                      {marked(o) && restoring !== o.where && (
                        <button type="button" className="link-btn" onClick={() => setRestoring(o.where)} aria-label={`Restore ${noteName(o)}`}
                                data-testid={`delivery-outside-restore-${file.file_id}-${i}`}>Restore…</button>
                      )}
                    </div>
                    {o.counted && <Why action="It is not data" actionLabel={`Mark ${noteName(o)} as not data`} label={`Why ${noteName(o)} is not data`}
                                       busy={busy} testId="delivery-file-outside-accept" onSubmit={exclude([o.where], "outside")} />}
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
                             onStored={(id) => { setReading(null); onMapping(id); }} />}
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

/** A file read while Inputs is open brings values onto the cards: every resource is read again when the reading ends.
 *  Used by the Inputs workspace, so it holds on every area, not only while the Client files area shows this section
 *  (plan 2026-11-14 slice 1). Answers the delivery as read (the status line counts its open work), null until read. */
export function useDeliveryRefresh(projectId: string): Page | null {
  const read = useResource("/api/v1/projects/{project_id}/delivery", { project_id: projectId }, { poll: (d) => d.running, interval: 3000 });
  const refresh = useRefresh();
  const was = useRef(false);
  const running = read.data?.running ?? false;
  useEffect(() => {
    if (running) was.current = true;
    else if (was.current) { was.current = false; void refresh(); }
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps
  return read.data;
}

export function DeliverySection({ projectId, work, focus, onOpenGroup }: {
  projectId: string;
  /** the one list of work (lib/inputsWork.ts): each subject's one card, for its standing, and whether each table layout
   *  holds up a signature now (amber only then, plan 2026-11-14 §2 rule 5) */
  work?: WorkModel;
  /** a subject's card a To do row or "Next" opened: the section unfolds (the cards themselves are in their areas since
   *  plan 2026-11-14 slice 3) */
  focus?: { subject: string; at: number } | null;
  /** open an area where the delivery's studies, products and compound are confirmed on their cards (`group` "": the area) */
  onOpenGroup?: (group: string, tab: Tab) => void;
}) {
  const read = useResource("/api/v1/projects/{project_id}/delivery", { project_id: projectId }, { poll: (d) => d.running, interval: 3000 });
  const { decide, busy, problem } = useDecide();
  const [folded, setFolded] = useState(false);
  const [mapping, setMapping] = useState<string | null>(null);
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
  // each layout's item in the one list: open (amber, To decide), or not counted now and why (neutral)
  const layoutItem = (m: Page["mappings"][number]): WorkItem | undefined =>
    work?.items.find((i) => i.id === `layout:${m.mapping_id}@${m.version}`);
  const layoutsOpen = page.mappings.filter((m) => layoutItem(m)?.open).length;
  // the one reason every layout not counted gives, said once in the list's lede instead of on each
  const reasons = [...new Set(page.mappings.map((m) => layoutItem(m)).filter((i) => i && !i.open && i.why).map((i) => i!.why!))];
  const oneReason = !layoutsOpen && reasons.length === 1 ? reasons[0] : null;
  const waits = work ? work.items.some((i) => i.open && i.pipeline === "delivery" && i.area === "files")
    : page.mappings.length > 0 || page.unassigned.length > 0;

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
            <button type="button" className="btn tiny" disabled={busy || running} data-testid="delivery-run"
                    onClick={() => void decide(() => send("post", RUN, { project_id: projectId }, { files: [] }))}>Read again</button>
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

          {page.mappings.length > 0 && (
            <section className="delivery-block" data-testid="delivery-mappings">
              <div className="delivery-block-head"><h3>Table layouts to check <span className="muted">({page.mappings.length})</span></h3></div>
              <p className="muted fs-13 m-0">A table&apos;s layout decides which of its numbers become values.{" "}
                {!work || layoutsOpen ? "Until a person approves it, they can't be confirmed with a signature."
                  : oneReason ? `None of these holds up a signature now. ${oneReason} Check them for the delivery record.`
                    : "None of these holds up a signature now (each says why): check them for the delivery record."}</p>
              <ul className="delivery-plain">
                {page.mappings.map((m) => {
                  const item = layoutItem(m);
                  const quiet = item && !item.open && !m.waiting;
                  return (
                  <li key={`${m.mapping_id}-${m.version}`} className={quiet ? "delivery-check" : "delivery-check open"} data-testid={layoutAnchor(m, page.mappings)}>
                    <div className="delivery-check-line">
                      {item?.open ? <span className="chip medium">To decide</span>
                        : quiet ? <span className="chip neutral">{item.group === "tidy" ? "blocks nothing" : "holds up nothing yet"}</span>
                          : <ChipFor state={m.status} table={MAPPING_STATE} />}
                      <span className="delivery-check-text">{tableKindText(m.kind)} · {m.used_in.map((u) => `${u.file}, ${placeText(u.where)}`).join("; ") || "no file uses it now"}
                        <span className="muted"> · {layoutOrigin(m.origin)} · version {m.version}</span></span>
                      {m.waiting && <span className="chip neutral">Reading…</span>}
                      <button type="button" className="btn tiny" onClick={() => setMapping(m.mapping_id)}
                              data-testid={layoutAnchor(m, page.mappings).replace("delivery-mapping-", "delivery-mapping-open-")}
                              aria-label={`Check the layout of the ${tableKindText(m.kind)} in ${m.used_in[0]?.file ?? "no file"}, version ${m.version}`}>Check layout</button>
                    </div>
                    {quiet && item.why && !oneReason && <p className="muted fs-12 m-0">{item.why}</p>}
                  </li>
                  );
                })}
              </ul>
            </section>
          )}

          <Unassigned projectId={projectId} page={page} />

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
      {mapping && <MappingReview projectId={projectId} mappingId={mapping} onClose={() => setMapping(null)} />}
    </section>
  );
}

// a file's own reading (its tables and texts, loose numbers, stage times, read again) opens under that file's row in the
// Client files table (components/inputs/ClientFilesTab.tsx): the only list of files on Inputs (plan 2026-11-14 slice 2)
export { FileItem };
