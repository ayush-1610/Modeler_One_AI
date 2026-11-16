// What a change on Inputs makes stale, by the kind of change (final review OWN-7, CODE-4; plan 2026-11-14 §2.1 "fewer
// refetches"): said once here, so every place that makes the same change reads the same things again, and nothing else.
// A change answered with what it changed has that answer written into the page's cache (a choice answers the inputs, a
// decision on a value or a dataset the evidence, the sheet form its groups); a read named here is read again where it is
// shown and marked stale elsewhere (read when next shown). What a decision on Compound and a confirmation read again was
// checked against the API's answers before and after it, and against the code that answers (final review round 4). The step bar, drawn on the server, follows the readiness: the workspace
// draws it again when the readiness the inputs answer with changes (`InputsWorkspace`), whatever changed it. A decision
// on the delivery is written by `components/delivery/writes.ts`. Two rules follow what a decision changed beyond what it
// names (final review rounds 5 and 6): a read of the delivery page is followed by the cards whose rows it changed
// (`followPage`), and a change of the project's blinding, seen in a delivery row or in the studies the inputs say are
// blinded (`blindingChanged`, which the workspace calls on every answer of the inputs), has everything of the project
// the blinding changes read again, once (`followBlinding`, writes.ts: one place decides what it reads).

import type { QueryClient } from "@tanstack/react-query";

import { followBlinding, followPage, followPages } from "@/components/delivery/writes";
import type { Schema } from "@/lib/api";
import { moment, put, readAgain, readMoment, type After, type Read } from "@/lib/hooks";

const P = "/api/v1/projects/{project_id}" as const;
export const INPUTS = `${P}/inputs` as const;
export const EVIDENCE = `${P}/evidence` as const;
export const REUSE = `${P}/value-reuse` as const;
export const CLIENT_DATA = `${P}/client-data` as const;
export const CLIENT_REVIEW = `${P}/client-review` as const;
export const DELIVERY = `${P}/delivery` as const;
export const DOCUMENTS = `${P}/documents` as const;
export const READING = `${P}/reading-queue` as const;
export const LITERATURE = `${P}/literature-run` as const;
export const BRIEF = `${P}/brief` as const;
const CARD = `${P}/delivery/subjects/{type}/{subject}` as const;

type InputsPage = Schema<"InputsPage">;
type EvidencePage = Schema<"EvidencePage">;
type ReviewPage = Schema<"ClientReviewPage">;

const key = (route: Read, projectId: string) => [route, { project_id: projectId }, {}];

/** What the person's other projects of the drug offer (`value-reuse`) is what they found that this project does not hold
 *  yet, compared by parameter, value, unit, source and quote, whatever its state here (`modeler_project.value_reuse`).
 *  So a decision on a value held already (accepted, rejected, kept over the others, a pKa's acid or base) or on a study
 *  or a dataset never changes it, and a value newly held here can only take an offer away: the offers are read again
 *  only when the page holds one (final review round 4: every decision on Compound read them again). */
function offersFollow(client: QueryClient, projectId: string) {
  const offers = client.getQueryData<Schema<"ValueReusePage">>(key(REUSE, projectId));
  if (offers?.offers.length) void client.invalidateQueries({ queryKey: key(REUSE, projectId), exact: true });
}

/** A model input changed that holds no new value (a dataset's study, its facts or its overlay): the inputs, assembled
 *  again with it (their rows, to-do and readiness), and the evidence and its datasets. */
export const MODEL: After = { reads: [INPUTS, EVIDENCE] };

/** Values newly held here (added with their source, a published model's values and datasets): the inputs, the evidence,
 *  and the other projects' offers where the page holds one. */
export function valuesAfter(projectId: string): After {
  return { write: (_answer, client) => offersFollow(client, projectId), reads: [INPUTS, EVIDENCE] };
}

/** `valuesAfter` for values that arrived with no answer to write (the literature agent's end; the compound values entered
 *  in To do, one `POST` each, read once after the last). */
export function valuesArrived(client: QueryClient, projectId: string): Promise<void> {
  offersFollow(client, projectId);
  return readAgain(client, [INPUTS, EVIDENCE]);
}

/** Another project's values reused here (`value-reuse`, with the person's consent): its offer is spent, so the offers are
 *  read again with the inputs and the evidence. */
export const REUSED: After = { reads: [INPUTS, EVIDENCE, REUSE] };

/** A change answered with the inputs page (a PK-Sim name or process chosen, a formulation chosen, a study left out, the
 *  inputs assembled): written; `reads`, what else it changed (nothing, for a choice). */
export function inputsAfter(projectId: string, reads: readonly Read[] = []): After<InputsPage> {
  return { write: (page, client) => put(client, key(INPUTS, projectId), page), reads };
}

/** The molecular weight proposed from the identity (answered with the inputs page, written): a value newly held, so the
 *  evidence, and the offers where the page holds one. */
