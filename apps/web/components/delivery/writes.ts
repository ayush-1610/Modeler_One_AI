// After a decision on the delivery (plan 2026-11-14 §2.1 "fewer refetches", slice 4; final review OWN-7, CODE-4): the
// answer is written into the page's cache and only what it changed is read again, so a decision costs at most two
// requests (the decision, and the one card or page it changed) instead of every read on the page. `values:assign`,
// `regions:exclude` and `regions:restore` answer the delivery page; a layout's decisions answer the layout, and its files
// are read again; a decision on a card (`:enter`, `:override`, `:dispose`, `:choose`, `:link`) answers the card, and the
// spot check its draw.
//
// One rule follows every answer of the delivery page a decision brings (`followRows`, final review round 5): the cards
// of the subjects whose rows it changed are read again, now where they are shown or counted, else when next shown. A
// decision can change rows other than its own subject's: in a project whose blinding is on, a study the MS-01 split
// proposes for S5 once its signature lands its dataset, or one entered for external validation, is blinded with every
// product that holds its values (round 4 left such a product's card showing the study's values).
//
// One rule follows a change of the project's blinding, either way, whichever answer shows it (`followBlinding`, final
// review round 6): the API withholds by file and by name too, beyond the rows that changed (the why of a decision about a
// file that now holds a blinded study's values, on the card of another study; a layout's headers; a source page; a
// dataset's points; the Studies list's chip), so everything of the project the blinding changes is read again, once.

import type { QueryClient, QueryKey } from "@tanstack/react-query";

import type { Schema } from "@/lib/api";
import { changedRows, followFrom, type Followed } from "@/lib/freshness";
import { moment, put, readAgain, type After, type Read } from "@/lib/hooks";

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
const CARD = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;
const SPOT = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}/spot-check" as const;
const MAPPING = "/api/v1/projects/{project_id}/delivery/mappings/{mapping_id}" as const;
const SOURCE = "/api/v1/projects/{project_id}/delivery/source" as const;
type Page = Schema<"DeliveryPage">;
type Mapping = Schema<"DeliveryMapping">;
type Subject = Schema<"DeliverySubject">;
type Spot = Schema<"DeliverySpotCheck">;

export const pageKey = (projectId: string): QueryKey => [DELIVERY, { project_id: projectId }, {}];
export const cardKey = (projectId: string, type: string, subject: string): QueryKey => [CARD, { project_id: projectId, type, subject }, {}];
const ref = (s: { subject_type?: string; type?: string; subject: string }) => `${s.subject_type ?? s.type}/${s.subject}`;
/** A card of the project's, by its reference (null: not a card, or another project's). */
const cardOf = (key: QueryKey, projectId: string) => {
  const params = key[1] as { project_id?: string; type: string; subject: string } | undefined;
  return key[0] === CARD && params?.project_id === projectId ? ref(params) : null;
};

/** Everything of a project whose answer a change of its blinding changes (final review round 6; the API's
 *  `modeler_project.blinded_sources`, by file and by name): the delivery's page; every card (its values, its spot check,
 *  and the why of a decision about a file that holds a blinded study's values, masked on any card); the layout views
 *  (their headers and findings masked by file) and the source view (a page withheld by file); the inputs (the Studies
 *  list says which studies are blinded) and the evidence (a dataset's points); the client's files and their sheets, the
 *  sheet form's groups, the documents, their pages and the figures suggested from them. */
const BLINDING: readonly Read[] = [
  DELIVERY, CARD, SPOT, MAPPING, SOURCE,
  "/api/v1/projects/{project_id}/inputs", "/api/v1/projects/{project_id}/evidence",
  "/api/v1/projects/{project_id}/client-data", "/api/v1/projects/{project_id}/client-data/{sid}/sheets/{sheet}",
  "/api/v1/projects/{project_id}/client-review", "/api/v1/projects/{project_id}/documents",
  "/api/v1/projects/{project_id}/documents/{sha256}/pages/{page}", "/api/v1/projects/{project_id}/documents/{sha256}/figures",
];

// per page (its cache) and project: the last following of a change of the blinding
const followed = new WeakMap<QueryClient, Map<string, Followed>>();

