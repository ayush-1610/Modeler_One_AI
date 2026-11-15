// After a decision on the delivery (plan 2026-11-14 §2.1 "fewer refetches", slice 4; final review OWN-7, CODE-4): the
// answer is written into the page's cache and only what it changed is read again, so a decision costs at most two
// requests (the decision, and the one card or page it changed) instead of every read on the page. `values:assign`,
// `regions:exclude` and `regions:restore` answer the delivery page; a layout's decisions answer the layout, and its files
// are read again; a decision on a card (`:enter`, `:override`, `:dispose`, `:choose`, `:link`) answers the card, and the
// spot check its draw.

import type { QueryClient, QueryKey } from "@tanstack/react-query";

import type { Schema } from "@/lib/api";
import type { After, Read } from "@/lib/hooks";

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
const CARD = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;
const SPOT = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}/spot-check" as const;
const MAPPING = "/api/v1/projects/{project_id}/delivery/mappings/{mapping_id}" as const;
type Page = Schema<"DeliveryPage">;
type Mapping = Schema<"DeliveryMapping">;
type SubjectRow = Schema<"DeliverySubjectRow">;
type Subject = Schema<"DeliverySubject">;
type Spot = Schema<"DeliverySpotCheck">;

export const pageKey = (projectId: string): QueryKey => [DELIVERY, { project_id: projectId }, {}];
export const cardKey = (projectId: string, type: string, subject: string): QueryKey => [CARD, { project_id: projectId, type, subject }, {}];
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

/** The newest version a layout's answer knows of: the answer is the layout's latest when it is that version. */
const newest = (m: Mapping) => Math.max(m.version, ...m.versions.map((v) => v.version));

/** Write a layout a decision answered under every key a dialog shows it by, and read the page again: its list of layouts
 *  changed and the files of the layout are being read again. The cards follow when the reading ends. The keys follow
 *  the API's own rule (GET …/mappings/{id}: no `version` is the latest, a file and region the table it is shown on):
 *  the answer is written at its version, and, when it is the latest by its own list of versions, with no version, each
 *  both on no table and on the table it shows. A dialog opened with no version on a table (the one "Read this table…"
 *  opens on the layout it stored) is written as one opened at the version (final review round 2's regression). */
export function writeMapping(client: QueryClient, projectId: string, m: Mapping) {
  const params = { project_id: projectId, mapping_id: m.mapping_id };
  // every answer of this layout says how each of its tables is read, which the decision changed: read again when shown
  void client.invalidateQueries({ predicate: (q) => q.queryKey[0] === MAPPING && (q.queryKey[1] as { mapping_id?: string })?.mapping_id === m.mapping_id,
                                  refetchType: "none" });
  const at = m.sample ? { file_sha256: m.sample.file_sha256, region_id: m.sample.region_id } : null;
  const versions = [{ version: String(m.version) }, ...(newest(m) === m.version ? [{}] : [])];
  for (const v of versions) {
    client.setQueryData([MAPPING, params, v], m);
    if (at) client.setQueryData([MAPPING, params, { ...v, ...at }], m);
  }
  void client.invalidateQueries({ predicate: (q) => q.queryKey[0] === CARD, refetchType: "none" });
  void client.invalidateQueries({ queryKey: pageKey(projectId), exact: true });
}

/** Read the page again after something that changes it without answering it (a file read again). */
export function readPage(client: QueryClient, projectId: string) {
  void client.invalidateQueries({ queryKey: pageKey(projectId), exact: true });
}

/** A reading a decision asked for has ended (its layout no longer waits): the page and the cards shown are read again
 *  (the others are stale already), as when the page sees its reading end. */
export function readReading(client: QueryClient, projectId: string) {
  readPage(client, projectId);
  void client.invalidateQueries({ predicate: (q) => q.queryKey[0] === CARD && (q.queryKey[1] as { project_id?: string })?.project_id === projectId });
}

/** A decision on a subject's card (`:enter`, `:override`, `:dispose`, `:choose`, `:link`): the answer is the card, written
 *  under the key every part of the page reads it by (its own area, the work model's counts, Populations and
 *  individuals); `reads`: the delivery page, read again once, since the subject's row there (how many values it has and
 *  how they were read) follows the card. Nothing else on the page changed. */
export function cardAfter(projectId: string, reads: readonly Read[] = [DELIVERY]): After<Subject> {
  return { write: (card, client) => client.setQueryData(cardKey(projectId, card.subject_type, card.subject), card), reads };
}

/** The spot check's draw or record: the answer is the draw (written where "Show the values to check" reads it); the
 *  subject's card says how far the spot check is and whether it still holds the signature, so that one card is read
 *  again. */
export function spotAfter(projectId: string, type: string, subject: string): After<Spot> {
  return {
    write: (spot, client) => client.setQueryData([SPOT, { project_id: projectId, type, subject }, {}], spot),
    keys: [cardKey(projectId, type, subject)],
  };
}

/** What a signed confirmation changed, once its dialog has said what loaded: the card (its answer); the delivery page;
 *  the model inputs, the datasets and dissolution records, the sheet form's groups of the same source (loaded now), all
 *  read again; the other cards marked stale (one landing can name another's source), read when next shown. The step bar
 *  follows the readiness (the workspace draws it again when the readiness changes). */
export function writeConfirmed(client: QueryClient, projectId: string, card: Subject): Promise<void> {
  const key = cardKey(projectId, card.subject_type, card.subject);
  client.setQueryData(key, card);
  void client.invalidateQueries({ predicate: (q) => q.queryKey[0] === CARD && cardRef(q.queryKey) !== ref(card), refetchType: "none" });
  const reads = new Set<string>([DELIVERY, "/api/v1/projects/{project_id}/inputs", "/api/v1/projects/{project_id}/client-review",
                                 "/api/v1/projects/{project_id}/client-data", "/api/v1/projects/{project_id}/evidence"]);
  return client.invalidateQueries({ predicate: (q) => reads.has(q.queryKey[0] as string) });
}