export function identityAfter(projectId: string): After<InputsPage> {
  return { write: (page, client) => { put(client, key(INPUTS, projectId), page); offersFollow(client, projectId); }, reads: [EVIDENCE] };
}

/** A decision on a value held here (`evidence/{id}:decide`: accepted, rejected or excluded; an access request fulfilled),
 *  answered with the evidence page, written: the inputs, assembled again with it. Nothing else changed. */
export function evidenceAfter(projectId: string): After<EvidencePage> {
  return { write: (page, client) => put(client, key(EVIDENCE, projectId), page), reads: [INPUTS] };
}

/** One value kept over the others (`evidence/{id}:choose`, answered with the ids it rejected and the evidence page): the
 *  page written, the inputs read again. */
export function chooseAfter(projectId: string): After<Schema<"EvidenceChoice">> {
  return { write: ({ rejected: _rejected, ...page }, client) => put(client, key(EVIDENCE, projectId), page), reads: [INPUTS] };
}

/** A value corrected (`evidence/{id}:correct`, answered with the corrected copy and the evidence page): the page written,
 *  the inputs read again. A pKa's acid or base keeps its parameter, value and source, so nothing else changes; filed under
 *  another parameter or given the number its quote states (`newValue`), the copy is a value newly held, and the offers
 *  follow where the page holds one. */
export function correctAfter(projectId: string, newValue: boolean): After<Schema<"EvidenceCorrection">> {
  return {
    write: ({ corrected: _corrected, ...page }, client) => {
      put(client, key(EVIDENCE, projectId), page);
      if (newValue) offersFollow(client, projectId);
    },
    reads: [INPUTS],
  };
}

/** A dataset kept or left out (`datasets/{id}:decide`, answered with the evidence page, written): the inputs, and the
 *  sheet form's groups, which say which of their datasets are in the model. A delivery subject that names the dataset (one
 *  its signature loaded, or one of its source the sheet form read) says it too: the delivery page and that card are read
 *  again, only then. */
export function datasetAfter(projectId: string, dataset: string): After<EvidencePage> {
  return {
    write: (page, client) => {
      put(client, key(EVIDENCE, projectId), page);
      const delivery = client.getQueryData<Schema<"DeliveryPage">>(key(DELIVERY, projectId));
      return readSubjects(client, projectId, (delivery?.subjects ?? []).filter((s) => [
        ...s.loaded_elsewhere, ...s.proposed_elsewhere, ...(s.confirmation?.landed_datasets ?? [])].includes(dataset)));
    },
    reads: [INPUTS, CLIENT_REVIEW],
  };
}

/** A search started (the sources and the literature, or the observed-data agent): its progress is read; what it finds
 *  is read when it finishes (the workspace reads the inputs again then). */
export const SEARCH: After = { reads: [LITERATURE] };

/** Files arrived (uploaded, the library's documents read for data, read again, filed under another area, a sheet
 *  classified): the client's files, their reading, the delivery that reads them (read again, it says it is reading, and
 *  the page follows the reading to its end) and the documents; the sheet form's groups follow what the files hold. */
export const FILES: After = { reads: [CLIENT_DATA, CLIENT_REVIEW, DELIVERY, READING, DOCUMENTS] };

/** A sheet read with the sheet form and saved (`client-data/{sid}:map`): the file says which of its sheets are read, the
 *  sheet form has its group to confirm (one more in the inputs' to-do), and the delivery joins it to its subjects: its
 *  page is read again and followed (`followPages`: a subject joined to the group says so on its card, and a sheet read
 *  for external validation in a project whose blinding is on blinds the delivery's study of that name with the products
 *  that hold its values). The sheet's own view says it was read before (`read_before`), which is what offers to replace
 *  that reading when it is read again: without it, a second save in the same visit would add the same datasets twice
 *  (final review round 4: it was current only because the delivery's end-of-reading refresh reads every route under the
 *  client data again). */
export const SHEET: After = { write: (_answer, client) => followPages(client),
                              reads: [CLIENT_DATA, `${CLIENT_DATA}/{sid}/sheets/{sheet}`, CLIENT_REVIEW, INPUTS] };

/** The AI reading asked for again: the reading queue and the files it reads. */
export const READ_AGAIN: After = { reads: [READING, CLIENT_DATA] };

/** An AI reading finished (not a decision: the queue says so): what it read is in the files, the sheet form and the
 *  evidence, so those, the inputs, the delivery and the documents are read again. */
export const READ_DONE: After = { reads: [CLIENT_DATA, CLIENT_REVIEW, INPUTS, EVIDENCE, DELIVERY, DOCUMENTS] };

/** A figure digitized into a dataset (`datasets:digitize`): a model input (the dataset, no value), and the figures of its
 *  document say which are digitized. */
export const DIGITIZED: After = { reads: [...MODEL.reads!, `${P}/documents/{sha256}/figures`] };