/** The one place that decides what a change of the project's blinding reads (final review round 6), either way (a study
 *  or product blinded, no longer blinded, or blinded for another reason), whichever answer shows it: a delivery row
 *  (`followRows`) or the studies the inputs say are blinded (`blindingChanged`, components/inputs/after.ts). Everything
 *  of the project the blinding changes (`BLINDING`) is read again, at once where it is shown or counted (the work model
 *  counts every card), else when next shown, except what was read or written in the moment `since` or later (the moment
 *  the answer that shows the change was read in, or the decision's): that holds the change already. An answer read by an
 *  earlier following of the same change (the inputs it read again, say) shows that change again: it is followed from the
 *  same moment, so nothing is read twice when both rules see it (round 5's gap a: a signed landing the split blinds read
 *  the client data, the sheet form, the documents, the evidence and the delivery twice). */
export function followBlinding(client: QueryClient, projectId: string, since: number): Promise<void> {
  const projects = followed.get(client) ?? new Map<string, Followed>();
  followed.set(client, projects);
  const from = followFrom(projects.get(projectId), since);
  projects.set(projectId, { since: from, at: moment() });
  return readAgain(client, BLINDING, from, projectId);
}

/** Follow a new answer of the delivery page (`after`, against `before`, the page as it was before the decision): the
 *  cards of the subjects whose rows changed are read again, at once where they are shown or counted, else when next
 *  shown (`changedRows`, lib/freshness.ts), except `answered`, the cards the decision's own answer wrote (current). When a
 *  subject's blinding changed, the blinding's own rule follows instead (`followBlinding`: every card, and what the
 *  blinding withholds elsewhere; `since`, the moment the decision was answered in: what was read or written since holds
 *  it). A decision that changes no other row reads nothing more. */
export function followRows(client: QueryClient, projectId: string, before: Page | undefined, after: Page,
                           { answered = [], since = moment() }: { answered?: readonly string[]; since?: number } = {}) {
  const { changed, blinding } = changedRows(before, after);
  if (blinding) {
    void followBlinding(client, projectId, since);
    return;
  }
  const stale = new Set(changed.filter((r) => !answered.includes(r)));
  if (stale.size) void client.invalidateQueries({ predicate: (q) => stale.has(cardOf(q.queryKey, projectId) ?? "") });
}

/** Read the delivery page again after a decision whose answer is not the page, and follow it (`followRows`): `before`,
 *  the page as the decision found it (default: as the page holds it now); `answered`, the cards the decision's answer
 *  wrote; `since`, the moment the decision was answered in (default: now; several decisions, the first one's). Waited
 *  for by the decision (its `After`), as its reads are. */
export async function followPage(client: QueryClient, projectId: string,
                                 { answered = [], before, since }: { answered?: readonly string[]; before?: Page; since?: number } = {}) {
  const was = before ?? client.getQueryData<Page>(pageKey(projectId));
  const asked = since ?? moment();
  await client.invalidateQueries({ queryKey: pageKey(projectId), exact: true });
  const page = client.getQueryData<Page>(pageKey(projectId));
  if (page && page !== was) followRows(client, projectId, was, page, { answered, since: asked });
}

/** `followPage` for every project whose delivery page the page holds (a change named by its route, not its project). */
export function followPages(client: QueryClient): Promise<void> {
  const projects = client.getQueryCache().findAll({ predicate: (q) => q.queryKey[0] === DELIVERY })
    .map((q) => (q.queryKey[1] as { project_id: string }).project_id);
  return Promise.all([...new Set(projects)].map((p) => followPage(client, p))).then(() => undefined);
}

/** Write the delivery page a decision answered. The cards of the subjects whose rows it changed are read again
 *  (`followRows`); every other card only changed in the delivery-wide clean-up (which the page says itself), so it is
 *  marked stale and read again when it is next shown. */
export function writePage(client: QueryClient, projectId: string, page: Page) {
  const before = client.getQueryData<Page>(pageKey(projectId));
  put(client, pageKey(projectId), page);
  void client.invalidateQueries({ predicate: (q) => cardOf(q.queryKey, projectId) !== null, refetchType: "none" });
  followRows(client, projectId, before, page);
}

/** The newest version a layout's answer knows of: the answer is the layout's latest when it is that version. */
const newest = (m: Mapping) => Math.max(m.version, ...m.versions.map((v) => v.version));

