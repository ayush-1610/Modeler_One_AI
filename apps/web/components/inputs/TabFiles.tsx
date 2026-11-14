"use client";

// The client's files by the area their data belong to (plan 2026-11-05 §3.1, the owner's answer of 2026-11-05): a file's
// tag names its area (Clinical studies, Products and dissolution, Compound), and its data land there. Since the frame of
// plan 2026-11-14 (slice 1) every file is listed once, in the Client files area, filed under the area its tag names; the
// head's "Add data" adds files for an area. A file's tag is changed on its row, and the file is filed again with it.

import type { ReactNode } from "react";

import { type Act, ClientFiles, type Retag } from "@/components/client/ClientFiles";
import type { ClientFile, View as ClientView } from "@/components/client/types";
import { upload } from "@/lib/api";
import { type DataTab, TAG_TAB, type TagKind, guessStudy, tagFor, tagsField } from "@/lib/fileTags";

import type { Run } from "./InputsTodo";

export const AREA_LABEL: Record<DataTab, string> = {
  compound: "Compound", formulations: "Products and dissolution", studies: "Clinical studies",
};
export const AREA_FILES: Record<DataTab, string> = {
  compound: "in vitro and physico-chemistry files", formulations: "formulation and dissolution files",
  studies: "clinical and bioanalytical files",
};
/** The areas in the order their files are listed. */
export const FILE_AREAS: DataTab[] = ["studies", "formulations", "compound"];
export const ACCEPT = ".xlsx,.xlsm,.xls,.csv,.pdf,.docx,.md,.txt,.zip";
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The area a client file is filed under, by its tag; a file tagged "other" whose content code reads as another kind is
 *  filed where that reading puts it, with the reading on its row to use or keep (kept "other", it waits to be placed).
 *  A file with no tag (a store that keeps no library record), or the client-data template tagged "other", is filed with
 *  the clinical studies, as before. */
export function fileArea(file: ClientFile): DataTab | null {
  if (!file.tag) return "studies";
  // the client-data template holds every kind of data, read cell by cell: filed with the studies unless tagged otherwise
  if (file.template && file.tag.kind === "other") return "studies";
  const reading = file.tag_proposal?.decided === "open" ? file.tag_proposal.kind : null;
  return TAG_TAB[file.tag.kind === "other" && reading ? reading : file.tag.kind];
}

export function whereShown(kind: TagKind): string {
  const area = TAG_TAB[kind];
  return area ? `filed under ${AREA_LABEL[area]}` : "not filed under an area until you say what it is";
}

/** Store the client's files added for an area: each takes the tag its name says, else the area's (a name that says what it
 *  is wins: a dissolution workbook added for Clinical studies is filed under Products and dissolution). */
export async function addClientFiles(projectId: string, run: Run, list: FileList | null, tab: DataTab) {
  if (!list?.length) return;
  const files = Array.from(list);
  const tagged = files.map((file) => ({ file, tag: tagFor(file.name, tab), study: guessStudy(file.name) }));
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  form.set("tags", tagsField(tagged));
  const elsewhere = tagged.filter((t) => TAG_TAB[t.tag] !== tab).map((t) => `${t.file.name} is ${whereShown(t.tag)}, by its name`);
  await run(() => upload("/api/v1/projects/{project_id}/client-data", { project_id: projectId }, form),
            `${plural(files.length, "file")} stored.${elsewhere.length ? ` ${elsewhere.join("; ")}.` : ""}`
            + " Each is listed under Client files: open each data sheet there, check its reading and save it.");
}

/** The files filed under one area (or not placed yet), each with what it holds, its sheets and their reading. */
export function FileGroup({ id, title, projectId, client, files, act, onRetag, onSaved, children }: {
  id: string; title: string; projectId: string; client: ClientView; files: ClientFile[]; act: Act; onRetag?: Retag;
  onSaved: (message: string) => Promise<void>; children?: ReactNode;
}) {
  if (files.length === 0) return null;
  return (
    <section className="client-files" data-testid={`${id}-client-files`} id={`${id}-client-files`}>
      <h3>{title} ({files.length})</h3>
      {children}
      <ClientFiles projectId={projectId} view={client} files={files} act={act} onRetag={onRetag} onSaved={onSaved} />
    </section>
  );
}
