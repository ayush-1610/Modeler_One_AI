// What a change on Inputs makes stale, by the kind of change (final review OWN-7, CODE-4; plan 2026-11-14 §2.1 "fewer
// refetches"): said once here, so every place that makes the same change reads the same things again, and nothing else.
// A change answered with what it changed has that answer written into the page's cache (a choice answers the inputs, a
// dataset's decision the evidence, the sheet form its groups); a read named here is read again where it is shown and
// marked stale elsewhere (read when next shown). The step bar, drawn on the server, follows the readiness: the workspace
// draws it again when the readiness the inputs answer with changes (`InputsWorkspace`), whatever changed it. A decision
// on the delivery is written by `components/delivery/writes.ts`.

import type { QueryClient } from "@tanstack/react-query";

import type { Schema } from "@/lib/api";
import type { After, Read } from "@/lib/hooks";

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

/** A model input changed (a value proposed, decided, corrected, chosen or taken from elsewhere; a dataset's study or its
 *  overlay): the inputs, assembled again with it (their rows, to-do and readiness), the evidence and its datasets, and
 *  what the person's other projects offer that this one does not hold yet. */
export const MODEL: After = { reads: [INPUTS, EVIDENCE, REUSE] };

/** A change answered with the inputs page (a choice, the inputs assembled, the identity proposed): written; the evidence
 *  and the offers are read again (a choice leaves both as they were, but the identity proposed is a value). */
export function inputsAfter(projectId: string, reads: readonly Read[] = [EVIDENCE, REUSE]): After<InputsPage> {
  return { write: (page, client) => client.setQueryData(key(INPUTS, projectId), page), reads };
}

/** A dataset kept or left out (`datasets/{id}:decide`, answered with the evidence page, written): the inputs, and the
 *  sheet form's groups, which say which of their datasets are in the model. A delivery subject that names the dataset (one
 *  its signature loaded, or one of its source the sheet form read) says it too: the delivery page and that card are read
 *  again, only then. */
export function datasetAfter(projectId: string, dataset: string): After<EvidencePage> {
  return {
    write: (page, client) => {
      client.setQueryData(key(EVIDENCE, projectId), page);
      const delivery = client.getQueryData<Schema<"DeliveryPage">>(key(DELIVERY, projectId));
      readSubjects(client, projectId, (delivery?.subjects ?? []).filter((s) => [
        ...s.loaded_elsewhere, ...s.proposed_elsewhere, ...(s.confirmation?.landed_datasets ?? [])].includes(dataset)));
    },
    reads: [INPUTS, REUSE, CLIENT_REVIEW],
  };
}

/** A file's values or datasets proposed in the evidence (an access request fulfilled, answered with the evidence page). */
export function evidenceAfter(projectId: string): After<EvidencePage> {
  return { write: (page, client) => client.setQueryData(key(EVIDENCE, projectId), page), reads: [INPUTS, REUSE] };
}

/** A search started (the sources and the literature, or the observed-data agent): its progress is read; what it finds
 *  is read when it finishes (the workspace reads the inputs again then). */
export const SEARCH: After = { reads: [LITERATURE] };

/** Files arrived (uploaded, the library's documents read for data, read again, filed under another area, a sheet
 *  classified): the client's files, their reading, the delivery that reads them (read again, it says it is reading, and
 *  the page follows the reading to its end) and the documents; the sheet form's groups follow what the files hold. */
export const FILES: After = { reads: [CLIENT_DATA, CLIENT_REVIEW, DELIVERY, READING, DOCUMENTS] };

/** A sheet read with the sheet form and saved (`client-data/{sid}:map`): the file says which of its sheets are read, the
 *  sheet form has its group to confirm (one more in the inputs' to-do), and the delivery joins it to its subjects. */
export const SHEET: After = { reads: [CLIENT_DATA, CLIENT_REVIEW, INPUTS, DELIVERY] };

/** The AI reading asked for again: the reading queue and the files it reads. */
export const READ_AGAIN: After = { reads: [READING, CLIENT_DATA] };

/** An AI reading finished (not a decision: the queue says so): what it read is in the files, the sheet form and the
 *  evidence, so those, the inputs, the delivery and the documents are read again. */
export const READ_DONE: After = { reads: [CLIENT_DATA, CLIENT_REVIEW, INPUTS, EVIDENCE, DELIVERY, DOCUMENTS] };

/** A figure digitized into a dataset (`datasets:digitize`): a model input (the dataset), and the figures of its document
 *  say which are digitized. */
export const DIGITIZED: After = { reads: [...MODEL.reads!, `${P}/documents/{sha256}/figures`] };

/** A dissolution profile proposed as a product's release (`dissolution/{id}:propose`): its profile says so, and the
 *  product's release values are proposed in the evidence. */
export const RELEASE: After = { reads: [CLIENT_DATA, INPUTS, EVIDENCE, REUSE] };

/** A brief's list changed (its products, its populations): the brief; the data plan, the client data's plan and the inputs
 *  follow it; Start's step (drawn on the server) says what the brief still needs. */
export const BRIEF_CHANGED: After = { reads: [BRIEF, INPUTS, CLIENT_DATA], server: true };

const writeReview = (projectId: string) => (page: ReviewPage, client: QueryClient) => client.setQueryData(key(CLIENT_REVIEW, projectId), page);

/** A selection made in a sheet form's group, or one changed again, before it is confirmed (answered with the groups,
 *  written): the inputs' to-do says how many items of the group are still open. */
export function reviewAfter(projectId: string): After<ReviewPage> {
  return { write: writeReview(projectId), reads: [INPUTS] };
}

/** A sheet read into the sheet form (`client-review:finish`, answered with the groups, written): its group is one more
 *  to confirm in the inputs' to-do, and the delivery joins the groups of a source it reads to its subjects. */
export function sheetReadAfter(projectId: string): After<ReviewPage> {
  return { write: writeReview(projectId), reads: [INPUTS, DELIVERY] };
}

/** A sheet form's group confirmed (answered with the groups, written): what it holds is in the model now, so the inputs,
 *  the evidence and the client data are read again, and the delivery where one of its subjects reads the same source
 *  (the group is one of a subject's `legacy_groups`: its card says what of its source is in the model). */
export function confirmAfter(projectId: string, group: string): After<ReviewPage> {
  return {
    write: (page, client) => {
      writeReview(projectId)(page, client);
      const delivery = client.getQueryData<Schema<"DeliveryPage">>(key(DELIVERY, projectId));
      readSubjects(client, projectId, (delivery?.subjects ?? []).filter((s) => s.legacy_groups.includes(group)));
    },
    reads: [INPUTS, EVIDENCE, CLIENT_DATA],
  };
}

/** The delivery page and the cards of `subjects` read again (none: nothing is read). */
function readSubjects(client: QueryClient, projectId: string, subjects: Schema<"DeliverySubjectRow">[]) {
  if (!subjects.length) return;
  void client.invalidateQueries({ queryKey: key(DELIVERY, projectId), exact: true });
  for (const s of subjects) {
    void client.invalidateQueries({ queryKey: [CARD, { project_id: projectId, type: s.subject_type, subject: s.subject }, {}], exact: true });
  }
}
