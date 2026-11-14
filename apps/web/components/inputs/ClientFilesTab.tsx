"use client";

// The Client files area (plan 2026-11-14 slice 1): everything about the files themselves, in one place, after the input
// areas. The head adds files; under it the AI reading line (the reading tray), one row per file (what it is, the area it
// is filed under, what it gave), the Delivery review (unchanged inside) and, by area, each file's sheets with their
// reading. The files drawer and the per-area file lists it replaces are gone.

import Link from "next/link";
import { useRef, useState } from "react";

import { type Act, FileTagLine, type Retag } from "@/components/client/ClientFiles";
import type { ClientFile, View as ClientView } from "@/components/client/types";
import { DeliverySection } from "@/components/delivery/DeliverySection";
import type { DataTab } from "@/lib/fileTags";

import type { Run } from "./InputsTodo";
import { ReadingTray } from "./ReadingTray";
import { ACCEPT, AREA_FILES, AREA_LABEL, FILE_AREAS, FileGroup, addClientFiles, fileArea } from "./TabFiles";

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

/** One row per client file: what it is (changed here, which files it again), the area it is filed under, what it gave. */
function FilesTable({ files, onRetag, onOpen }: { files: ClientFile[]; onRetag: Retag; onOpen: (area: DataTab) => void }) {
  return (
    <div className="table-scroll">
      <table className="files-table" data-testid="files-table">
        <caption className="sr-only">The client&apos;s files</caption>
        <thead><tr><th>File</th><th>What it is</th><th>Filed under</th><th>What it gave</th></tr></thead>
        <tbody>
          {files.map((f) => {
            const area = fileArea(f);
            return (
              <tr key={f.id} data-testid={`inputs-file-${f.file}`}>
                <td><a className="files-name" href={`#client-file-${f.id}`} title="Show its sheets and their reading">{f.file}</a></td>
                <td><FileTagLine file={f} onRetag={onRetag} /></td>
                <td>{area ? (
                  <button type="button" className="link-btn" data-testid={`open-file-${f.file}`} onClick={() => onOpen(area)}
                          title={`Its data land on ${AREA_LABEL[area]}`}>Open on {AREA_LABEL[area]}</button>
                ) : <span className="chip medium">not placed: say what it is</span>}</td>
                <td className="muted">{gave(f)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ClientFilesTab({ projectId, client, run, act, onRetag, onSaved, onOpen }: {
  projectId: string; client: ClientView | null; run: Run; act: Act; onRetag: Retag; onSaved: (message: string) => Promise<void>;
  /** open an input area (where a file's data land) */
  onOpen: (area: DataTab) => void;
}) {
  const [area, setArea] = useState<DataTab>("studies");
  const input = useRef<HTMLInputElement>(null);
  const files = client?.files ?? [];
  const unplaced = files.filter((f) => !fileArea(f));
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
          <button type="button" className="btn primary" onClick={() => input.current?.click()}>Add files</button>
          <input ref={input} type="file" multiple hidden accept={ACCEPT} data-testid="client-upload-files"
                 aria-label={`Add the client's ${AREA_FILES[area]}`}
                 onChange={(e) => { void addClientFiles(projectId, run, e.target.files, area); e.target.value = ""; }} />
        </span>
        <Link href={`/projects/${encodeURIComponent(projectId)}/library`}>The files in the Document Library</Link>
      </div>
      <ReadingTray projectId={projectId} />
      {files.length === 0 ? <p className="muted" data-testid="files-none">No client file yet: add them with Add data at the top
        of the page, or with Add files here.</p> : <FilesTable files={files} onRetag={onRetag} onOpen={onOpen} />}
      <DeliverySection projectId={projectId} />
      {client && files.length > 0 && (
        <>
          {FILE_AREAS.map((a) => (
            <FileGroup key={a} id={a} title={`${AREA_LABEL[a]}: the client's ${AREA_FILES[a]}`} projectId={projectId} client={client}
                       files={files.filter((f) => fileArea(f) === a)} act={act} onSaved={onSaved}>
              {a === "studies" && (
                <p className="muted fs-13 m-0-0-8">
                  The reading agent proposes how to read each data sheet, and code checks every proposal: each quote is in its cell and
                  the reading applies without a problem. Open a sheet, check what it reads against the sheet, correct anything wrong
                  and save.{!client.agents.enabled && " Agents are off: the form is filled in first by code."}
                </p>
              )}
            </FileGroup>
          ))}
          <FileGroup id="unplaced" title="Not placed yet: say what each is, on its row above" projectId={projectId} client={client}
                     files={unplaced} act={act} onSaved={onSaved} />
        </>
      )}
    </>
  );
}