/** A dissolution profile proposed as a product's release (`dissolution/{id}:propose`): its profile says so, and the
 *  product's release values are proposed in the evidence (values newly held: the offers follow where the page holds one). */
export function releaseAfter(projectId: string): After {
  return { write: (_answer, client) => offersFollow(client, projectId), reads: [CLIENT_DATA, INPUTS, EVIDENCE] };
}

/** A brief's list changed (its products, its populations): the brief; the data plan, the client data's plan and the inputs
 *  follow it; Start's step (drawn on the server) says what the brief still needs. */
export const BRIEF_CHANGED: After = { reads: [BRIEF, INPUTS, CLIENT_DATA], server: true };

const writeReview = (projectId: string) => (page: ReviewPage, client: QueryClient) => put(client, key(CLIENT_REVIEW, projectId), page);

/** A selection made in a sheet form's group, or one changed again, before it is confirmed (answered with the groups,
 *  written): the inputs' to-do says how many items of the group are still open. */
export function reviewAfter(projectId: string): After<ReviewPage> {
  return { write: writeReview(projectId), reads: [INPUTS] };
}

/** A sheet read into the sheet form (`client-review:finish`, answered with the groups, written): its group is one more
 *  to confirm in the inputs' to-do, and the delivery joins the groups of a source it reads to its subjects (its page read
 *  again and followed, as `SHEET`'s). */
export function sheetReadAfter(projectId: string): After<ReviewPage> {
  return { write: (page, client) => { writeReview(projectId)(page, client); return followPage(client, projectId); }, reads: [INPUTS] };
}

/** A sheet form's group confirmed (`client-review:confirm`, answered with the groups, written): what it holds is in the
 *  model now, so the inputs are read again (its to-do, and its readiness, which the step bar follows), and what else the
 *  confirmation changed, by what the group holds (`modeler_project.client_review.confirm`; final review round 4, each
 *  measured by the API's answers before and after): the evidence when it loads datasets or values (a study's datasets,
 *  the compound's values); the client data when a product's profile was chosen between two files (its dissolution
 *  profiles are put together again); the delivery page and a card where one of its subjects reads the same source (the
 *  group is one of a subject's `legacy_groups`: its card says what of its source is in the model). A product's
 *  confirmation that chose no profile changes the inputs' to-do and nothing else. */
export function confirmAfter(projectId: string, group: Schema<"ReviewGroup">): After<ReviewPage> {
  const loads = group.items.some((i) => i.kind === "dataset" || i.kind === "value") || group.kind === "compound";
  const profiles = group.kind === "product"
    && group.issues.some((i) => i.kind !== "link" && !i.id.split("|").slice(1).join("|").startsWith("demographics:"));
  return {
    write: (page, client) => {
      writeReview(projectId)(page, client);
      const delivery = client.getQueryData<Schema<"DeliveryPage">>(key(DELIVERY, projectId));
      return readSubjects(client, projectId, (delivery?.subjects ?? []).filter((s) => s.legacy_groups.includes(group.id)));
    },
    reads: [INPUTS, ...(loads ? [EVIDENCE] : []), ...(profiles ? [CLIENT_DATA] : [])],
  };
}

/** The cards of `subjects` read again, and the delivery page with them, followed (`followPage`: another subject's row
 *  it changed has its card read again too); none: nothing is read. */
function readSubjects(client: QueryClient, projectId: string, subjects: Schema<"DeliverySubjectRow">[]): Promise<void> | undefined {
  if (!subjects.length) return;
  for (const s of subjects) {
    void client.invalidateQueries({ queryKey: [CARD, { project_id: projectId, type: s.subject_type, subject: s.subject }, {}], exact: true });
  }
  return followPage(client, projectId, { answered: subjects.map((s) => `${s.subject_type}/${s.subject}`) });
}

/** The studies the inputs say are blinded changed (final review round 5): the workspace compares them on every answer of
 *  the inputs (`lib/freshness.ts` `blindedStudies`), whatever changed them. A study's datasets put in the catalog (a sheet
 *  form's group confirmed, a dataset kept or left out, a study's facts or purpose, values brought in) can make the MS-01
 *  split propose S5 or S6 for it, or for another study, before a plan, and a study the delivery blinds by its card is
 *  blinded on the Studies list too (round 6: one rule for a study's values, `BlindedSources.withholds`). Round 4 read the
 *  client's files again after a study's confirmation only when a product's profile was chosen, so the template's sheets
 *  of a study the split had just blinded stayed readable on the page. The blinding's one rule follows it
 *  (`followBlinding`), from the moment the inputs that show it were read in: what was read since holds the change, and
 *  a change the delivery's rows showed first (its following read these inputs again) is not read twice. */
export function blindingChanged(client: QueryClient, projectId: string): Promise<void> {
  return followBlinding(client, projectId, readMoment(key(INPUTS, projectId)) ?? moment());
}
