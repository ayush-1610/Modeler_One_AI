// After a decision on the delivery (plan 2026-11-14 §2.1 "fewer refetches", slice 4): the answer is written into the
// page's cache and only what it changed is read again, so a decision costs at most two requests (the decision, and the
// one card or page it changed) instead of every read on the page. `values:assign`, `regions:exclude` and
// `regions:restore` answer the delivery page; a layout's decisions answer the layout, and its files are read again.

import type { QueryClient, QueryKey } from "@tanstack/react-query";

import type { Schema } from "@/lib/api";

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
const CARD = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;
const MAPPING = "/api/v1/projects/{project_id}/delivery/mappings/{mapping_id}" as const;
type Page = Schema<"DeliveryPage">;
type Mapping = Schema<"DeliveryMapping">;
type SubjectRow = Schema<"DeliverySubjectRow">;

export const pageKey = (projectId: string): QueryKey => [DELIVERY, { project_id: projectId }, {}];
const ref = (s: { subject_type?: string; type?: string; subject: string }) => `${s.subject_type ?? s.type}/${s.subject}`;
const cardRef = (key: QueryKey) => (key[0] === CARD ? ref(key[1] as { type: string; subject: string }) : null);
const own = (s: SubjectRow) => JSON.stringify([s.values, s.by_level, s.arms, s.batches, s.confirmation, s.files, s.label]);

/** The subjects whose own row a decision changed (their values, how they were read, their arms or batches, files or
 *  confirmation), as `${type}/${subject}`: what their cards show changed with it. */
export function changedSubjects(before: Page | undefined, after: Page): string[] {
  const was = new Map((before?.subjects ?? []).map((s) => [ref(s), own(s)] as const));
  return after.subjects.filter((s) => was.get(ref(s)) !== own(s)).map(ref);
}

/** Write the delivery page a decision answered. The cards of the subjects it changed are read again; every other card
 *  only changed in the delivery-wide clean-up (which the page says itself), so it is marked stale and read again when it
 *  is next shown. */
export function writePage(client: QueryClient, projectId: string, page: Page) {
  const before = client.getQueryData<Page>(pageKey(projectId));
  client.setQueryData(pageKey(projectId), page);
  const changed = new Set(changedSubjects(before, page));
  void client.invalidateQueries({ predicate: (q) => q.queryKey[0] === CARD && !changed.has(cardRef(q.queryKey) ?? ""), refetchType: "none" });
  void client.invalidateQueries({ predicate: (q) => changed.has(cardRef(q.queryKey) ?? "") });
}

/** Write a layout a decision answered (at its version, and as the latest when it is), and read the page again: its list
 *  of layouts changed and the files of the layout are being read again. The cards follow when the reading ends. */
export function writeMapping(client: QueryClient, projectId: string, m: Mapping) {
  const params = { project_id: projectId, mapping_id: m.mapping_id };
  // every answer of this layout says how each of its tables is read, which the decision changed: read again when shown
  void client.invalidateQueries({ predicate: (q) => q.queryKey[0] === MAPPING && (q.queryKey[1] as { mapping_id?: string })?.mapping_id === m.mapping_id,
                                  refetchType: "none" });
  client.setQueryData([MAPPING, params, { version: String(m.version) }], m);
  // the answer is shown on the table the dialog asked for (the one it was opened from): written under that key too
  if (m.sample) {
    client.setQueryData([MAPPING, params, { version: String(m.version), file_sha256: m.sample.file_sha256, region_id: m.sample.region_id }], m);
  }
  const latest = client.getQueryData<Mapping>([MAPPING, params, {}]);
  if (!latest || latest.version <= m.version) client.setQueryData([MAPPING, params, {}], m);
  void client.invalidateQueries({ predicate: (q) => q.queryKey[0] === CARD, refetchType: "none" });
  void client.invalidateQueries({ queryKey: pageKey(projectId), exact: true });
}

/** Read the page again after something that changes it without answering it (a file read again). */
export function readPage(client: QueryClient, projectId: string) {
  void client.invalidateQueries({ queryKey: pageKey(projectId), exact: true });
}
