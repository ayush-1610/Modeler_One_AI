"use client";

// The Client files area (plan 2026-11-14 slices 1–2): everything about the files themselves, in one place, after the input
// areas. The head adds files; under it the AI reading line, then the one table of files: one row and one status per file
// (what it is, where its data land, how far it was read, what it still needs from you, counted from the one list of work).
// A row opens on everything about that file: the delivery's reading of it (its tables and texts, loose numbers, stage
// times, "Read again"), its AI reading, and its sheets with their reading form. Then the delivery itself (its layouts to
// check, the values to link, its studies and products). No other list of files is kept on Inputs (plan §2, rule 4).

import Link from "next/link";
import { Fragment, useRef, useState } from "react";

import { type Act, ClientFiles, FileTagLine, type Retag, type SheetMemory } from "@/components/client/ClientFiles";
import type { ClientFile, View as ClientView } from "@/components/client/types";
import { DeliverySection, FileItem } from "@/components/delivery/DeliverySection";
import { MappingReview } from "@/components/delivery/MappingReview";
import { Problem, useDecide, type FileRow } from "@/components/delivery/shared";
import type { Schema } from "@/lib/api";
import type { DataTab } from "@/lib/fileTags";
import { useResource } from "@/lib/hooks";
import { areaHead, type WorkItem, type WorkModel } from "@/lib/inputsWork";
import { type Tab, plural } from "@/lib/words";

import type { Run } from "./InputsTodo";
import { AiReading, ReadingTray } from "./ReadingTray";
import { ACCEPT, AREA_FILES, AREA_LABEL, FILE_AREAS, addClientFiles, fileArea } from "./TabFiles";

type ReadingItem = Schema<"ReadingItem">;

