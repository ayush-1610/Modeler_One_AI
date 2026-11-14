"use client";

// The Client files area (plan 2026-11-14 slice 1): everything about the files themselves, in one place, after the input
// areas. The head adds files; under it the AI reading line (the reading tray), then one row per file (what it is, where
// its data land, what it gave) that opens on the file's sheets and their reading, then the Delivery review (unchanged
// inside until a later slice folds each file's delivery reading into its row). The files drawer and the per-area file
// lists it replaces are gone.

import Link from "next/link";
import { Fragment, useRef, useState } from "react";

import { type Act, ClientFiles, FileTagLine, type Retag, type SheetMemory } from "@/components/client/ClientFiles";
import type { ClientFile, View as ClientView } from "@/components/client/types";
import { DeliverySection } from "@/components/delivery/DeliverySection";
import type { DataTab } from "@/lib/fileTags";

import type { Run } from "./InputsTodo";
import { ReadingTray } from "./ReadingTray";
import { ACCEPT, AREA_FILES, AREA_LABEL, FILE_AREAS, addClientFiles, fileArea } from "./TabFiles";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** What a file gave this project, in words. */
function gave(f: ClientFile): string {
  const parts = [
    f.template ? "the client-data template, read cell by cell" : "",
    f.datasets?.length ? plural(f.datasets.length, "dataset") : "",
    f.evidence?.length ? plural(f.evidence.length, "value") : "",
    f.dissolution?.length || f.mappings?.some((m) => m.dissolution_records) ? "dissolution data" : "",
    f.triage?.length && !f.template ? `${plural(f.triage.length, "sheet")} sorted` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "stored; nothing read from it yet";
}

/** The files opened on their sheets and the last sheet form saved: kept by the workspace, so they hold while another
 *  area is shown. */
export type FilesShown = { open: ReadonlySet<string>; toggle: (id: string) => void; memory: SheetMemory };

/** One row per client file: what it is (changed here, which files it again), the area its data land on, what it gave. Its
 *  name opens the file's sheets and their reading under the row; the last sheet form saved is offered in every file. */
function FilesTable({ projectId, client, act, onRetag, onSaved, onOpen, shown: { open, toggle, memory } }: {
  projectId: string; client: ClientView; act: Act; onRetag: Retag; onSaved: (message: string) => Promise<void>;
  onOpen: (area: DataTab) => void; shown: FilesShown;
}) {
  return (
    <div className="table-scroll">
      <table className="files-table" data-testid="files-table">
        <caption className="sr-only">The client&apos;s files</caption>
        <thead><tr><th>File</th><th>What it is</th><th>Its data land on</th><th>What it gave</th></tr></thead>
        <tbody>
          {client.files.map((f) => {
            const area = fileArea(f);
            const shown = open.has(f.id);
            return (
              <Fragment key={f.id}>
                <tr data-testid={`inputs-file-${f.file}`} className={shown ? "open" : undefined}>
                  <td>
                    <button type="button" className="files-name" aria-expanded={shown} aria-controls={`file-detail-${f.id}`}
                            data-testid={`file-toggle-${f.file}`} onClick={() => toggle(f.id)}
                            title={shown ? "Hide its sheets and their reading" : "Show its sheets and their reading"}>
                      <span className="files-caret" aria-hidden="true">{shown ? "▾" : "▸"}</span>{f.file}
                    </button>
                  </td>
                  <td><FileTagLine file={f} onRetag={onRetag} /></td>
                  <td>{area ? (
                    <button type="button" className="link-btn" data-testid={`open-file-${f.file}`} onClick={() => onOpen(area)}
                            title={`Open ${AREA_LABEL[area]}, where the data of ${f.file} land`}>{AREA_LABEL[area]}</button>
                  ) : <span className="chip medium">not placed: say what it is</span>}</td>
                  <td className="muted">{gave(f)}</td>
                </tr>
                {shown && (
                  <tr className="files-detail" id={`file-detail-${f.id}`}>
                    <td colSpan={4}>
                      <ClientFiles projectId={projectId} view={client} files={[f]} act={act} onSaved={onSaved} memory={memory} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ClientFilesTab({ projectId, client, run, act, onRetag, onSaved, onOpen, shown }: {
  projectId: string; client: ClientView | null; run: Run; act: Act; onRetag: Retag; onSaved: (message: string) => Promise<void>;
  /** open an input area (where a file's data land) */
  onOpen: (area: DataTab) => void;
  shown: FilesShown;
}) {
  const [area, setArea] = useState<DataTab>("studies");
  const input = useRef<HTMLInputElement>(null);
  const files = client?.files ?? [];
  return (
    <>
      <div className="files-head">
        <h2 className="m-0">Client files <span className="muted">({files.length})</span></h2>
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
      <ReadingTray projectId={projectId} />
      {!client || files.length === 0 ? <p className="muted" data-testid="files-none">No client file yet: add them with Add data at
        the top of the page, or with Add files here.</p> : (
        <>
          <FilesTable projectId={projectId} client={client} act={act} onRetag={onRetag} onSaved={onSaved} onOpen={onOpen} shown={shown} />
          <p className="muted fs-13 m-6-0-0" data-testid="files-reading-note">
            A file&apos;s name opens its sheets. The reading agent proposes how to read each data sheet, and code checks every
            proposal: each quote is in its cell and the reading applies without a problem. Open a sheet, check what it reads
            against the sheet, correct anything wrong and save.{!client.agents.enabled && " Agents are off: the form is filled in first by code."}
          </p>
        </>
      )}
      <DeliverySection projectId={projectId} />
    </>
  );
}