/** Write a layout a decision answered under every key a dialog shows it by, and read the page again: its list of layouts
 *  changed and the files of the layout are being read again. The page follows that reading to its end, and the cards
 *  and the To do rows with it (`useDeliveryRefresh`). A read of the layout sent before the decision is called off, so it
 *  cannot put back the layout as it was (`put`, final review round 4). The keys follow
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
    put(client, [MAPPING, params, v], m);
    if (at) put(client, [MAPPING, params, { ...v, ...at }], m);
  }
  void client.invalidateQueries({ predicate: (q) => q.queryKey[0] === CARD, refetchType: "none" });
  void client.invalidateQueries({ queryKey: pageKey(projectId), exact: true });
}

/** Read the page again after something that changes it without answering it (a file read again). */
export function readPage(client: QueryClient, projectId: string) {
  void client.invalidateQueries({ queryKey: pageKey(projectId), exact: true });
}

/** A decision on a subject's card (`:enter`, `:override`, `:dispose`, `:choose`, `:link`): the answer is the card, written
 *  under the key every part of the page reads it by (its own area, the work model's counts, Populations and
 *  individuals); the delivery page is read again once, since the subject's row there (how many values it has and how
 *  they were read) follows the card, and followed (`followPage`): a decision on one card can change another's row (a
 *  study entered for external validation blinds the products that hold its values; a link merges two studies).
 *  `before`: the page as the decision found it; `page` false: the delivery page is read once after several decisions
 *  (the facts form's), by its caller. */
export function cardAfter(projectId: string, { before, page = true }: { before?: Page; page?: boolean } = {}): After<Subject> {
  return {
    write: (card, client) => {
      put(client, cardKey(projectId, card.subject_type, card.subject), card);
      if (page) return followPage(client, projectId, { answered: [ref(card)], before });
    },
  };
}

/** The reference a decision's answer (a card) is followed by: what `followPage` leaves out as `answered`. */
export const answeredBy = (card: { subject_type: string; subject: string }) => ref(card);

/** The spot check's draw or record: the answer is the draw (written where "Show the values to check" reads it); the
 *  subject's card says how far the spot check is and whether it still holds the signature, so that one card is read
 *  again. */
export function spotAfter(projectId: string, type: string, subject: string): After<Spot> {
  return {
    write: (spot, client) => put(client, [SPOT, { project_id: projectId, type, subject }, {}], spot),
    keys: [cardKey(projectId, type, subject)],
  };
}

/** What a signed confirmation changed, once its dialog has said what loaded: the card (its answer); the model inputs;
 *  the sheet form's groups of the same source (loaded now); the client's files and their dissolution profiles; the
 *  evidence when the landing put datasets or values in it (a product's lands its dissolution records only) — each
 *  measured by the API's answers before and after (final review round 4); and the delivery page, followed
 *  (`followPage`). With blinding off, only the subject's own row changes, so nothing more is read (a card names the
 *  sheet form's datasets of its source, `loaded_elsewhere`, never the delivery's, and a landing makes only the
 *  delivery's). With blinding on and no plan, the landing puts the study's dataset in the catalog, the MS-01 split can
 *  propose S5 for it, and the study is then blinded with every product that holds its values: their rows say so, and
 *  their cards are read again (final review round 5: round 4's "no other card changes" held only with blinding off).
 *  `before`: the page as the signature found it (the dialog's). `sent`: when the signature was sent. The step bar
 *  follows the readiness (the workspace draws it again when the readiness changes). */
export function writeConfirmed(client: QueryClient, projectId: string, card: Subject,
                               { before, sent }: { before?: Page; sent?: number } = {}): Promise<void> {
  put(client, cardKey(projectId, card.subject_type, card.subject), card, sent);
  const since = moment();
  const landed = card.confirmation?.landed;
  const evidence = !landed || landed.datasets.length > 0 || landed.evidence.length > 0;
  const reads = new Set<string>(["/api/v1/projects/{project_id}/inputs", "/api/v1/projects/{project_id}/client-review",
                                 "/api/v1/projects/{project_id}/client-data", ...(evidence ? ["/api/v1/projects/{project_id}/evidence"] : [])]);
  return Promise.all([client.invalidateQueries({ predicate: (q) => reads.has(q.queryKey[0] as string) }),
                      followPage(client, projectId, { answered: [ref(card)], before, since })]).then(() => undefined);
}