/** What a file gave this project, in words. */
function gave(f: ClientFile): string {
  const parts = [
    f.template ? "the client-data template, read cell by cell" : "",
    f.datasets?.length ? plural(f.datasets.length, "dataset") : "",
    f.evidence?.length ? plural(f.evidence.length, "value") : "",
    f.dissolution?.length || f.mappings?.some((m) => m.dissolution_records) ? "dissolution data" : "",
    f.triage?.length && !f.template ? `${plural(f.triage.length, "sheet")} sorted` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "";
}

/** A file's one status (design "File status"): the delivery's reading first (partly read while a table or text of it was
 *  not read), then the AI reading while AI is on, then the sheet form's. Never "waiting" beside "read". */
export function readState(delivery: FileRow | undefined, ai: ReadingItem | undefined, aiOn: boolean,
                          file: ClientFile | undefined): { text: string; tone: string } {
  if (delivery) {
    const s = delivery.state;
    if (s === "read" || s === "partly_read") {
      return delivery.coverage?.regions_unread || s === "partly_read" ? { text: "partly read", tone: "neutral" } : { text: "read", tone: "low" };
    }
    if (s === "waiting") return { text: "Reading…", tone: "neutral" };
    if (s === "unsupported") return { text: "not a kind the reader takes", tone: "neutral" };
    if (s === "failed" || s === "unreadable") return { text: "could not be read", tone: "high" };
    return { text: "not read", tone: "neutral" };
  }
  if (ai && aiOn) {
    return ai.state === "done" ? { text: "read by AI", tone: "low" } : ai.state === "failed" ? { text: "AI reading failed", tone: "high" }
      : { text: ai.state === "reading" ? "Reading…" : "waiting for AI", tone: "neutral" };
  }
  if (file && (file.mappings?.length || file.datasets?.length || file.evidence?.length || file.template)) return { text: "read", tone: "low" };
  if (ai) return { text: "waiting for AI · AI reading is off", tone: "neutral" };
  return { text: "stored, not read yet", tone: "neutral" };
}

/** What a file still needs from you, in words: one entry per kind of work, each opening where it is settled. */
function needs(items: WorkItem[]): { item: WorkItem; text: string }[] {
  const out: { item: WorkItem; text: string }[] = [];
  const layouts = items.filter((i) => i.id.startsWith("layout:"));
  if (layouts.length) out.push({ item: layouts[0], text: `${plural(layouts.length, "table layout")} to check` });
  for (const i of items.filter((x) => x.id.startsWith("link:"))) out.push({ item: i, text: `${plural(i.weight, "value")} to link` });
  for (const i of items.filter((x) => x.id.startsWith("alias:"))) out.push({ item: i, text: i.label.split("?")[0] + "?" });
  for (const i of items.filter((x) => x.id.startsWith("notread:"))) out.push({ item: i, text: i.label.slice(i.label.indexOf(": ") + 2) });
  const drafts = items.filter((i) => i.id.startsWith("draft:"));
  if (drafts.length) out.push({ item: drafts[0], text: `${plural(drafts.length, "sheet")} with facts to fill in` });
  return out;
}

/** The files opened on their sheets and the last sheet form saved: kept by the workspace, so they hold while another
 *  area is shown. */
export type FilesShown = { open: ReadonlySet<string>; toggle: (id: string) => void; memory: SheetMemory };

type Row = { id: string; name: string; sha: string; file: ClientFile | undefined; delivery: FileRow[] };

/** One row per client file (and per delivered file no client file stands for): what it is (changed here, which files it
 *  again), the area its data land on, its one status and what it still needs from you. Its name opens everything about
 *  the file under the row. */
function FilesTable({ projectId, client, rows, work, ai, aiOn, act, onRetag, onSaved, onOpen, onItem, shown: { open, toggle, memory } }: {
  projectId: string; client: ClientView | null; rows: Row[]; work: WorkModel; ai: Map<string, ReadingItem>; aiOn: boolean;
  act: Act; onRetag: Retag; onSaved: (message: string) => Promise<void>;
  onOpen: (area: DataTab) => void; onItem: (item: WorkItem) => void; shown: FilesShown;
}) {
  const { decide, busy, problem } = useDecide();
  const [mapping, setMapping] = useState<string | null>(null);
  const firsts = new Map<string, FileRow>();
  for (const r of rows) for (const d of r.delivery) if (!d.repeat && !firsts.has(d.sha256)) firsts.set(d.sha256, d);
  return (
    <>
      <Problem text={problem} testId="files-problem" />
      <div className="table-scroll">
        <table className="files-table" data-testid="files-table">
          <caption className="sr-only">The client&apos;s files</caption>
          <thead><tr><th>File</th><th>What it is</th><th>Its data land on</th><th>Read</th><th>Still needs you</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const f = r.file;
              const area = f ? fileArea(f) : null;
              const isOpen = open.has(r.id);
              const state = readState(r.delivery[0], ai.get(r.id), aiOn, f);
              const todo = needs(work.byFile[r.id] ?? []);
              const gives = f ? gave(f) : "";
              return (
                <Fragment key={r.id}>
                  <tr data-testid={`inputs-file-${r.name}`} className={isOpen ? "open" : undefined}>
                    <td>
                      <button type="button" className="files-name" aria-expanded={isOpen} aria-controls={`file-detail-${r.id}`}
                              data-testid={`file-toggle-${r.name}`} onClick={() => toggle(r.id)}
                              title={isOpen ? "Hide its reading" : "Show its tables, sheets and their reading"}>
                        <span className="files-caret" aria-hidden="true">{isOpen ? "▾" : "▸"}</span>{r.name}
                      </button>
                      {gives && <div className="muted fs-12">{gives}</div>}
                    </td>
                    <td>{f ? <FileTagLine file={f} onRetag={onRetag} /> : <span className="muted">in the delivery only</span>}</td>
                    <td>{area ? (
                      <button type="button" className="link-btn" data-testid={`open-file-${r.name}`} onClick={() => onOpen(area)}
                              title={`Open ${AREA_LABEL[area]}, where the data of ${r.name} land`}>{AREA_LABEL[area]}</button>
                    ) : f ? <span className="chip medium">not placed: say what it is</span> : <span className="muted">—</span>}</td>
                    <td><span className={`chip ${state.tone}`} data-testid={`file-state-${r.name}`}>{state.text}</span></td>
                    <td data-testid={`file-needs-${r.name}`}>
                      {todo.length ? (
                        <ul className="file-needs">
                          {todo.map((n) => (
                            <li key={n.item.id}>
                              <button type="button" className="link-btn" onClick={() => onItem(n.item)}
                                      aria-label={`${n.text}: ${n.item.label}`}>{n.text}</button>
                            </li>
                          ))}
                        </ul>
                      ) : <span className="muted">nothing</span>}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="files-detail" id={`file-detail-${r.id}`}>
                      <td colSpan={5}>
                        {r.delivery.length > 0 && (
                          <ul className="delivery-plain file-delivery" aria-label={`How the delivery read ${r.name}`}>
                            {r.delivery.map((d) => <FileItem key={d.file_id} projectId={projectId} file={d} first={firsts.get(d.sha256)}
                                                             decide={decide} busy={busy} onMapping={setMapping} />)}
                          </ul>
                        )}
                        {f && <AiReading projectId={projectId} sid={f.id} />}
                        {f && client && <ClientFiles projectId={projectId} view={client} files={[f]} act={act} onSaved={onSaved} memory={memory} />}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {mapping && <MappingReview projectId={projectId} mappingId={mapping} onClose={() => setMapping(null)} />}
    </>
  );
}

export function ClientFilesTab({ projectId, client, work, only, onOnly, run, act, onRetag, onSaved, onOpen, onItem, onOpenGroup, focus, shown }: {
  projectId: string; client: ClientView | null; work: WorkModel;
  /** "Only what needs me": the files with something open */
  only: boolean; onOnly: (on: boolean) => void;
  run: Run; act: Act; onRetag: Retag; onSaved: (message: string) => Promise<void>;
  /** open an input area (where a file's data land) */
  onOpen: (area: DataTab) => void;
  /** open where a file's open item is settled */
  onItem: (item: WorkItem) => void;
  onOpenGroup: (group: string, tab: Tab) => void;
  /** a delivery subject's card to open (a To do row, "Next") */
  focus: { subject: string; at: number } | null;
  shown: FilesShown;
}) {
  const [area, setArea] = useState<DataTab>("studies");
  const input = useRef<HTMLInputElement>(null);
  const delivery = useResource("/api/v1/projects/{project_id}/delivery", { project_id: projectId }).data;
  const queue = useResource("/api/v1/projects/{project_id}/reading-queue", { project_id: projectId }).data;
  const files = client?.files ?? [];
  // one row per client file, with the delivery's reading of the same bytes; a delivered file no client file stands for
  // (a member of an archive) gets its own row
  const delivered = delivery?.enabled ? delivery.deliveries.flatMap((d) => d.files) : [];
  const rows: Row[] = files.map((f) => ({ id: f.id, name: f.file, sha: f.sha256, file: f,
                                          delivery: delivered.filter((d) => d.sha256 === f.sha256 || d.legacy_sid === f.id) }));
  for (const d of delivered) {
    if (rows.some((r) => r.delivery.includes(d))) continue;
    const known = rows.find((r) => r.id === `sha:${d.sha256}`);
    if (known) known.delivery.push(d);
    else rows.push({ id: `sha:${d.sha256}`, name: d.name, sha: d.sha256, file: undefined, delivery: [d] });
  }
  const ai = new Map((queue?.items ?? []).map((i) => [i.sid, i] as const));
  const shownRows = only ? rows.filter((r) => (work.byFile[r.id] ?? []).length > 0) : rows;
  const readByCode = new Set(delivered.filter((d) => d.state === "read" || d.state === "partly_read").map((d) => d.sha256)).size;
  return (
    <>
      <div className="files-head">
        <h2 className="m-0">Client files <span className="muted">({rows.length})</span></h2>
        <span className="row gap-6">
          <span className="muted">Files for</span>
          <select value={area} onChange={(e) => setArea(e.target.value as DataTab)} aria-label="the area the files are for"
                  data-testid="client-upload-area">
            {FILE_AREAS.map((a) => <option key={a} value={a}>{AREA_LABEL[a]}</option>)}
          </select>
          <button type="button" className="btn" onClick={() => input.current?.click()}>Add files</button>
          <input ref={input} type="file" multiple hidden accept={ACCEPT} data-testid="client-upload-files"
                 aria-label={`Add the client's ${AREA_FILES[area]}`}
                 onChange={(e) => { void addClientFiles(projectId, run, e.target.files, area); e.target.value = ""; }} />
        </span>
        <Link href={`/projects/${encodeURIComponent(projectId)}/library`}>The files in the Document Library</Link>
      </div>
      <div className="area-head-row">
        <p className="area-head" data-testid="area-head-files">{areaHead(work, "files", rows.length)}</p>
        {rows.length > 0 && (
          <label className="only-mine">
            <input type="checkbox" checked={only} onChange={(e) => onOnly(e.target.checked)} data-testid="files-only" />
            Only what needs me
          </label>
        )}
      </div>
      <ReadingTray projectId={projectId} readWithoutAi={readByCode} />
      {rows.length === 0 ? <p className="muted" data-testid="files-none">No client file yet: add them with Add data at
        the top of the page, or with Add files here.</p> : (
        <>
          {shownRows.length === 0 ? <p className="muted" data-testid="files-nothing">Nothing in the files needs you now.</p> : (
            <FilesTable projectId={projectId} client={client} rows={shownRows} work={work} ai={ai} aiOn={Boolean(queue?.agents.enabled)}
                        act={act} onRetag={onRetag} onSaved={onSaved} onOpen={onOpen} onItem={onItem} shown={shown} />
          )}
          <p className="muted fs-13 m-6-0-0" data-testid="files-reading-note">
            A file&apos;s name opens everything about it: how its tables were read, and its sheets. Open a sheet to check how it
            was read, fix anything wrong and save.{client && !client.agents.enabled && " AI reading is off: the form is filled in first by code."}
          </p>
        </>
      )}
      <DeliverySection projectId={projectId} subjects={work.subjects} focus={focus} onOpenGroup={onOpenGroup} />
    </>
  );
}
