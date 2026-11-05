"use client";

// The client's files where their data belong (plan 2026-11-05 §3.1, the owner's answer of 2026-11-05): each file is
// shown on the area of Inputs its tag names (Clinical studies, Products and dissolution, Compound), and each area has
// its own "Add files". A file's tag is changed on its card or in the files view, and the file moves with it.

import type { ReactNode } from "react";

import { type Act, ClientFiles, type Retag } from "@/components/client/ClientFiles";
import type { ClientFile, View as ClientView } from "@/components/client/types";
import { upload } from "@/lib/api";
import { type DataTab, TAG_TAB, type TagKind, guessStudy, tagFor, tagsField } from "@/lib/fileTags";

import type { Run } from "./InputsTodo";

export const AREA_LABEL: Record<DataTab, string> = {
  compound: "Compound", formulations: "Products and dissolution", studies: "Clinical studies",
};
const AREA_FILES: Record<DataTab, string> = {
  compound: "in vitro and physico-chemistry files", formulations: "formulation and dissolution files",
  studies: "clinical and bioanalytical files",
};
const ACCEPT = ".xlsx,.xlsm,.xls,.csv,.pdf,.docx,.md,.txt";
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The area a client file is shown in, by its tag; a file tagged "other" whose content code reads as another kind is
 *  shown where that reading puts it, with the reading on its card to use or keep (kept "other", it is listed in the
 *  files view only). A file with no tag (a store that keeps no library record) stays on Clinical studies, as before. */
export function fileArea(file: ClientFile): DataTab | null {
  if (!file.tag) return "studies";
  const reading = file.tag_proposal?.decided === "open" ? file.tag_proposal.kind : null;
  return TAG_TAB[file.tag.kind === "other" && reading ? reading : file.tag.kind];
}

export function whereShown(kind: TagKind): string {
  const area = TAG_TAB[kind];
  return area ? `shown on ${AREA_LABEL[area]}` : "listed in the client's files only, until you say what it is";
}

/** The top of an area: its "Add files" (the area's tag unless the name says otherwise) and how many files it shows. */
export function FilesBar({ tab, projectId, client, run }: {
  tab: DataTab; projectId: string; client: ClientView | undefined; run: Run;
}) {
  const here = (client?.files ?? []).filter((f) => fileArea(f) === tab).length;
  async function add(list: FileList | null) {
    if (!list?.length) return;
    const files = Array.from(list);
    const tagged = files.map((file) => ({ file, tag: tagFor(file.name, tab), study: guessStudy(file.name) }));
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    form.set("tags", tagsField(tagged));
    const elsewhere = tagged.filter((t) => TAG_TAB[t.tag] !== tab).map((t) => `${t.file.name} is ${whereShown(t.tag)}, by its name`);
    await run(() => upload("/api/v1/projects/{project_id}/client-data", { project_id: projectId }, form),
              `${plural(files.length, "file")} stored.${elsewhere.length ? ` ${elsewhere.join("; ")}.` : ""}`
              + " Each file shows what it holds; open each data sheet, check its reading and save it.");
  }
  return (
    <div className="files-bar" data-testid={`files-bar-${tab}`}>
      <label className="btn primary">
        Add files
        <input type="file" multiple hidden data-testid={`client-upload-${tab}`} accept={ACCEPT}
               onChange={(e) => { void add(e.target.files); e.target.value = ""; }} />
      </label>
      <span className="muted">
        {here ? <a href={`#${tab}-client-files`}>{plural(here, "client file")} here</a> : `No client file here yet: add the ${AREA_FILES[tab]}.`}
      </span>
    </div>
  );
}

/** The files shown on an area, each with what it holds, its reading and what it is. */
export function FilesHere({ tab, projectId, client, act, onRetag, onSaved, children }: {
  tab: DataTab; projectId: string; client: ClientView | undefined; act: Act; onRetag: Retag;
  onSaved: (message: string) => Promise<void>; children?: ReactNode;
}) {
  const files = (client?.files ?? []).filter((f) => fileArea(f) === tab);
  if (!client || files.length === 0) return null;
  return (
    <section className="client-files" data-testid={`${tab}-client-files`} id={`${tab}-client-files`}>
      <h3>The client&apos;s {AREA_FILES[tab]} ({files.length})</h3>
      {children}
      <ClientFiles projectId={projectId} view={client} files={files} act={act} onRetag={onRetag} onSaved={onSaved} />
    </section>
  );
}
