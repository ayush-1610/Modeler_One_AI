// One list of work for Inputs (plan docs/plans/2026-11-14-inputs-task-first.md §2 rule 1, slice 2; the design text's
// "One work model"). Pure functions, no React: from the /inputs page, the client review (the sheet form) and the
// delivery they build every open item once, with its status word, its area, where it is settled and why it cannot be
// acted on yet; every count on the page (the status line, the area bar, each area's head, To do, each file's "still
// needs you") is counted from that one list, so the numbers agree everywhere.
//
// The join of a delivery subject and a sheet-form group is conservative (plan §2.1): only the group ids the API names on
// the subject (`DeliverySubjectRow.legacy_groups`) or the same kind with the exact normalised label ("Study 230-23" and
// "230-23"). A sheet-form study whose name only starts with a delivery study's (230-23-REF beside 230-23) is never
// merged: it is asked, "Same study as 230-23?", where its file's values are linked. Two delivery subjects are never
// merged, and nothing is joined across kinds.

import type { Schema } from "./api";
import {
  AREA_NAME, type FormulationWay, STATUS_WORD, type Status, type Tab, UNREADABLE, askAt, checkFix, checkLabel, factText, formulationParts,
  formulationWays, individualNeeds, layoutOrigin, placeText, plural,
  tableKindText, todoLabel, whenText, whereIs,
} from "./words";

type DeliveryPage = Schema<"DeliveryPage">;
type DeliveryFile = Schema<"DeliveryFile">;
type SubjectRow = Schema<"DeliverySubjectRow">;
type ReviewPage = Schema<"ClientReviewPage">;
type ReviewGroup = Schema<"ReviewGroup">;
type ReviewItem = Schema<"ReviewItem">;

/** A line of what the client is asked for (the delivery's `request`, and the formulation item's `ask`). */
export type RequestLike = { req_id: string; what: string; why: string; required: boolean; product?: string | null };
/** An open item of the /inputs to-do (components/inputs/InputsTodo.tsx `TodoItem`), as far as the work model reads it;
 *  the formulation item carries what gives a tablet study its formulation as the project stands (`way`) and what the client
 *  is asked for each study whose way offers the client (`ask`: rounds 4 and 5, "add a product" and "add a product's
 *  dissolution data"). */
export type TodoLike = {
  kind: string; target: string; message: string; tab?: string; dataset_id?: string | null; details?: string[];
  way?: FormulationWay | null; ask?: RequestLike[];
};
/** The /inputs page, as far as the work model reads it. */
export type InputsLike = {
  todo: TodoLike[];
  compound: { id: string; state: string; tab: string }[];
  studies: { study_id: string; excluded: string | null; blinded: boolean; dataset_id?: string | null }[];
  readiness: { content: { ready: boolean; checks: { check: string; ok: boolean; detail: string[] }[] } | null } | null;
};
/** A client file (GET /client-data), as far as the work model reads it. */
export type FileLike = { id: string; file: string; sha256: string };
/** A delivery subject's card (GET /delivery/subjects/{type}/{subject}), as far as the work model reads it: what blocks
 *  its signature besides the delivery-wide clean-up (facts not stated, failed checks, disagreements, links between files,
 *  required items, the spot check). */
export type CardLike = {
  blockers: { code: string; detail: string }[];
  gaps: { tag: string; reason: string }[];
  checks: { id: string; code: string; message: string | null; severity: string; overridden: boolean }[];
  conflicts: { id: string; field: string; kind: string; time: number | null; time_unit?: string | null; labels?: Record<string, string> }[];
  links: { id: string; state: string; file: string; study_label: string | null }[];
  requirements: { req_id: string; status: string; disposition: string | null; label: string }[];
  spot_check: { state: string };
  /** a study's simulated individual (D-29): what it still needs once demographics are stated (absent on older cards) */
  individual?: { demographics: Record<string, unknown> | null; needs: string[]; why: string; stated: string[] } | null;
};
export type WorkSources = {
  inputs: InputsLike | null; review: ReviewPage | null; delivery: DeliveryPage | null; files?: FileLike[];
  /** the cards of the delivery's subjects signed on the delivery, by `${subject_type}/${subject}`: a card not read yet is
   *  absent (its row says it is being checked), one that could not be read is null */
  cards?: Record<string, CardLike | null>;
};

/** The groups of To do, in the order a person works through them: each unblocks the ones after it (design "How the person
 *  works through it"). "Next" is the first open item in this order. */
export const GROUPS = ["ready", "layouts", "link", "notread", "missing", "disagree", "confirm", "tidy", "done"] as const;
export type Group = (typeof GROUPS)[number];
export const GROUP_TITLE: Record<Group, string> = {
  ready: "Ready to confirm now", layouts: "Check how tables are read", link: "Link values to a study or product",
  notread: "Numbers not read", missing: "Fill in what's missing", disagree: "Settle disagreements",
  confirm: "Confirm the client's data", tidy: "Blocks nothing", done: "Done",
};
export const GROUP_LEDE: Record<Group, string> = {
  ready: "Nothing is open on these: confirming adds each to the model under your name.",
  layouts: "A table's layout decides which of its numbers become values. Until a person approves it, they can't be confirmed with a signature.",
  link: "These files don't say which study or product their values belong to.",
  notread: "Numbers no table layout picked up. Mark them as not data, or read the table.",
  missing: "No file or source gives these.",
  disagree: "The sources or the client's files disagree, or a value waits for your check.",
  confirm: "Confirming adds a study or product to the model under your name.",
  tidy: "Clean-up that holds up no signature: each row says why. Tidy it for the delivery record.",
  done: "Confirmed and in the model.",
};

/** Where an item is settled: the area, and the element (its data-testid) to bring into view there. `subject` opens a
 *  delivery subject's card; `file` opens a client file's row. */
export type Where = { tab: Tab; anchor?: string; subject?: string; file?: string };

export type WorkItem = {
  /** stable: layout:<mapping id>@<version> · link:<sha> · alias:<group id> · notread:<sha> · todo:<kind>:<target> ·
   *  draft:<item id> · issue:<group id>:<issue id> · confirm:<subject key>; from a delivery subject's card (its key):
   *  fact:<key> · need:<key>:<req id> · check:<key>:<check id> · differ:<key>:<conflict id> ·
   *  same:<key>:<link id> · hold:<key>:<code> */
  id: string;
  group: Group;
  status: Status;
  /** the area it counts in (the area bar's badge) */
  area: Tab;
  /** what it is, with its context ("Link the 79 values of 230-23 Fasting Reference.xlsx to a study or product") */
  label: string;
  detail?: string;
  where: Where;
  /** why a person cannot act on it now (blinded, being read again): left out of Next and of the counts */
  blocked?: string;
  /** why it is not counted although a person could do it now: it holds up no signature (the "Blocks nothing" group, or
   *  only blinded studies), said on its row */
  why?: string;
  /** counted: open (not done), not blocked, and it holds something up */
  open: boolean;
  pipeline: "delivery" | "sheet-form" | "inputs";
  /** the client files it concerns (client file ids; `sha:<sha256>` for a delivery file with no client file) */
  files: string[];
  /** the unified subjects it concerns (their keys) */
  subjects: string[];
  /** values held up: orders the rows of a group */
  weight: number;
  /** the /inputs to-do item, settled inline with its own form (the compound's values) */
  todo?: TodoLike;
  /** the sheet-form issue, settled inline with the card's own form */
  issue?: { group: string; issue: string };
  /** a done item: what is in the model, who confirmed it and when */
  inModel?: string;
  /** a card signed on the delivery: what of the delivery's clean-up holds up its signature (said once per group) */
  gate?: string;
  /** what still needs the owner's decision (final review OWN-2 d): on an item no one can settle on this page, the
   *  decision it waits for; on a card held by the delivery's clean-up, the sentence the gate line adds (`ownerText`) */
  owner?: string;
  /** numbers not read: every study and product read from its file is confirmed with the sheet form (none signed on the
   *  delivery), so a read table of it can be set aside whole as not data and nothing loaded or signed is lost */
  elsewhere?: boolean;
  /** what a file-level item is about: the delivery file's sha256 ("entered" for values a person entered), or the table
   *  layout's id; To do's batch tables (slice 4) build the item's row from it */
  ref?: string;
  /** a disagreement between files: whom it is about ("subject 001, period I"), so a card lists them by subject */
  about?: string;
};

/** Whom values that disagree are about, from the labels they are read with: "arm Test, subject 001, period I" (the
 *  study is the card's own and is not said). */
export function aboutText(labels: Record<string, string> = {}): string {
  return (["arm", "subject", "period", "sequence", "occasion", "vessel"] as const)
    .filter((k) => labels[k]).map((k) => `${k} ${labels[k]}`).join(", ");
}

/** A study, product or compound as one card: a delivery subject, the sheet-form groups joined to it, or a sheet-form
 *  group alone. */
export type Subject = {
  key: string; kind: "study" | "product" | "compound"; label: string;
  /** how it is confirmed: "Confirm and sign" on the delivery, "Confirm" with the sheet form, or not here (a template
   *  subject whose sheet-form card is missing) */
  path: "delivery" | "sheet-form" | "read-only";
  row: SubjectRow | null; groups: ReviewGroup[];
  /** the other names it was read under ("230-23 Fasting" is not one: only the joined groups' own names) */
  aliases: string[];
  area: Tab; files: string[]; blinded: boolean; done: boolean;
};

/** A line of "Ask the client": `at`, its own anchor (the page's `?at=`), apart for each product a study names (round 6). */
export type AskLine = { req: string; what: string; subjects: string[]; required: boolean; why: string; at: string };
/** A model check (the readiness report) in words; `said`: an open check whose gap a To do group already lists (its
 *  rows, or the cards to confirm), so the Model checks group does not say it again (final review OWN-14). */
export type CheckLine = { raw: string; label: string; ok: boolean; detail: string[]; fix: string; said: boolean };
export type Counts = Record<Status, number> & { open: number };
/** What the model holds: `studies` counts a study signed on the delivery once, its arms and its means together;
 *  `datasets`, the study rows the model is built from (one per arm; what the signature's landing says it loaded). */
export type InModel = { studies: number; datasets: number; formulations: number; values: number };

export type WorkModel = {
  items: WorkItem[];
  subjects: Subject[];
  counts: Counts;
  /** open items by the area they count in */
  byArea: Record<Tab, number>;
  /** open items by client file id */
  byFile: Record<string, WorkItem[]>;
  /** a file's own work a person can do now by client file id: the open items and those shown in their group but not
   *  counted (a delivery whose files name no study yet, one that holds up only blinded studies); not the "Blocks nothing"
   *  clean-up */
  fileWork: Record<string, WorkItem[]>;
  next: WorkItem | null;
  ask: AskLine[];
  checks: CheckLine[];
  inModel: InModel;
  /** every model check passes and nothing is open */
  ready: boolean;
  /** delivery cards not read yet: what holds them is not counted until they are */
  checking: number;
};

// --- names and joins ------------------------------------------------------------------------------------------------------

/** A label as the join compares it: case and spacing ignored, a leading "Study"/"Product" dropped. */
export const normLabel = (s: string) => s.trim().toLowerCase().replace(/^(study|product)[\s:]+/, "").replace(/\s+/g, " ");
const KIND_AREA: Record<Subject["kind"], Tab> = { study: "studies", product: "formulations", compound: "compound" };
const KIND_WORD: Record<Subject["kind"], string> = { study: "Study", product: "Product", compound: "Compound" };
const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** A sheet-form group's own name: "230-23" for `study:230-23`, else its title. */
export function groupLabel(g: ReviewGroup): string {
  const prefix = `${g.kind}:`;
  return g.id.startsWith(prefix) ? g.id.slice(prefix.length) : g.title;
}
/** The client files a sheet-form group was read from (by its items' and facts' sources). */
function groupShas(g: ReviewGroup): string[] {
  const out = new Set<string>();
  for (const s of [...g.items.map((i) => i.source), ...g.facts.map((f) => f.source)]) {
    const sha = (s as { doc_sha256?: string | null } | null | undefined)?.doc_sha256;
    if (sha) out.add(sha);
  }
  return [...out];
}

/** One card per study, product and compound: each delivery subject with the sheet-form groups the API names on it or
 *  of the exact same label, then each sheet-form study, product or compound group that joined none. Sheet groups (a sheet
 *  whose product or study is not stated yet) are not subjects. */
export function unifySubjects(delivery: DeliveryPage | null, review: ReviewPage | null, fileOf: (sha: string) => string = (s) => s,
                              blindedStudies: ReadonlySet<string> = new Set()): Subject[] {
  const all = review?.groups ?? [];
  const groups = all.filter((g) => g.kind !== "sheet");
  const taken = new Set<string>();
  const out: Subject[] = [];
  for (const row of delivery?.enabled ? delivery.subjects : []) {
    // the API names the groups of the same source: those holding a dataset of it, and those read from files a person
    // linked to this subject on the delivery (a sheet whose product or study the sheet form asks for included: review
    // OWN-4, INT-9), so the same file is never asked or counted twice
    const named = all.filter((g) => row.legacy_groups.includes(g.id) && !taken.has(g.id));
    const same = groups.filter((g) => !taken.has(g.id) && !named.includes(g) && g.kind === row.subject_type
                                    && normLabel(groupLabel(g)) === normLabel(row.label));
    // the card is known by the group of its own name, else by its own (a joined group of another name never renames it);
    // that group comes first, so its answers are the first suggestions (an arm's sheet says the arm's number of subjects)
    const exact = [...named, ...same].find((g) => g.kind === row.subject_type && normLabel(groupLabel(g)) === normLabel(row.label));
    const joined = exact ? [exact, ...[...named, ...same].filter((g) => g !== exact)] : [...named, ...same];
    joined.forEach((g) => taken.add(g.id));
    const path: Subject["path"] = row.confirm_on === "delivery" ? "delivery" : joined.length ? "sheet-form" : "read-only";
    const c = row.confirmation;
    // signed and loaded on the delivery, or confirmed with the sheet form (whichever is confirmed first is what loads)
    const sheets = joined.length > 0 && joined.every((g) => g.state === "confirmed");
    const done = path === "delivery" ? Boolean(c?.current && c.landed) || sheets : path === "sheet-form" ? sheets : false;
    const files = [...new Set([...row.files, ...joined.flatMap(groupShas)].map(fileOf))];
    out.push({
      key: exact?.id ?? `${row.subject_type}:${row.label}`, kind: row.subject_type, label: row.label, path, row, groups: joined,
      aliases: joined.filter((g) => g.kind !== "sheet").map(groupLabel).filter((l) => normLabel(l) !== normLabel(row.label)),
      area: (exact ?? joined[0]) ? ((exact ?? joined[0]).tab as Tab) : KIND_AREA[row.subject_type], files,
      // blinded by the delivery (its row, or the client review's group of it), or by the project's blinding list
      blinded: row.blinded || joined.some((g) => g.blinded) || (row.subject_type === "study" && blindedStudies.has(normLabel(row.label))), done,
    });
  }
  for (const g of groups.filter((x) => !taken.has(x.id))) {
    const kind = g.kind as Subject["kind"];
    out.push({
      key: g.id, kind, label: groupLabel(g), path: "sheet-form", row: null, groups: [g], aliases: [],
      area: (g.tab as Tab) ?? KIND_AREA[kind], files: groupShas(g).map(fileOf),
      blinded: Boolean(g.blinded) || (kind === "study" && blindedStudies.has(normLabel(groupLabel(g)))), done: g.state === "confirmed",
    });
  }
  return out;
}

/** The delivery study a sheet-form study's name starts with ("230-23-REF" → "230-23"; the longest that fits), if any. */
export function prefixAlias(label: string, rows: SubjectRow[]): SubjectRow | null {
  const mine = normLabel(label);
  const fits = rows.filter((r) => r.subject_type === "study" && mine !== normLabel(r.label)
                               && new RegExp(`^${normLabel(r.label).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[-_ ]`).test(mine));
  return fits.sort((a, b) => b.label.length - a.label.length)[0] ?? null;
}

/** A table layout's place in the delivery's list of layouts (its testid): `delivery-mapping-<id>`, with `-v<version>` for
 *  a later version of the same layout listed beside the first. */
export function layoutAnchor(m: { mapping_id: string; version: number }, all: { mapping_id: string; version: number }[]): string {
  const first = Math.min(...all.filter((x) => x.mapping_id === m.mapping_id).map((x) => x.version), m.version);
  return `delivery-mapping-${m.mapping_id}${m.version === first ? "" : `-v${m.version}`}`;
}

/** A study's, product's or compound's card in its area (plan 2026-11-14 slice 3): `study-card-<key>`, `product-card-<key>`,
 *  `compound-card-<key>`. Every item of a card opens there, whichever reader found the subject. */
export const cardAnchor = (s: Pick<Subject, "kind" | "key">) => `${s.kind}-card-${s.key}`;

/** A table layout's row in To do's queue: `todo-layout-<id>`, `-v<version>` for a later version beside the first. */
export const layoutRowId = (m: { mapping_id: string; version: number }, all: { mapping_id: string; version: number }[]) =>
  layoutAnchor(m, all).replace(/^delivery-mapping-/, "todo-layout-");
/** A file's row in To do's batch tables, by the delivery's id of the file ("entered" for values a person entered). */
export const linkRowId = (fileId: string) => `link-${fileId}`;
export const notReadRowId = (fileId: string) => `notread-${fileId}`;

// --- the work ------------------------------------------------------------------------------------------------------------

/** The items that are a file's own work (counted on its row in Client files). */
const FILE_WORK = /^(layout|link|alias|notread|draft):/;
const DECIDE = new Set(["conflict", "correct", "pka", "review", "formulation", "process", "unit"]);
/** A delivery subject's own items, from its card. */
const CARD_ITEM = /^(fact|need|individual|check|differ|same|hold):/;
/** The data plan's demographics item: a study's individual is chosen with them (D-29). */
const DEMOGRAPHICS_REQ = "REQ-sys.demographics";
/** A card's failed checks counted as another of its rows (a fact not stated, a required item, a disagreement). */
const SETTLED_ELSEWHERE = new Set(["LANDING_FIELD_MISSING", "DOSE_MISSING", "MATRIX_MISSING", "REQUIRED_ITEM_UNDISPOSED", "CONFLICT_OPEN"]);

/** The fact a failed check says the study record needs: LANDING_FIELD_MISSING's "needs n, …", DOSE_MISSING's dose,
 *  MATRIX_MISSING's matrix; null for any other check. One rule for the card's facts form (`FactsForm`) and To do's facts
 *  row, so a fact is asked, and counted, as a fact in both (final review CODE-8 c: To do counted a matrix not stated as a
 *  check to decide while the card asked it as a fact). */
export function checkField(c: { code: string; message?: string | null; field?: string | null }): string | null {
  // the field the API names apart (round 6), else read from the message, as the API wrote it before
  if (c.code === "LANDING_FIELD_MISSING") return c.field ?? /needs (\w+)/.exec(c.message ?? "")?.[1] ?? null;
  return c.code === "DOSE_MISSING" ? "dose" : c.code === "MATRIX_MISSING" ? "matrix" : null;
}
/** A card's blockers counted elsewhere: the delivery-wide clean-up (once, by file), the card's own rows, the spot check
 *  (the signature's first step) and blinding (the row is not counted and says why). */
const CARD_COUNTED = new Set(["SILENT_LOSS", "OUTSIDE_NUMBERS", "UNASSIGNED_VALUES", "SCHEMA_GAP", "CHECK_FAILED", "LINK_UNCONFIRMED",
                              "SPOT_CHECK", "BLINDED"]);
/** The to-do kinds settled inline in To do with their own form (the compound's values: the S0 batch, plan §2.1). */
export const INLINE_TODO = new Set(["missing", "conflict", "correct", "pka", "review"]);

/** Every open item once, with every count read from them. */
export function buildWork(sources: WorkSources): WorkModel {
  const { inputs, review, delivery, files = [] } = sources;
  const on = Boolean(delivery?.enabled);
  const deliveryFiles = on ? delivery!.deliveries.flatMap((d) => d.files) : [];
  const bySha = new Map(files.map((f) => [f.sha256, f] as const));
  const firstOf = new Map<string, DeliveryFile>();
  for (const f of deliveryFiles) if (!f.repeat && !firstOf.has(f.sha256)) firstOf.set(f.sha256, f);
  for (const f of deliveryFiles) if (!firstOf.has(f.sha256)) firstOf.set(f.sha256, f);
  const fileOf = (sha: string) => bySha.get(sha)?.id ?? firstOf.get(sha)?.legacy_sid ?? `sha:${sha}`;
  const nameOf = (sha: string) => bySha.get(sha)?.file ?? firstOf.get(sha)?.name ?? "a file";
  const nameById = new Map<string, string>([...files.map((f) => [f.id, f.file] as const),
                                            ...[...firstOf.values()].map((f) => [f.legacy_sid ?? `sha:${f.sha256}`, f.name] as const)]);
  /** The files a card was read from, as its row names them: "from four-studies.xlsx", "from a.xlsx, b.xlsx and 3 more". */
  const fromFiles = (ids: string[]) => {
    const names = [...new Set(ids.map((id) => nameById.get(id)).filter((n): n is string => Boolean(n)))];
    return names.length ? `from ${names.slice(0, 2).join(", ")}${names.length > 2 ? ` and ${names.length - 2} more` : ""}` : "";
  };
  const blindedStudies = new Set((inputs?.studies ?? []).filter((s) => s.blinded).map((s) => normLabel(s.study_id)));

  const subjects = unifySubjects(delivery, review, fileOf, blindedStudies);
  const items: WorkItem[] = [];
  const add = (item: Omit<WorkItem, "open">) => items.push({ ...item, open: false });

  // what of a delivery's clean-up holds up (SILENT_LOSS, OUTSIDE_NUMBERS and UNASSIGNED_VALUES gate every confirmation
  // of the delivery's subjects, contracts §11.10): its subjects signed on the delivery and not yet signed. When none is,
  // the item is not counted and its row says why: only blinded studies wait (it counts once the plan is signed), or its
  // files name no study or product yet (their values reach the model only once linked): both stay in their group, shown
  // and not counted; every one is confirmed already, or the delivery's subjects are all confirmed with the sheet form
  // (both "Blocks nothing")
  const hold = (deliveryIds: string[]): { group?: "tidy"; subjects: string[]; why?: string } => {
    const mine = subjects.filter((s) => s.path === "delivery" && s.row!.deliveries.some((d) => deliveryIds.includes(d)));
    const held = mine.filter((s) => !s.done && !s.blinded);
    if (held.length) return { subjects: held.map((s) => s.key) };
    const blinded = mine.filter((s) => !s.done && s.blinded);
    if (blinded.length) {
      const which = `${blinded.length === 1 ? "a blinded study" : "blinded studies"} (${blinded.map((s) => s.label).join(", ")})`;
      return { subjects: [], why: `It holds up only ${which}: it counts once the plan is signed and the study can be confirmed.` };
    }
    if (mine.length) return { group: "tidy", subjects: [], why: "Every study and product it held up is confirmed." };
    // a delivery whose files name no study or product yet (its values linked to none): nothing is held up until they are,
    // but nothing of it reaches the model either, so its work stays in its group, in view (not under "Blocks nothing")
    if (!subjects.some((s) => s.row?.deliveries.some((d) => deliveryIds.includes(d)))) {
      return { subjects: [], why: "Its files name no study or product yet: it holds up nothing until their values are linked to one." };
    }
    return { group: "tidy", subjects: [], why: "Its studies and products are confirmed with the sheet form: it holds up nothing." };
  };

  // 1 · table layouts to check (one row per version: two versions of one layout are two decisions)
  for (const m of on ? delivery!.mappings.filter((x) => x.status === "proposed") : []) {
    const shas = [...new Set(m.used_in.map((u) => u.file_sha256))];
    const held = hold(shas.map((s) => firstOf.get(s)?.delivery ?? ""));
    const first = m.used_in[0];
    const where = first ? `${first.file} (${placeText(first.where)})` : "no file uses it now";
    const more = shas.length > 1 ? ` and ${plural(shas.length - 1, "more file")}` : "";
    add({
      id: `layout:${m.mapping_id}@${m.version}`, group: held.group ?? "layouts", status: "to_decide", area: "files",
      label: `${capital(tableKindText(m.kind))} · ${where}${more}`, detail: `${layoutOrigin(m.origin)} · version ${m.version}`,
      where: { tab: "todo", anchor: layoutRowId(m, delivery!.mappings) }, pipeline: "delivery",
      blocked: m.waiting ? "Being read again: it can be checked once the reading ends." : undefined, why: held.why,
      files: shas.map(fileOf), subjects: held.subjects, weight: m.used_in.length, ref: m.mapping_id,
    });
  }

  // 2 · values to link to a study or product, one row per file; a file the sheet form read under a name that only starts
  // with a delivery study's ("230-23-REF" beside "230-23") asks "Same study as 230-23?" in its place (no silent merge),
  // counted in Client files with the file's other work, and linked in To do's link table (slice 4), where Yes fills its
  // row with that study and the suggested arm
  const unassigned = on ? delivery!.unassigned : [];
  const sheetNames = new Map<string, Subject>();
  for (const s of subjects) if (!s.row && s.kind === "study") for (const g of s.groups) for (const sha of groupShas(g)) sheetNames.set(sha, s);
  const studyRows = on ? delivery!.subjects.filter((r) => r.subject_type === "study") : [];
  const linkShas = [...new Set(unassigned.map((v) => v.file_sha256 ?? "entered"))];
  for (const sha of linkShas) {
    const values = unassigned.filter((v) => (v.file_sha256 ?? "entered") === sha);
    const name = sha === "entered" ? "values entered by a person" : nameOf(sha);
    const held = hold([...new Set(values.map((v) => v.delivery))]);
    const read = sheetNames.get(sha);
    const alias = read ? prefixAlias(read.label, studyRows) : null;
    const base = {
      group: held.group ?? "link" as Group, status: "to_decide" as Status, area: "files" as Tab, pipeline: "delivery" as const,
      where: { tab: "todo" as Tab, anchor: linkRowId(sha === "entered" ? "entered" : firstOf.get(sha)?.file_id ?? `sha-${sha.slice(0, 12)}`) },
      why: held.why, files: sha === "entered" ? [] : [fileOf(sha)], weight: values.length, ref: sha,
    };
    if (alias && read) {
      add({ ...base, id: `alias:${read.key}`, subjects: [read.key, ...held.subjects],
            label: `Same study as ${alias.label}? ${read.label} · ${name}`,
            detail: `The sheet form read this file as ${read.label}; its ${linkCount(values)} are not linked to a study in the delivery. If it is ${alias.label}, link them to it with their arm.` });
    } else {
      add({ ...base, id: `link:${sha}`, subjects: held.subjects,
            label: `Link the ${linkCount(values)} of ${name} to a study or product`,
            detail: read ? `The sheet form read it as ${KIND_WORD[read.kind]} ${read.label}.` : undefined });
    }
  }
  // a sheet-form alias whose file the person has linked to the study it starts with: settled
  for (const s of subjects.filter((x) => !x.row && x.kind === "study")) {
    const alias = prefixAlias(s.label, studyRows);
    const shas = s.groups.flatMap(groupShas);
    if (!alias || items.some((i) => i.id === `alias:${s.key}`) || !shas.some((sha) => alias.files.includes(sha))) continue;
    // settled: it opens the card of the study it was linked to, in its area
    const into = subjects.find((x) => x.row === alias);
    add({ id: `alias:${s.key}`, group: "done", status: "done", area: "files", pipeline: "delivery", subjects: [s.key],
          label: `Same study as ${alias.label}? ${s.label}`, inModel: `Its file is linked to ${alias.label} in the delivery.`,
          where: { tab: into?.area ?? "studies", anchor: into ? cardAnchor(into) : undefined, subject: `${alias.subject_type}/${alias.subject}` },
          files: shas.map(fileOf), weight: 0 });
  }

  // 3 · numbers not read, one row per file: in tables no layout picked up, loose ones outside every table, unread tables
  for (const f of firstOf.values()) {
    const c = f.coverage;
    const loose = f.outside.filter((o) => o.counted).length;
    const parts = [c?.silent_loss ? `${plural(c.silent_loss, "number")} in tables not read` : "",
                   loose ? plural(loose, "loose number") : "", c?.regions_unread ? plural(c.regions_unread, "table or text", "tables or texts") + " not read" : ""]
      .filter(Boolean);
    const failed = f.state === "failed" || f.state === "unreadable" || f.state === "unsupported";
    if (!parts.length && !failed) continue;
    const held = hold([f.delivery]);
    // the studies and products read from this file, each confirmed with the sheet form and none signed on the delivery:
    // a read table of it can be set aside whole, losing nothing that is loaded or signed (review OWN-2 b)
    const readFrom = subjects.filter((s) => s.row?.files.includes(f.sha256));
    const elsewhere = readFrom.length > 0 && readFrom.every((s) => s.done && !s.row?.confirmation?.current);
    // all that is left is numbers in read tables that no layout can read (not plain numbers): only setting single cells
    // aside would clear them, which waits for the owner's decision (plan §3 API 3), so Next and the counts skip it, and
    // its row says why (review OWN-2 d, plan §2.2.5 extended)
    const silent = f.regions.filter((r) => r.state === "mapped" && r.silent > 0);
    const stuck = !failed && !loose && !c?.regions_unread && !elsewhere && silent.length > 0 && silent.every(noLayoutReads);
    const odd = [...new Set(silent.flatMap((r) => r.silent_cells ?? []).filter((x) => UNREADABLE.has(x.why) && x.text !== null).map((x) => x.text!))];
    add({
      id: `notread:${f.sha256}`, group: held.group ?? "notread", status: "to_decide", area: "files",
      label: `${f.name}: ${failed ? `could not be read${f.reason ? ` (${f.reason})` : ""}` : parts.join(" · ")}`,
      where: { tab: "todo", anchor: notReadRowId(f.file_id) }, pipeline: "delivery",
      blocked: f.state === "unsupported" ? "Not a kind of file the reader takes."
        : stuck ? `${odd.length === 1 ? `“${odd[0]}” is not a plain number` : odd.length ? `${odd.slice(0, 3).map((t) => `“${t}”`).join(", ")} are not plain numbers`
          : "Its numbers are not plain numbers"}, so no table layout reads ${odd.length === 1 ? "it" : "them"}. Setting a single cell aside as`
          + " not data waits for the owner's decision; until then, correct the file and send it again." : undefined,
      owner: stuck ? OWNER_CELLS : undefined, why: held.why, elsewhere: elsewhere || undefined,
      files: [fileOf(f.sha256)], subjects: held.subjects, weight: (c?.silent_loss ?? 0) + loose, ref: f.sha256,
    });
  }

  // 4–5 · the /inputs to-do: what no source gives (missing), and the choices on the compound's values
  const toConfirmStudies = subjects.some((s) => s.kind === "study" && !s.done);
  for (const t of inputs?.todo ?? []) {
    if (t.kind === "confirm") continue;                      // a group to confirm is its subject's card, below
    if (t.kind === "check") continue;                        // the software build is a model check
    if (t.kind === "datasets" && toConfirmStudies) continue; // settled by confirming a study's data, below
    const decide = DECIDE.has(t.kind);
    const tab = (t.tab ?? "compound") as Tab;
    const blinded = (t.kind === "regimen" || t.kind === "demographics") && blindedStudies.has(normLabel(t.target));
    // a tablet study's missing formulation (final review OWN-10, round 4): what gives it one as the project stands (`way`,
    // the step bar's too) says where the item opens: the card of the first product whose dissolution profile can give the
    // release (or whose dissolution data are to add), at its release; it is that card's own work when it is the only one
    const way = t.kind === "formulation" ? formulationWays(t.way) : null;
    const lever = t.kind === "formulation" && (t.way?.way === "use_profile" || t.way?.way === "add_dissolution") ? t.way : null;
    const product = lever ? productFor(subjects, lever.products[0]) : null;
    add({
      id: `todo:${t.kind}:${t.target}`, group: decide ? "disagree" : "missing", status: decide ? "to_decide" : "missing", area: tab,
      label: todoLabel(t.kind, t.target), pipeline: "inputs",
      where: product ? { tab: product.area, anchor: releaseAnchor(product), subject: product.row ? `${product.row.subject_type}/${product.row.subject}` : undefined }
        : { tab, anchor: `todo-${t.kind}-${t.target}` },
      detail: way?.ways.length ? way.fix : undefined,
      blocked: blinded ? blindedText(subjects.find((s) => s.kind === "study" && normLabel(s.label) === normLabel(t.target)) ?? { row: null, groups: [] },
                                     ": its facts are set afterwards.") : undefined,
      files: [], subjects: product && lever!.products.length === 1 ? [product.key] : [], weight: 1, todo: t,
    });
  }

  // the sheet form's own open items: the issues (settled with the card's own form) and the sheets that do not say a fact
  // (filled in on the card). A subject signed on the delivery that the sheet form also read keeps its issues: it can be
  // confirmed with the sheet form instead (plan §2.2.1). Its sheets' missing facts are not asked again there: the
  // delivery's own facts row asks for them, once (slice 3 after its review); the sheet form asks them inside its path,
  // when the person chooses it ("The sheet form has n things first")
  for (const s of subjects.filter((x) => x.groups.length > 0 && !x.done)) {
    const also = s.path === "delivery" ? "To confirm it with the sheet form instead of signing it on the delivery." : undefined;
    for (const g of s.groups.filter((x) => x.state === "to_confirm")) {
      for (const issue of g.issues.filter((i) => i.selected === null && i.answered === null)) {
        add({ id: `issue:${g.id}:${issue.id}`, group: "disagree", status: "to_decide", area: g.tab as Tab, pipeline: "sheet-form",
              label: `${KIND_WORD[s.kind]} ${s.label}: ${issue.text}`, where: { tab: g.tab as Tab, anchor: `issue-${issue.id}` },
              blocked: s.blinded ? blindedText(s, ".") : undefined, detail: also,
              files: s.files, subjects: [s.key], weight: 1, issue: { group: g.id, issue: issue.id } });
      }
      if (s.path === "delivery") continue;
      for (const i of g.items.filter((x) => x.kind === "draft")) draftItem(add, g, i, `${KIND_WORD[s.kind]} ${s.label}`, [s.key], s.blinded ? blindedText(s, ".") : undefined, fileOf, also);
    }
  }
  // a sheet whose study or product is not stated yet: its card asks for it, and its data join that card once read. A
  // sheet whose file a person linked to a study or product on the delivery is that card's (joined above): not asked again
  const joinedSheets = new Set(subjects.flatMap((s) => s.groups.map((g) => g.id)));
  for (const g of (review?.groups ?? []).filter((x) => x.kind === "sheet" && x.state === "to_confirm" && !joinedSheets.has(x.id))) {
    for (const i of g.items.filter((x) => x.kind === "draft")) draftItem(add, g, i, g.title, [], undefined, fileOf);
  }

  // what holds up a delivery subject's signature on its own card (plan §2 rule 1, "each card's blockers"; §2.1: rows
  // that open the card): the facts no file states (a gap, or a check that names the fact the study record needs: one
  // row per fact), the required items no one has settled, failed checks, values two files give differently, links
  // between files, and any other reason the card gives. The delivery-wide clean-up is counted once, above, and the spot
  // check is the first step of the signature (its confirm row says so). Until a card is read, its row says it is being checked.
  const cards = sources.cards ?? {};
  const layoutIds = on ? delivery!.mappings.filter((m) => m.status === "proposed").map((m) => m.mapping_id) : [];
  let checking = 0;
  for (const s of subjects.filter((x) => x.path === "delivery" && !x.done && !x.blinded)) {
    const ref = `${s.row!.subject_type}/${s.row!.subject}`;
    if (!(ref in cards)) { checking += 1; continue; }
    const card = cards[ref];
    if (!card) continue;
    const name = `${KIND_WORD[s.kind]} ${s.label}`;
    const base = { area: s.area, pipeline: "delivery" as const, files: s.files, subjects: [s.key], weight: 1 };
    // on the card in its area (slice 3; until then the card opened in Client files)
    const at = (anchor: string): Where => ({ tab: s.area, anchor, subject: ref });
    const own = s.row!.subject;
    const failing = card.checks.filter((c) => c.severity === "fail" && !c.overridden);
    const facts = new Map<string, string>();
    for (const g of card.gaps) if (!facts.has(g.tag)) facts.set(g.tag, cardPlace("gap", own, g.tag));
    for (const c of failing) {
      const field = checkField(c);
      if (field && !facts.has(field)) facts.set(field, `delivery-check-${c.id}`);
    }
    // the facts on one row, as a sheet's facts are ("not stated: the route, the number of subjects"): each is entered on the card
    if (facts.size) {
      add({ ...base, id: `fact:${s.key}`, group: "missing", status: "missing",
            label: `${name} · not stated: ${[...facts.keys()].map(factText).join(", ")}`, where: at([...facts.values()][0]) });
    }
    for (const r of card.requirements.filter((x) => x.status === "missing" && !x.disposition)) {
      add({ ...base, id: `need:${s.key}:${r.req_id}`, group: "missing", status: "missing",
            label: `${name} · not in the files: ${r.label.replace(` — ${s.label}`, "")}`,
            detail: "Record that it is asked of the client, taken from the literature or not needed.", where: at(cardPlace("requirement", own, r.req_id)) });
    }
    // the study's individual (D-29), once its demographics are stated: the PK-Sim population and the sex a person
    // chooses. It comes before the spot check in the order of work, since choosing it enters facts the spot check is
    // drawn from (a spot check recorded before it is drawn again). Its demographics still to give are the row above.
    const individual = card.individual;
    // (the card shows it on the data plan's demographics row once that row is settled; before, that row asks for both)
    const demographicsSettled = card.requirements.some((r) => r.req_id === DEMOGRAPHICS_REQ && !(r.status === "missing" && !r.disposition));
    if (individual && !individual.demographics && individual.stated.length > 0 && demographicsSettled) {
      add({ ...base, id: `individual:${s.key}`, group: "missing", status: "missing", label: `${name} · choose the study's individual`,
            // where the spot check is drawn already, choosing it draws the spot check again: said, not found later
            detail: `${capital(individualNeeds(individual.needs, individual.why))}${["none", "stale"].includes(card.spot_check.state)
              ? ", before the spot check." : "; the spot check is then drawn again."}`,
            where: at(`delivery-individual-${s.row!.subject}`) });
    }
    for (const c of failing) {
      if (SETTLED_ELSEWHERE.has(c.code) || (c.code === "MAPPING_NOT_APPROVED" && layoutIds.some((id) => c.message?.includes(id)))) continue;
      add({ ...base, id: `check:${s.key}:${c.id}`, group: "disagree", status: "to_decide", label: `${name}: ${c.message ?? "a check failed"}`,
            detail: "A check failed: correct the values, or say why it holds as it is.", where: at(`delivery-check-${c.id}`) });
    }
    // each disagreement says whom it is about and when, with the time's unit ("concentration at 1 h, subject 001,
    // period I"; review INT-10): sixty rows of "at 1" could not be told apart
    for (const x of card.conflicts) {
      const about = aboutText(x.labels);
      const when = x.time !== null ? ` at ${x.time}${x.time_unit ? ` ${x.time_unit}` : ""}` : "";
      add({ ...base, id: `differ:${s.key}:${x.id}`, group: "disagree", status: "to_decide", about: about || undefined,
            label: `${name}: the files give different ${x.kind === "unit" ? "units" : "values"} for ${x.field.replace(/_/g, " ")}${when}${about ? `, ${about}` : ""}`,
            where: at(cardPlace("conflict", own, x.id)) });
    }
    for (const l of card.links.filter((x) => x.state !== "refused")) {
      add({ ...base, id: `same:${s.key}:${l.id}`, group: "disagree", status: "to_decide", label: `${name}: is ${l.file} about the same study?`,
            detail: `It names ${l.study_label ? `study ${l.study_label}` : "a study"} in its text.`, where: at(cardPlace("link", own, l.id.replace(/[^A-Za-z0-9-]/g, "-"))) });
    }
    for (const b of card.blockers.filter((x) => !CARD_COUNTED.has(x.code))) {
      add({ ...base, id: `hold:${s.key}:${b.code}`, group: "disagree", status: "to_decide", label: `${name}: ${b.detail}`,
            where: at(`delivery-blockers-${s.row!.subject}`) });
    }
  }

  // 0, 6 · the client's data to confirm, one row per card; done ones say what is in the model
  const ownOf = (s: Subject) => items.filter((i) => i.subjects.includes(s.key) && CARD_ITEM.test(i.id));
  const heldBy = (s: Subject) => (s.path !== "delivery" ? []
    : items.filter((i) => i.subjects.includes(s.key) && (i.group === "layouts" || i.group === "link" || i.group === "notread")));
  for (const s of subjects) {
    const name = `${KIND_WORD[s.kind]} ${s.label}`;
    const aliases = s.aliases.length ? ` · also read by the sheet form as ${s.aliases.join(", ")}` : "";
    const g = s.groups[0];
    const where: Where = s.path === "sheet-form" && g ? { tab: g.tab as Tab, anchor: `group-${g.id}` }
      : { tab: s.area, anchor: cardAnchor(s), subject: `${s.row!.subject_type}/${s.row!.subject}` };
    const base = { area: s.area, where, pipeline: (s.path === "delivery" ? "delivery" : "sheet-form") as WorkItem["pipeline"],
                   files: s.files, subjects: [s.key], weight: s.row?.values ?? s.groups.reduce((n, x) => n + x.items.length, 0) };
    if (s.done) {
      // a product says what of it is in the model: its dissolution kept, and its release set or not (OWN-10)
      const release = s.kind === "product" ? releaseOf(s, inputs).name : null;
      const what = s.kind !== "product" ? "" : release ? ` Its release is the formulation “${release}”.`
        : " Its dissolution profile is kept; the formulation's release is not set yet.";
      add({ ...base, id: `confirm:${s.key}`, group: "done", status: "done", label: name, inModel: `${inModelText(s)}${what}` });
      continue;
    }
    const c = s.row?.confirmation;
    if (s.path === "read-only") {
      add({ ...base, id: `confirm:${s.key}`, group: "confirm", status: "to_confirm", label: name,
            detail: "A filled client-data template: it is confirmed on its card in its area, which is not available yet.",
            blocked: "Its card is not available yet: read the file again from Client files." });
      continue;
    }
    const sheetOpen = s.groups.reduce((n, x) => n + (x.state === "to_confirm" ? x.open : 0), 0);
    const from = fromFiles(s.files);
    if (s.path === "sheet-form") {
      add({ ...base, id: `confirm:${s.key}`, group: sheetOpen ? "confirm" : "ready", status: "to_confirm", label: name,
            detail: [from, sheetOpen ? `${plural(sheetOpen, "thing")} first, on its card` : ""].filter(Boolean).join(" · ") + aliases || undefined,
            blocked: s.blinded ? blindedText(s, ": it is confirmed afterwards.") : undefined });
      continue;
    }
    // signed on the delivery: what holds it, in the order it is done (its own items and the clean-up, then the spot
    // check and the signature); "once the delivery is cleaned up" only where the clean-up is all that holds it
    const ref = `${s.row!.subject_type}/${s.row!.subject}`;
    const card = cards[ref];
    const own = ownOf(s);
    const held = heldBy(s);
    const step = c && !c.current ? "changed since it was signed: confirm again" : c && !c.landed ? "signed; the loading is not finished"
      : !(ref in cards) ? "checking what holds it…" : card === null ? "its card could not be read: open it to see what holds it"
        : (() => {
          const first = [own.length ? `${plural(own.length, "item")} on its card (${statusSummary(own)})` : "",
                         held.length ? "the delivery clean-up" : ""].filter(Boolean);
          const spot = card!.spot_check.state !== "complete";
          return first.length ? `first ${first.join(" and ")}; then ${spot ? "the spot check and " : ""}the signature`
            : `${spot ? "the spot check, then " : ""}confirm and sign on its card`;
        })();
    const sheet = s.groups.length ? ` · or confirm it with the sheet form on ${AREA_NAME[s.area]}`
      + `${sheetOpen ? ` (${plural(sheetOpen, "thing")} first)` : ""}: whichever is confirmed first is what loads` : "";
    const ready = Boolean(card) && !own.length && !held.length && !c;
    add({ ...base, id: `confirm:${s.key}`, group: ready ? "ready" : "confirm", status: "to_confirm", label: name,
          detail: [from, step].filter(Boolean).join(" · ") + sheet + aliases, gate: held.length ? gateText(held) : undefined,
          owner: held.length ? ownerText(held) : undefined,
          blocked: s.blinded ? blindedText(s, ": it is confirmed afterwards.") : undefined });
  }

  // counted: open, not blocked, and holding up a signature a person can make now
  for (const i of items) i.open = i.status !== "done" && !i.blocked && !i.why && i.group !== "tidy";
  const order = (i: WorkItem) => GROUPS.indexOf(i.group);
  items.sort((a, b) => order(a) - order(b) || b.weight - a.weight);

  const open = items.filter((i) => i.open);
  const counts: Counts = { missing: 0, to_confirm: 0, to_decide: 0, done: 0, open: open.length };
  for (const i of open) counts[i.status] += 1;
  counts.done = items.filter((i) => i.status === "done").length;
  const byArea = Object.fromEntries((Object.keys(AREA_NAME) as Tab[]).map((t) => [t, 0])) as Record<Tab, number>;
  for (const i of open) byArea[i.area] += 1;
  byArea.todo = open.length;
  // a file's own work (its layouts, links, numbers not read, the facts its sheets do not say), not its subjects' cards
  const byFile: Record<string, WorkItem[]> = {};
  for (const i of open.filter((x) => FILE_WORK.test(x.id))) for (const f of i.files) (byFile[f] ??= []).push(i);
  const fileWork: Record<string, WorkItem[]> = {};
  for (const i of items.filter((x) => FILE_WORK.test(x.id) && x.status !== "done" && !x.blocked && x.group !== "tidy")) {
    for (const f of i.files) (fileWork[f] ??= []).push(i);
  }

  // an open check whose gap the /inputs to-do lists as rows of To do (a row that is that gap), or, for the observed data,
  // the studies still to confirm: said there, not again among the model checks
  const listed = items.filter((i) => i.status !== "done" && i.todo).map((i) => i.todo as TodoLike);
  const said = (raw: string) => listed.some((t) => CHECK_TODO[checkKeyOf(raw)]?.(t) ?? false)
    || (checkKeyOf(raw) === "observed data to judge on" && toConfirmStudies);
  const formulation = (inputs?.todo ?? []).find((t) => t.kind === "formulation");
  const checks = (inputs?.readiness?.content?.checks ?? []).map((c) => ({
    raw: c.check, label: checkLabel(c.check, c.detail, c.ok), ok: c.ok, detail: c.detail, fix: checkFix(c.check, formulation?.way),
    said: !c.ok && said(c.check),
  }));
  return {
    items, subjects, counts, byArea, byFile, fileWork, next: open[0] ?? null, ask: askLines(delivery, inputs), checks,
    inModel: inModel(inputs, delivery), ready: !open.length && !checking && Boolean(inputs?.readiness?.content?.ready), checking,
  };
}

function draftItem(add: (i: Omit<WorkItem, "open">) => void, g: ReviewGroup, i: ReviewItem, name: string, subjects: string[],
                   blinded: string | undefined, fileOf: (sha: string) => string, detail?: string) {
  const draft = i.draft as { sid?: string; needs?: string[]; labels?: Record<string, string> } | null | undefined;
  const needs = (draft?.needs ?? []).map((n) => draft?.labels?.[n] ?? n.replace(/_/g, " "));
  const sha = (i.source as { doc_sha256?: string | null } | null | undefined)?.doc_sha256;
  add({ id: `draft:${i.id}`, group: "missing", status: "missing", area: g.tab as Tab, pipeline: "sheet-form",
        label: g.kind === "sheet" ? `${i.label}: ${needs.length ? `not stated: ${needs.join(", ")}` : "to read"}`
          : `${name} · ${i.label}: ${needs.length ? `not stated: ${needs.join(", ")}` : "to read"}`,
        where: { tab: g.tab as Tab, anchor: `group-${g.id}` }, blocked: blinded, detail,
        files: draft?.sid ? [draft.sid] : sha ? [fileOf(sha)] : [], subjects, weight: 1 });
}

/** The /inputs to-do rows that are a model check's gap (`modeler_project.inputs.todo`, by the check's name without its
 *  reference): a pathway's process, the tablet studies' formulation, a multiple-dose study's dosing, a study's
 *  demographics; and, for the minimum compound data (S0), a compound value missing, or a compound value held for a
 *  person's check (a value to accept or correct, a pKa, a unit, a disagreement, an elimination pathway's process),
 *  which is how the to-do lists an S0 gap a value was found for ("an open issue on a parameter is what settles its S0
 *  gap: not listed twice"; final review OWN-14: the review's "An elimination pathway: check this value before it is
 *  used"). Every S0 gap is one of these rows, so a failed S0 check with one of them listed is said in To do. */
const COMPOUND_ISSUE = new Set(["review", "correct", "pka", "unit", "conflict"]);
const CHECK_TODO: Record<string, (t: TodoLike) => boolean> = {
  // an elimination pathway's process to choose settles its S0 gap too (`inputs.todo`: any issue on an elim.* target)
  "S0 completeness": (t) => t.kind === "missing" || ((COMPOUND_ISSUE.has(t.kind) || (t.kind === "process" && t.target.startsWith("elim")))
    && (t.tab ?? "compound") === "compound"),
  "every pathway placeable": (t) => t.kind === "process", "formulations of solid studies": (t) => t.kind === "formulation",
  "multiple-dose regimens": (t) => t.kind === "regimen", "demographics stated": (t) => t.kind === "demographics",
};
const checkKeyOf = (raw: string) => raw.replace(/\s*\([^)]*\)\s*$/, "");

/** The checks a values table stays folded under (final review OWN-9): when every row of it that needs the person is
 *  marked only by failed checks that each have their own row in Checks (`marking`: the card's failed checks that mark
 *  values; `listed`: whether one is listed in Checks), and no row is in a disagreement (settled value by value), the
 *  table stays one line naming each check with the number of its rows it marks, most first: one decision each, in
 *  Checks. Several checks may mark the same rows (the concentrations of an arm name no analyte, and 6 of them state more
 *  than one LLOQ because of it). Null when no row needs the person, or when one does otherwise (a disagreement, a check
 *  not listed in Checks): the table then opens. */
export function foldChecks<C extends { id: string; values: string[] }>(rows: { id: string }[], marking: C[], listed: (c: C) => boolean,
                                                                       conflicts: { values: string[] }[]): { check: C; count: number }[] | null {
  const ids = new Set(rows.map((r) => r.id));
  const from = marking.map((check) => ({ check, count: new Set(check.values.filter((v) => ids.has(v))).size })).filter((x) => x.count > 0);
  if (!from.length || conflicts.some((x) => x.values.some((v) => ids.has(v))) || from.some((x) => !listed(x.check))) return null;
  return from.sort((a, b) => b.count - a.count);
}

/** A place on a delivery subject's card, by the subject (`delivery-gap-st-8-route`): two cards open at once each have
 *  their own facts, required items, blockers, disagreements and links, so a link into one card never lands on the other
 *  (final review CODE-1). */
export const cardPlace = (place: string, subject: string, id: string) => `delivery-${place}-${subject}-${id}`;

/** The status line's one primary button: what comes next, in words ("Next: Check 10 table layouts"). */
export function nextText(model: WorkModel): string | null {
  const first = model.next;
  if (!first) return null;
  const n = model.items.filter((i) => i.open && i.group === first.group).length;
  const name = first.label.replace(/^(Study|Product|Compound) /, (k) => k.toLowerCase());
  switch (first.group) {
    case "ready": case "confirm": return `Next: Confirm ${name}`;
    case "layouts": return `Next: Check ${plural(n, "table layout")}`;
    case "link": return n > 1 ? `Next: Link the values of ${plural(n, "file")}` : `Next: ${first.label}`;
    case "notread": return `Next: Numbers not read in ${plural(n, "file")}`;
    case "missing": return `Next: Fill in ${first.label}`;
    default: return `Next: ${first.label}`;
  }
}

/** What holds up a delivery subject's signature, in one line: "10 table layouts · 6 files to link · 9 files with numbers
 *  not read". */
export function gateText(held: WorkItem[]): string {
  const n = (g: Group) => held.filter((i) => i.group === g).length;
  return [n("layouts") ? `${plural(n("layouts"), "table layout")} to check` : "",
          n("link") ? `${plural(n("link"), "file")} to link` : "",
          n("notread") ? `${plural(n("notread"), "file")} with numbers not read` : ""].filter(Boolean).join(" · ");
}

/** The decision a numbers-not-read item waits for when no layout can read its numbers (plan §3 API 3, the owner's). */
export const OWNER_CELLS = "whether a single cell can be set aside as not data";
/** What of a held signature still needs the owner's decision, in one sentence (review OWN-2 d): the gate itself, which
 *  holds every signature of the delivery until its whole clean-up is done (contracts §11.10), and, when a held item
 *  waits for it, setting single cells aside (plan §3 API 3). */
export function ownerText(held: WorkItem[]): string {
  const cells = held.filter((i) => i.owner === OWNER_CELLS);
  const gate = "whether a signature waits for the whole delivery's clean-up or only for its own files'";
  return cells.length
    ? `Two decisions here are the owner's: ${OWNER_CELLS} (${plural(cells.length, "file")} wait${cells.length === 1 ? "s" : ""} for it), and ${gate}.`
    : `It is the owner's decision ${gate}.`;
}

/** Whether no table layout can read a read table's numbers that are not read (review OWN-2 d): each is written so that
 *  no reading takes it (not a plain number, `UNREADABLE`), or sits in a sheet row beside one that is (its SD or n, which
 *  then qualifies no value). Every cell must be listed (`silent_cells` holds the first 50). */
export function noLayoutReads(r: { silent: number; silent_cells?: { where: string; why: string }[] }): boolean {
  const cells = r.silent_cells ?? [];
  if (!r.silent || cells.length < r.silent) return false;
  const rowOf = (where: string) => /![A-Z]{1,3}([0-9]+)$/.exec(where)?.[1] ?? null;
  const rows = new Set(cells.filter((c) => UNREADABLE.has(c.why)).map((c) => rowOf(c.where)).filter((x): x is string => x !== null));
  return cells.some((c) => UNREADABLE.has(c.why))
    && cells.every((c) => UNREADABLE.has(c.why) || (rowOf(c.where) !== null && rows.has(rowOf(c.where)!)));
}

/** Open items by status word, in a few words: "3 missing · 1 to decide". */
export function statusSummary(items: WorkItem[]): string {
  return (["missing", "to_decide", "to_confirm"] as Status[]).map((st) => [st, items.filter((i) => i.status === st).length] as const)
    .filter(([, n]) => n).map(([st, n]) => `${n} ${STATUS_WORD[st].toLowerCase()}`).join(" · ");
}

/** What a confirmed card put in the model: who confirmed or signed it, and when. */
function inModelText(s: Subject): string {
  const c = s.row?.confirmation;
  if (s.path === "delivery" && c?.current && c.landed) return `Signed by ${c.printed_name || c.by} on ${whenText(c.at)}; in the model.`;
  const g = s.groups.find((x) => x.state === "confirmed");
  return g ? `Confirmed by ${g.confirmed_by ?? "a person"}${g.confirmed_at ? ` on ${whenText(g.confirmed_at)}` : ""}; in the model.` : "In the model.";
}

/** What the model holds now: the studies its study list is built from (the client's only once confirmed: a client
 *  dataset waiting for confirmation is not in it), the formulations and the compound's values the inputs keep. Nothing
 *  proposed and not yet confirmed is counted. A study signed on the delivery is one study however many datasets its
 *  landing loaded (its arms land as `<study>-<arm>`): the datasets are counted beside it, from the same rows, so the
 *  status line, the card ("In the model: 3 datasets") and the signing dialog ("3 datasets") say the same (final review,
 *  owner-job gap 3). */
export function inModel(inputs: InputsLike | null,
                        delivery: { subjects: { label: string; confirmation?: { landed_datasets: string[] } | null }[] } | null = null): InModel {
  const kept = (inputs?.compound ?? []).filter((r) => r.state === "kept");
  const signed = new Map<string, string>();
  for (const s of delivery?.subjects ?? []) for (const id of s.confirmation?.landed_datasets ?? []) signed.set(id, normLabel(s.label));
  const rows = (inputs?.studies ?? []).filter((s) => !s.excluded);
  return {
    studies: new Set(rows.map((s) => (s.dataset_id && signed.get(s.dataset_id)) || `row:${s.study_id}`)).size,
    datasets: rows.length,
    formulations: new Set(kept.filter((r) => /^form\.[^.]+\.type$/.test(r.id)).map((r) => r.id.split(".")[1])).size,
    values: kept.filter((r) => r.tab === "compound").length,
  };
}

/** The formulations the model holds: each a kept `form.<name>.type` (the CPF's release model of a formulation), by name. */
export function formulationsHeld(inputs: InputsLike | null): string[] {
  return [...new Set((inputs?.compound ?? []).filter((r) => r.state === "kept" && /^form\..+\.type$/.test(r.id))
    .map((r) => r.id.slice("form.".length, -".type".length)))];
}

/** A product's release in the model (final review OWN-10): the formulation the model holds under the product's name (its
 *  card's, or another name the sheet form gave it), or null while its release is not set; and whether a tablet or capsule
 *  study needs it: the readiness check "formulations of solid studies" names this product's formulation as missing or
 *  incomplete, or says a solid study has no formulation at all (any product may then be the one). */
export function releaseOf(s: Pick<Subject, "label" | "aliases">, inputs: InputsLike | null): { name: string | null; needed: boolean } {
  const names = new Set([s.label, ...s.aliases].map(normLabel));
  const name = formulationsHeld(inputs).find((n) => names.has(normLabel(n))) ?? null;
  const parts = (inputs?.todo ?? []).filter((t) => t.kind === "formulation").flatMap(formulationParts);
  const needed = parts.some((p) => /defines no formulation \(/.test(p)
    || [...p.matchAll(/formulation '([^']+)'/g)].some((m) => names.has(normLabel(m[1]))));
  return { name, needed };
}
/** Where a product's card says its release, and offers to set it. */
export const releaseAnchor = (s: Pick<Subject, "key">) => `card-release-${s.key}`;

/** A product's names as two readers give them, as the join compares them: its card's, the other names it was read under
 *  and its sheet-form groups' titles (what a dissolution profile's product is matched to, `ProductCard.productOf`). */
export const productNames = (s: Pick<Subject, "label" | "aliases" | "groups">) =>
  new Set([s.label, ...s.aliases, ...s.groups.map((g) => g.title.replace(/^Product /, ""))].map(normLabel));
/** The card of the product of this name (the API names a product as its reader gave it), if it has one. */
export const productFor = (subjects: Subject[], name: string | null | undefined): Subject | null =>
  (name ? subjects.find((s) => s.kind === "product" && productNames(s).has(normLabel(name))) ?? null : null);

/** Why a subject waits until the plan is signed, in words (`blinded_why`): the delivery's reason for its card, else the
 *  reason the sheet form's group of it is withheld (the delivery's, or the project's blinding list's: "the plan holds it
 *  back for external validation"), so a wrong match is seen wherever it is withheld (rounds 3 and 4). */
export const blindedWhy = (s: Pick<Subject, "row" | "groups">): string | null =>
  s.row?.blinded_why ?? s.groups.find((g) => g.blinded && g.blinded_why)?.blinded_why ?? null;
/** "Blinded until the plan is signed, because …" with what follows (`after`), from a reason (`blindedWhy`, a dataset's
 *  `blinded_why`): one sentence wherever a study, its card or a dataset of it is withheld (round 5). */
export const blindedWords = (why: string | null | undefined, after = "") =>
  `Blinded until the plan is signed${why ? `, because ${why}` : ""}${after}`;
/** "Blinded until the plan is signed, because …" with what follows (`after`). */
export const blindedText = (s: Pick<Subject, "row" | "groups">, after: string) => blindedWords(blindedWhy(s), after);
/** What a blinded card says where "Confirm and sign…" would be (round 6): the API refuses its signature until the plan
 *  is signed (409 BLINDED), so no button is offered, and why is said (`blinded_why`), as wherever it is withheld. */
export const signWaitsWords = (why: string | null | undefined) =>
  `Signing waits until the plan is signed${why ? `, because ${why}` : ""}.`;

/** A part of a blinded reason, and where what it says is decided (round 5): `purpose`, the study's own purpose on its
 *  delivery card ("it is entered for external validation on its card": changed there); `plan`, the plan's studies and
 *  roles ("the plan places it in S5 …", "the study split proposes it for S5 …": Review & sign). Other parts are said. */
export type BlindedPart = { text: string; to?: "purpose" | "plan" };
const DECIDED: [RegExp, BlindedPart["to"]][] = [
  [/it is entered for [^:;]+? on its card/, "purpose"],
  [/the plan places it in [^:;]+?\([^)]*\)/, "plan"],
  [/the study split proposes it for [^:;]+?\([^)]*\), before a plan/, "plan"],
];
/** A blinded reason (the API's words) in parts, each saying where it is decided where it can be changed. */
export function blindedParts(why: string): BlindedPart[] {
  const found = DECIDED.map(([rule, to]) => ({ m: rule.exec(why), to })).filter((x) => x.m)
    .sort((a, b) => a.m!.index - b.m!.index)[0];
  if (!found) return why ? [{ text: why }] : [];
  const { m, to } = found;
  return [...(m!.index ? [{ text: why.slice(0, m!.index) }] : []), { text: m![0], to },
          ...blindedParts(why.slice(m!.index + m![0].length))];
}

/** What only the client can send, one line per requirement with the subjects it is asked for: the delivery's request and
 *  the formulation item's (`ask`: each tablet study whose way to its formulation offers "ask the client", so wherever the
 *  step bar, Review & sign or To do offers it, this list holds the study's line: rounds 4 and 5), one line per requirement
 *  and wording, each study named once whichever path asks it. */
export function askLines(delivery: DeliveryPage | null, inputs: InputsLike | null = null): AskLine[] {
  const out = new Map<string, AskLine>();
  // the formulation item's lines anchor apart by the product a study names (`askAt`: round 6, a named study's line and
  // the line of the studies that name none shared one anchor); the delivery's by their requirement, as before
  const lines: [RequestLike, string][] = [
    ...(delivery?.enabled ? delivery.request : []).map((l): [RequestLike, string] => [l, `todo-ask-${l.req_id}`]),
    ...(inputs?.todo ?? []).filter((t) => t.kind === "formulation").flatMap((t) => t.ask ?? [])
      .map((l): [RequestLike, string] => [l, l.req_id === "REQ-form.release" ? askAt(l.product) : `todo-ask-${l.req_id}`]),
  ];
  for (const [line, at] of lines) {
    const [what, subject] = line.what.split(" — ");
    const key = `${line.req_id}|${what}`;
    const known = out.get(key) ?? { req: line.req_id, what, subjects: [], required: line.required, why: line.why, at };
    const name = subject?.replace(/^(study|product) /, "");
    if (name && !known.subjects.some((n) => normLabel(n) === normLabel(name))) known.subjects.push(name);
    known.required ||= line.required;
    out.set(key, known);
  }
  return [...out.values()];
}

/** An area's one-line head: what it holds and what is open in it ("6 studies · 4 to confirm · 1 to decide"). */
export function areaHead(model: WorkModel, tab: Tab, files = 0): string {
  const open = model.items.filter((i) => i.open && i.area === tab);
  const n = (s: Status) => open.filter((i) => i.status === s).length;
  const subjects = model.subjects.filter((s) => s.area === tab);
  const lead = tab === "studies" ? plural(subjects.filter((s) => s.kind === "study").length, "study", "studies")
    : tab === "formulations" ? plural(subjects.filter((s) => s.kind === "product").length, "product")
      : tab === "compound" ? `${plural(model.inModel.values, "value")} in the model`
        : tab === "files" ? plural(files, "file") : "";
  const parts = [lead, n("missing") ? `${n("missing")} missing` : "", n("to_confirm") ? `${n("to_confirm")} to confirm` : "",
                 n("to_decide") ? `${n("to_decide")} to decide` : ""].filter(Boolean);
  return parts.length > (lead ? 1 : 0) ? parts.join(" · ") : `${lead ? `${lead} · ` : ""}nothing open here`;
}

/** The cards of an area that are signed on the delivery and not done, with what is open on each (counted in this area).
 *  Since slice 3 they are in their area; until then they opened in Client files, and the area's head named them. */
export function onDelivery(model: WorkModel, tab: Tab): { subject: Subject; open: WorkItem[]; confirm: WorkItem | undefined }[] {
  return model.subjects.filter((s) => s.area === tab && s.path === "delivery" && !s.done).map((s) => ({
    subject: s, open: model.items.filter((i) => i.open && i.subjects.includes(s.key) && CARD_ITEM.test(i.id)),
    confirm: model.items.find((i) => i.id === `confirm:${s.key}`),
  }));
}

// --- To do's batch work (plan 2026-11-14 slice 4) --------------------------------------------------------------------------
// The rows of To do's batch tables, one per work item above, so a table's rows are the work model's items and every count
// stays the same: the files whose values have no study or product (link and alias items), the files with numbers not
// read (notread items) and the table layouts to check (layout items). What the tables suggest, refuse and send is
// computed here, from the delivery page as the API answered it.

type Value = Schema<"DeliveryValue">;
type Entity = Schema<"DeliveryEntity">;
type Outside = Schema<"DeliveryOutside">;
type Region = Schema<"DeliveryRegion">;
type MappingRow = Schema<"DeliveryMappingRow">;
/** What stands in place of a blinded study's text (the delivery review's own word, components/delivery/shared.tsx). */
const WITHHELD = "withheld (blinded)";

/** The link form's "a new one", named beside it (never an entity's id). */
export const NEW = "__new__";

/** Where a file's values are linked: a study (and its arm) or a product (and its batch), and their analyte; each an
 *  entity's id, NEW with its name beside it, or "" for none. */
export type LinkTarget = {
  study: string; newStudy: string; arm: string; newArm: string; product: string; newProduct: string;
  batch: string; newBatch: string; analyte: string; newAnalyte: string;
};
export const NO_TARGET: LinkTarget = {
  study: "", newStudy: "", arm: "", newArm: "", product: "", newProduct: "", batch: "", newBatch: "", analyte: "", newAnalyte: "",
};

/** What can be linked as one: a file (its row) or one of its tables (a part, when its tables go to different places).
 *  Two of them that hold the same subject in the same period cannot share one arm of one study (`collisions`). */
export type LinkPiece = {
  /** the row's sha256, or `${sha}#${part}` for a part */
  key: string;
  sha: string;
  /** in words: the file's name, or "the file, its table on sheet Sheet1" */
  name: string;
  values: Value[];
  /** each individual value as the arm guard compares it, its analyte aside (`seriesKey`: "001 · I · plasma ·
   *  concentration") */
  pairs: string[];
  /** the arm, batch and analyte it gives all its values (as read from it), if it gives one */
  own: { arm: Entity | null; batch: Entity | null; analyte: Entity | null };
};

/** One table of a file whose values have no study or product, with the file's facts read on its sheet or page (when it
 *  is the only table there), or the file's other facts: linked on its own when the file's tables go to different places
 *  (a workbook with one sheet per study). */
export type LinkPart = LinkPiece & {
  /** "individual PK table, 76 values · sheet Sheet1 · 3 facts" */
  label: string;
  /** where it is in the file, in a few words ("sheet Sheet1"; "sheet Sheet1, cells A4 to M12" beside another table there) */
  place: string;
  goesTo: "study" | "product";
  /** what its own title suggests (its table's caption and the lines read with it), and why; none for facts alone */
  suggested: { target: LinkTarget; why: string } | null;
  /** where a person linked it before its table was read again, when that link was not carried over */
  before: Before | null;
};

/** A link a re-read of its table did not carry over (`DeliveryPage.relink`, review OWN-1): where the values went, which
 *  the row is filled with again (`target`; null when they went to more than one place, said in the note, and the person
 *  chooses again: final review OWN-1), why it was not carried, in words, and the subjects it named (a study with no value
 *  left is no longer on the page's list of subjects, so the row's choices offer it from here). */
export type Before = { target: LinkTarget | null; why: string; note: string; subjects: SubjectRow[] };

export type LinkRow = LinkPiece & {
  item: WorkItem;
  /** the delivery's id of the file (the row's test ids), "entered" */
  fileId: string;
  file: string;
  /** what the file holds, in a few words: "individual PK table, 76 values · dose 50 mg · fasted · LLOQ 0.5 ng/mL" */
  holds: string;
  /** where values like these belong: a dissolution or product table's to a product, the others to a study */
  goesTo: "study" | "product";
  /** its tables (each with the facts read beside it) and its other facts: more than one, they can go to different places */
  parts: LinkPart[];
  /** its tables' own titles point to different places (one names a study, another names another or none): each table is
   *  given its own place to start with */
  split: boolean;
  /** the name the sheet form read the file under */
  sheet: string | null;
  /** "Same study as 230-23?": the delivery study the sheet form's name only starts with, and what Yes fills the row with */
  alias: { study: SubjectRow; target: LinkTarget } | null;
  /** the target the file's own labels suggest for all of it (its tables' titles and the lines read with them, else its
   *  name) and why; none while the alias question is open, or when its tables point to different places. Where a person
   *  linked the file before a re-read of its tables (`before`), that is the suggestion, said on the row */
  suggested: { target: LinkTarget; why: string } | null;
  /** where a person linked all of it before its tables were read again, when that link was not carried over */
  before: Before | null;
  blinded: boolean;
};

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** Whether `text` names `label` as a whole name: "Study 230-23:" names 230-23, "230-23-REF" does not. */
export function namesLabel(text: string, label: string): boolean {
  const l = label.trim();
  return Boolean(l) && new RegExp(`(^|[^A-Za-z0-9-])${escapeRe(l)}($|[^A-Za-z0-9-])`, "i").test(text);
}
/** A file name's words, without its extension. */
const nameWords = (name: string) => name.replace(/\.[A-Za-z0-9]{1,5}$/, "").split(/[\s_]+/).filter(Boolean);
/** The words that set a file's name apart from the others' ("Reference" of "230-23 Fasting Reference.xlsx" beside
 *  "230-23 Fasting Test.xlsx"): the name an arm of its own is suggested under. */
export function distinctWords(name: string, others: string[]): string {
  const rest = new Set(others.flatMap((o) => nameWords(o).map((w) => w.toLowerCase())));
  return nameWords(name).filter((w) => !rest.has(w.toLowerCase())).join(" ");
}
/** The names among `others` that share a word with `name` ("230-23 Fasting Reference.xlsx" with "230-23 Fasting
 *  Test.xlsx", not with "messy-delivery.xlsx"): the files an arm's name is told apart from. */
const alike = (name: string, others: string[]) => {
  const mine = new Set(nameWords(name).map((w) => w.toLowerCase()));
  return others.filter((o) => o !== name && nameWords(o).some((w) => mine.has(w.toLowerCase())));
};
const digits = (x: number) => String(Number(x.toPrecision(8)));

/** A fact of a file in a few words ("dose 50 mg", "fasted", "LLOQ 0.5 ng/mL"); never a blinded study's value. */
function factWords(v: Value): string {
  const value = v.blinded ? WITHHELD : v.value === null ? v.verbatim ?? "" : typeof v.value === "number" ? digits(v.value) : String(v.value);
  const said = `${value}${v.unit && !v.blinded ? ` ${v.unit}` : ""}`;
  return v.field === "food_state" ? said : `${v.field === "lloq" ? "LLOQ" : v.field.replace(/_mg$/, "").replace(/_/g, " ")} ${said}`;
}

/** The one entity of a role the file gives its values (its arm, batch or analyte), with its label; none when the file
 *  gives none or several. */
function ownEntity(values: Value[], role: "arm" | "batch" | "analyte"): Entity | null {
  const ids = [...new Set(values.map((v) => v.entity[role]).filter((x): x is string => Boolean(x)))];
  if (ids.length !== 1) return null;
  return { id: ids[0], label: values.find((v) => v.entity[role] === ids[0])?.labels[role] ?? ids[0] };
}
const ownOf = (values: Value[]) => ({ arm: ownEntity(values, "arm"), batch: ownEntity(values, "batch"), analyte: ownEntity(values, "analyte") });

/** Values linked already, as one piece to link elsewhere (review INT-5): the file's values a link covers, with the
 *  subjects and periods the collision guard compares and the arm, batch and analyte they carry now. */
export function linkedPiece(sha: string, name: string, values: Value[]): LinkPiece {
  return { key: sha, sha, name, values, pairs: pairsOf(values), own: ownOf(values) };
}

/** Where a person's link sent a file's values, as the link form's target (`DeliveryFileLink`, `DeliveryRelink`). */
export function linkTarget(l: { study: string | null; arm: string | null; product: string | null; batch: string | null; analyte: string | null }): LinkTarget {
  return { ...NO_TARGET, study: l.study ?? "", arm: l.study ? l.arm ?? "" : "", product: l.product ?? "", batch: l.product ? l.batch ?? "" : "",
           analyte: l.analyte ?? "" };
}

type FileLink = { assignment: string; targets: string[]; values: number; study: string | null; arm: string | null; product: string | null;
                  batch: string | null; analyte: string | null; labels: Record<string, string> };
/** A place a file's values were linked to (its study and arm, or its product and batch) with every link in force that
 *  sent some of them there (a file's facts and its table are often two links: "State it…" relinks the concentrations
 *  alone, and a re-read carries the table's link over apart from the facts'). Moved as one (final review INT-5): `targets`
 *  are the union of the links' targets, `values` their count, `target` the link form filled with the place and the
 *  analyte they state (the one stated, when the others state none), `words` the place in words. */
export type LinkPlace<L extends FileLink = FileLink> = { key: string; links: L[]; targets: string[]; values: number; target: LinkTarget; words: string };

/** A file's links (`DeliveryFile.links`) by the place they sent its values to, in the order the links were made. */
export function linkPlaces<L extends FileLink>(links: L[]): LinkPlace<L>[] {
  const places = new Map<string, L[]>();
  for (const l of links) {
    const key = [l.study, l.study ? l.arm : null, l.product, l.product ? l.batch : null].join("|");
    places.set(key, [...(places.get(key) ?? []), l]);
  }
  return [...places.entries()].map(([key, list]) => {
    const stated = [...new Set(list.map((l) => l.analyte).filter((a): a is string => Boolean(a)))];
    const analyte = stated.length === 1 ? stated[0] : null;
    const first = list.find((l) => l.analyte === analyte) ?? list[0];
    const place = { ...first, analyte, labels: { ...first.labels } };
    if (!analyte) delete place.labels.analyte;
    return { key, links: list, targets: [...new Set(list.flatMap((l) => l.targets))], values: list.reduce((n, l) => n + l.values, 0),
             target: linkTarget(place), words: linkWords(place) };
  });
}

/** A link's destination in words, by the labels the API gives with it: "study 230-23 · arm Reference". */
export function linkWords(l: { study: string | null; arm: string | null; product: string | null; batch: string | null; analyte: string | null;
                               labels: Record<string, string> }): string {
  const named = (role: "study" | "arm" | "product" | "batch" | "analyte") => l.labels[role] ?? l[role] ?? "";
  return [l.study ? `study ${named("study")}` : "", l.study && l.arm ? `arm ${named("arm")}` : "",
          l.product ? `product ${named("product")}` : "", l.product && l.batch ? `batch ${named("batch")}` : "",
          l.analyte ? `analyte ${named("analyte")}` : ""].filter(Boolean).join(" · ");
}
/** The fields that are never one series with another, as the ledger reads them (`ledger_view.in_conflicts`): a naming
 *  fact, a link fact, the LLOQ (written per study, analyte and matrix), a derived spread fact. */
const NAMING_FIELDS = new Set(["study_id", "treatment", "analyte", "product", "batch"]);
const inConflicts = (v: Value) => !(NAMING_FIELDS.has(v.field) || v.field.startsWith("link.") || v.field === "lloq"
  || (v.value === null && v.spread !== null && v.method === "derived" && (v.compute ?? "").startsWith("spread-")));
/** An individual value as the arm guard compares it, its analyte aside (compared per piece): "subject · period · matrix ·
 *  field", the ledger's conflict key (`ledger_view._entity_key` and the field; review INT-4). A period or a matrix left
 *  out is "" and matches any. */
export const seriesKey = (v: { field: string; labels: Record<string, string> }) =>
  [v.labels.subject, v.labels.period ?? "", v.labels.matrix ? normLabel(v.labels.matrix) : "", v.field].join(" · ");
const pairsOf = (values: Value[]) => [...new Set(values.filter((v) => v.labels.subject && inConflicts(v)).map(seriesKey))];
const kindGoesTo = (kinds: Set<string | null>): "study" | "product" =>
  (kinds.has("dissolution") || kinds.has("product_batch") || kinds.has("composition") ? "product" : "study");

/** Where in its file a value was read (its anchor's locator: `s:'Sheet1'!C5`, `p:3/t:1/…`). */
const locatorOf = (v: Value) => { const a = v.anchor ?? ""; return a.slice(a.indexOf("#") + 1); };
/** The sheet or page a locator is on (`s:Sheet1`, `p:3`), or "" for a place with neither. */
function sheetOf(where: string): string {
  const sheet = /^s:'((?:[^']|'')+)'!/.exec(where);
  if (sheet) return `s:${sheet[1]}`;
  const page = /^p:(\d+)/.exec(where);
  return page ? `p:${page[1]}` : "";
}
const letters = (l: string) => [...l].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0);
/** Whether a sheet cell (`…!C5`) lies in a region's range (`…!A4:M12`). */
function inRange(range: string, cell: string): boolean {
  const r = /!([A-Z]{1,3})([0-9]+):([A-Z]{1,3})([0-9]+)$/.exec(range), c = /!([A-Z]{1,3})([0-9]+)$/.exec(cell);
  if (!r || !c) return false;
  const [col, row] = [letters(c[1]), Number(c[2])];
  return col >= letters(r[1]) && col <= letters(r[3]) && row >= Number(r[2]) && row <= Number(r[4]);
}

/** A study's arm its title names ("…, Reference, 50 mg" names the arm Reference), as the target's arm. */
const armIn = (title: string, study: SubjectRow) => study.arms.find((a) => namesLabel(title, a.label));

/** How many values to link, in the units a file's row says them in: a table's cells are values, a fact read beside a
 *  table (its id has no `#`: a dose, the LLOQ) a fact. "76 values and 3 facts". The Link table's head, its rows and their
 *  buttons count alike (final review OWN-16: the head said 365 values where its rows said 355 and 10 facts). */
export function linkCount(values: { id: string }[]): string {
  const facts = values.filter((v) => !v.id.includes("#")).length;
  const cells = values.length - facts;
  return [cells ? plural(cells, "value") : "", facts ? plural(facts, "fact") : ""].filter(Boolean).join(" and ") || "no value";
}

/** One row per file whose values have no study or product, in the order of `items` (the work model's link and alias
 *  items), with what its own labels suggest. A file the sheet form read as "230-23-REF" asks "Same study as 230-23?"
 *  first: nothing is filled until it is answered, and Yes fills the study and the suggested arm (plan §2.1). Each of the
 *  file's tables is a part with its own title (its caption and the lines read with it): when the parts' titles point to
 *  different places, the row starts with each part in its own place. The arm: an arm of the study its title names; else
 *  the words that set its name apart from the other files of the same study, linked or not ("Reference" and "Test" of
 *  "230-23 Fasting Reference.xlsx" and "230-23 Fasting Test.xlsx"); else the sheet form's name past the study's ("REF"
 *  of 230-23-REF); the study's arm of that name, or a new one. */
export function linkRows(items: WorkItem[], page: DeliveryPage | null, subjects: Subject[]): LinkRow[] {
  if (!page?.enabled) return [];
  const files = page.deliveries.flatMap((d) => d.files);
  const fileOf = (sha: string) => files.find((f) => f.sha256 === sha && !f.repeat) ?? files.find((f) => f.sha256 === sha);
  const studies = page.subjects.filter((s) => s.subject_type === "study");
  const products = page.subjects.filter((s) => s.subject_type === "product");
  const sheetRead = (sha: string) => subjects.find((s) => !s.row && s.groups.some((g) => groupShas(g).includes(sha)))?.label ?? null;
  const fit = (text: string, among: SubjectRow[]) => among.filter((r) => namesLabel(text, r.label)).sort((a, b) => b.label.length - a.label.length)[0];
  const titles = new Map<string, string>();
  // a person's link that a re-read of the values' table did not carry over: the row comes back with it (review OWN-1)
  const relinks = page.relink ?? [];
  const beforeOf = (vs: Value[]): Before | null => {
    const found = relinks.filter((r) => vs.some((v) => r.targets.some((t) => v.id === t || v.id.startsWith(`${t}#`))));
    if (!found.length) return null;
    const where = (r: (typeof relinks)[number]) => [r.study, r.arm, r.product, r.batch, r.analyte].join("|");
    // one line per place they went (the latest link to it), in the order the links were made
    const places = [...new Map(found.map((r) => [where(r), r])).values()];
    const said = places.map((r) => `${linkWords(r)} (${r.by === "code" ? "carried over by the reader" : `by ${r.by}`} on ${whenText(r.at)})`)
      .join(" and to ");
    // a study or product with no value left is not on the page's list: offered from here, with the arm or batch named
    const kept = places.flatMap((r) => {
      const subject = r.study ?? r.product;
      const named = (role: "study" | "arm" | "product" | "batch" | "analyte") => r.labels[role] ?? r[role] ?? "";
      if (!subject || page.subjects.some((s) => s.subject === subject)) return [];
      return [{
        subject_type: r.study ? "study" : "product", subject, label: named(r.study ? "study" : "product"), values: 0, by_level: {},
        by_method: {}, files: [], deliveries: [], confirmation: null, loaded_elsewhere: [], proposed_elsewhere: [], legacy_groups: [],
        confirm_on: "delivery", blinded: false, blinded_why: null,
        arms: r.study && r.arm ? [{ id: r.arm, label: named("arm") }] : [], batches: r.product && r.batch ? [{ id: r.batch, label: named("batch") }] : [],
      } satisfies SubjectRow];
    }).filter((s, i, all) => all.findIndex((x) => x.subject === s.subject) === i);
    const one = places.length === 1 ? places[0] : null;
    return {
      // one place: the row is filled with it; two or more (part of a table linked here, part there): said, and the
      // person chooses again (final review OWN-1)
      target: one ? { ...linkTarget(one), analyte: one.analyte ?? ownEntity(vs, "analyte")?.id ?? "" } : null,
      why: `linked before to ${places.map((r) => linkWords(r)).join(" and to ")}`, subjects: kept,
      note: found.every((x) => x.whole)
        ? `Linked before to ${said}. ${one ? "Its table was" : "Its tables were"} read again before links were carried over: link ${one ? "it" : "them"} again.`
        : one ? `Linked before, in part, to ${said}. Its table was read again, and the link covered only part of it, so `
          + "it was not carried over: check where these values go and link them again."
          : `Linked before, in part, to ${said}. Read again, its values were linked to more than one place and the links `
            + "were not carried over: check where these values go and link them again.",
    };
  };
  const rows: LinkRow[] = items.filter((i) => /^(link|alias):/.test(i.id) && i.ref).map((item) => {
    const sha = item.ref!;
    const values = page.unassigned.filter((v) => (v.file_sha256 ?? "entered") === sha);
    const f = sha === "entered" ? undefined : fileOf(sha);
    const file = f?.name ?? values[0]?.file ?? "values entered by a person";
    const tables = new Map<string, Value[]>();
    for (const v of values.filter((x) => x.id.includes("#"))) tables.set(v.id.split("#")[0], [...(tables.get(v.id.split("#")[0]) ?? []), v]);
    const facts = values.filter((v) => !v.id.includes("#"));
    const holds = [...[...tables.values()].map((t) => `${tableKindText(t[0].table_kind)}, ${plural(t.length, "value")}`),
                   ...facts.slice(0, 4).map(factWords), facts.length > 4 ? `${facts.length - 4} more facts` : ""].filter(Boolean).join(" · ");
    const goesTo = kindGoesTo(new Set([...tables.values()].map((t) => t[0].table_kind)));
    const own = ownOf(values);
    const sheet = sha === "entered" ? null : sheetRead(sha);

    // its parts: each table where it was read (the region whose cells hold its first value), with the facts of its sheet
    // or page when it is the only table there; the facts beside no table, or beside several, together
    const regionOf = (vs: Value[]): Region | undefined => {
      const at = locatorOf(vs[0]);
      const here = (f?.regions ?? []).filter((r) => r.kind === "table" && sheetOf(r.where) === sheetOf(at));
      const same = here.filter((r) => r.mapping_id && r.mapping_id === vs[0].mapping_id);
      const pick = same.length ? same : here;
      return pick.length > 1 ? pick.find((r) => inRange(r.where, at)) ?? pick[0] : pick[0];
    };
    const read = [...tables.entries()].map(([id, vs]) => ({ id, vs, region: regionOf(vs), on: sheetOf(locatorOf(vs[0])) }));
    const besides = new Map<string, Value[]>(), loose: Value[] = [];
    for (const v of facts) {
      const on = read.filter((t) => t.on && t.on === sheetOf(locatorOf(v)));
      if (on.length === 1) besides.set(on[0].id, [...(besides.get(on[0].id) ?? []), v]);
      else loose.push(v);
    }
    const placeOf = (where: string, on: string) => {
      const at = whereIs(where);
      return read.filter((t) => t.on === on).length > 1 || !on ? at.place : on.startsWith("s:") ? `sheet ${at.name}` : at.name;
    };
    const partOf = (id: string, vs: Value[], title: string, place: string, label: string): LinkPart => {
      const goes = kindGoesTo(new Set(vs.filter((v) => v.id.includes("#")).map((v) => v.table_kind)));
      const found = title ? fit(title, goes === "product" ? products : studies) : undefined;
      const base = { ...NO_TARGET, analyte: ownEntity(vs, "analyte")?.id ?? "" };
      const arm = found?.subject_type === "study" ? armIn(title, found)?.id ?? ownEntity(vs, "arm")?.id ?? "" : "";
      const before = beforeOf(vs);
      return {
        key: `${sha}#${id}`, sha, name: `${file}, ${place ? `its ${label.split(",")[0]} on ${place}` : label}`, values: vs, pairs: pairsOf(vs),
        own: ownOf(vs), label, place, goesTo: goes, before,
        suggested: before ? (before.target ? { why: before.why, target: before.target } : null) : found ? {
          why: `its title names ${KIND_WORD[found.subject_type].toLowerCase()} ${found.label}`,
          target: found.subject_type === "product" ? { ...base, product: found.subject, batch: ownEntity(vs, "batch")?.id ?? "" } : { ...base, study: found.subject, arm },
        } : null,
      };
    };
    const parts: LinkPart[] = read.map((t) => {
      const with_ = besides.get(t.id) ?? [];
      // the table's own words: its caption and the lines read with it (none for a blinded file)
      const title = t.region ? [t.region.caption ?? "", ...(f?.outside ?? []).filter((o) => o.region === t.region!.region_id).map((o) => o.text ?? "")].join("\n") : "";
      const place = t.region ? placeOf(t.region.where, t.on) : "";
      const label = [`${tableKindText(t.vs[0].table_kind)}, ${plural(t.vs.length, "value")}`, place, with_.length ? plural(with_.length, "fact") : ""]
        .filter(Boolean).join(" · ");
      return partOf(t.id, [...t.vs, ...with_], title, place, label);
    });
    if (loose.length) {
      const on = [...new Set(loose.map((v) => sheetOf(locatorOf(v))))];
      const place = on.length === 1 && on[0] ? (on[0].startsWith("s:") ? `sheet ${on[0].slice(2)}` : `page ${on[0].slice(2)}`) : "";
      parts.push(partOf("facts", loose, "", place, [read.length ? `its other ${plural(loose.length, "fact")}` : plural(loose.length, "fact"), place].filter(Boolean).join(" · ")));
    }
    // the file's own words: its tables' titles and the lines read with them (none for a blinded file), then its name
    const title = [...(f?.regions ?? []).map((r) => r.caption ?? ""), ...(f?.outside ?? []).filter((o) => o.region).map((o) => o.text ?? "")].join("\n");
    titles.set(sha, title);
    // linked before a re-read of its tables (and that link not carried over): the row comes back with it, unasked
    const before = beforeOf(values);
    const aliasRow = item.id.startsWith("alias:") && sheet && !before ? prefixAlias(sheet, studies) : null;
    const base = { ...NO_TARGET, analyte: own.analyte?.id ?? "" };
    // the tables say where they go: all the same place, or (no table's title names one) the file's name does; tables
    // whose titles point to different places (or one does and another does not) start each in its own place
    const tabled = parts.filter((p) => p.key !== `${sha}#facts`);
    const said = tabled.map((p) => (p.suggested ? destinationKey(p.suggested.target) : ""));
    const split = !aliasRow && !before?.target && tabled.length > 1 && new Set(said).size > 1;
    const inName = said.every((k) => !k) ? fit(file, goesTo === "product" ? products : studies) : undefined;
    const suggested = before?.target ? { why: before.why, target: before.target } : before || aliasRow || split ? null : tabled.length && said[0] ? {
      why: `${tabled.length > 1 ? "its tables' titles name" : "its title names"} ${tabled[0].suggested!.why.replace(/^its title names /, "")}`,
      target: { ...tabled[0].suggested!.target, analyte: own.analyte?.id ?? "" },
    } : inName ? {
      why: `its file name names ${KIND_WORD[inName.subject_type].toLowerCase()} ${inName.label}`,
      target: inName.subject_type === "product" ? { ...base, product: inName.subject, batch: own.batch?.id ?? "" }
        : { ...base, study: inName.subject, arm: own.arm?.id ?? "" },
    } : null;
    return { item, key: sha, sha, name: file, fileId: sha === "entered" ? "entered" : f?.file_id ?? `sha-${sha.slice(0, 12)}`, file, values, holds,
             goesTo, own, pairs: pairsOf(values), parts, split, sheet, before,
             alias: aliasRow ? { study: aliasRow, target: { ...base, study: aliasRow.subject } } : null, suggested, blinded: values.some((v) => v.blinded) };
  });
  // the arm a row's study suggests: the arm its title names; else what sets its name apart from the study's other files,
  // the ones to link here and the ones linked already (so the second file of a pair is told apart from the first, linked
  // one, as the first was from it); else the sheet form's name past the study's
  const named = (sha: string) => fileOf(sha)?.name;
  const studyOf = (r: LinkRow) => r.alias?.study.subject ?? (r.suggested?.target.study || null);
  for (const r of rows) {
    const study = studyOf(r);
    const row = studies.find((s) => s.subject === study);
    if (!study || !row || r.before) continue;                // a link made before states its own arm
    const linked = row.files.filter((sha) => !rows.some((x) => x.sha === sha)).map(named).filter((n): n is string => Boolean(n));
    const siblings = [...rows.filter((x) => x !== r && studyOf(x) === study).map((x) => x.file), ...alike(r.file, linked)];
    let word = armIn(titles.get(r.sha) ?? "", row)?.label ?? "";
    if (!word && siblings.length) word = distinctWords(r.file, siblings);
    if (!word && r.sheet && normLabel(r.sheet).startsWith(normLabel(row.label))) word = r.sheet.slice(row.label.length).replace(/^[-_ ]+/, "");
    if (!word || (!siblings.length && !r.alias)) continue;
    const known = row.arms.find((a) => normLabel(a.label) === normLabel(word));
    const arm = known ? { arm: known.id, newArm: "" } : { arm: NEW, newArm: word };
    if (r.alias) r.alias.target = { ...r.alias.target, ...arm };
    else if (r.suggested) r.suggested.target = { ...r.suggested.target, ...arm };
  }
  return rows;
}

/** What a link still needs before it is sent, in words ("Pick a study or a product"), or null. A new analyte whose name
 *  one of `analytes` has already is refused (the ledger never makes a second one: pick it). */
export function targetProblem(t: LinkTarget, analytes: Entity[] = []): string | null {
  if (!t.study && !t.product) return "Pick a study or a product";
  for (const [choice, name, what] of [[t.study, t.newStudy, "study"], [t.arm, t.newArm, "arm"], [t.product, t.newProduct, "product"],
                                      [t.batch, t.newBatch, "batch"], [t.analyte, t.newAnalyte, "analyte"]] as const) {
    if (choice === NEW && !name.trim()) return `Name the new ${what}`;
  }
  const same = t.analyte === NEW ? analytes.find((a) => normLabel(a.label) === normLabel(t.newAnalyte)) : undefined;
  return same ? `An analyte named ${same.label} exists already: pick it` : null;
}

/** The analytes a picker offers, one per name (review OWN-11): the delivery gives each file's analyte an entity of its
 *  own, so two files that both name Exampleamide carry two ids of one analyte, and two options both called
 *  "Exampleamide" could split the parent drug in two. Of each name the one the destination study already uses (`used`:
 *  its values' analyte ids), else the file's own (`own`), else the first; the file's own name first, as it reads it. */
export function analyteChoices(analytes: Entity[], own: Entity | null = null, used: string[] = []): Entity[] {
  const byName = new Map<string, Entity[]>();
  for (const a of [...(own ? [own] : []), ...analytes]) {
    const list = byName.get(normLabel(a.label)) ?? [];
    if (!list.some((x) => x.id === a.id)) byName.set(normLabel(a.label), [...list, a]);
  }
  const out = [...byName.values()].map((list) => list.find((a) => used.includes(a.id)) ?? list.find((a) => a.id === own?.id) ?? list[0]);
  const mine = own ? normLabel(own.label) : null;
  return [...out.filter((a) => normLabel(a.label) === mine), ...out.filter((a) => normLabel(a.label) !== mine)];
}

/** The option of `choices` an analyte id stands for (the one of its name), so a select shows the name it carries; the
 *  id itself when it is none of them ("" and NEW stay as they are). */
export function analyteChoice(id: string, choices: Entity[], analytes: Entity[], own: Entity | null = null): string {
  if (!id || id === NEW || choices.some((a) => a.id === id)) return id;
  const label = (own?.id === id ? own.label : analytes.find((a) => a.id === id)?.label) ?? null;
  return (label !== null ? choices.find((a) => normLabel(a.label) === normLabel(label))?.id : undefined) ?? id;
}

/** The body of one `values:assign`. A link replaces the earlier one whole: the arm, batch and analyte are sent as they
 *  stand; an arm only with its study, a batch only with its product. */
export function assignBody(t: LinkTarget, targets: string[], why: string): Schema<"DeliveryAssignment"> {
  const pick = (choice: string, name: string, known: string, fresh: string) =>
    (choice === NEW ? { [fresh]: name.trim() } : choice ? { [known]: choice } : {});
  return {
    targets, why, ...pick(t.study, t.newStudy, "study", "new_study"), ...(t.study ? pick(t.arm, t.newArm, "arm", "new_arm") : {}),
    ...pick(t.product, t.newProduct, "product", "new_product"), ...(t.product ? pick(t.batch, t.newBatch, "batch", "new_batch") : {}),
    ...pick(t.analyte, t.newAnalyte, "analyte", "new_analyte"),
  };
}

const choiceKey = (choice: string, name: string) => (choice === NEW ? `new:${normLabel(name)}` : choice);
/** A target as one destination: rows with the same are linked in one `values:assign` (a new name compared as a label). */
export function destinationKey(t: LinkTarget): string {
  return [choiceKey(t.study, t.newStudy), t.study ? choiceKey(t.arm, t.newArm) : "", choiceKey(t.product, t.newProduct),
          t.product ? choiceKey(t.batch, t.newBatch) : "", choiceKey(t.analyte, t.newAnalyte)].join("|");
}

export type Collision = { files: string[]; study: string; example: string; keys: string[] };
/** What a study already holds, by its id: each individual value's arm ("" for none), analyte, `seriesKey` and file. */
export type Held = Record<string, { arm: string; analyte: string; pair: string; sha?: string | null }[]>;

/** The individual values of a study's card (`/delivery/subjects/study/{id}`), as `collisions` compares them (the analyte
 *  by its name, as `collisions` does). */
export function heldBy(card: { tables: { file_sha256: string | null; values: Value[] }[] } | null | undefined): Held[string] {
  return (card?.tables ?? []).flatMap((t) => t.values.filter((v) => v.labels.subject && inConflicts(v)).map((v) => ({
    arm: v.entity.arm ?? "", analyte: v.labels.analyte ? normLabel(v.labels.analyte) : v.entity.analyte ?? "",
    pair: seriesKey(v), sha: v.file_sha256 ?? t.file_sha256,
  })));
}

/** Whether two values (`seriesKey`: "subject · period · matrix · field") would be one series: the same subject and field,
 *  and the same period and matrix or one of them stating none (a file that gives no period holds the subject in every
 *  period, as the ledger reads it). A urine file and a plasma file of one study's subjects are two series. */
export function pairsMeet(a: string, b: string): boolean {
  const [sa, pa = "", ma = "", fa = ""] = a.split(" · "), [sb, pb = "", mb = "", fb = ""] = b.split(" · ");
  const any = (x: string, y: string) => !x || !y || x === y;
  return sa === sb && fa === fb && any(pa, pb) && any(ma, mb);
}
/** Whether two analytes (by name; "" for none stated) can be one: the same name, or one of them stating none. */
const analytesMeet = (a: string, b: string) => !a || !b || a === b;

/** Two files (or two files' tables) linked to one study in the same arm (no arm counts as one) whose values would be
 *  one series in the ledger (the same subject, period, matrix and field, `pairsMeet`, with the same analyte): refused
 *  before anything is sent, each needs its own arm (plan §2.2.2; the API refuses the same with 409, review INT-4). A
 *  period, a matrix or an analyte left out matches any: "as the file says" is the file's own analyte, or any when the
 *  file states none. Tables of one file are not compared with each other (the file reads them together), nor with what
 *  the study holds of that file. `existing`: what each study already holds (`heldBy` its card), compared by the same
 *  rule. An analyte is compared by its name (`analytes`: the delivery's, to name a chosen one): the delivery gives each
 *  file's analyte an entity of its own, so the two arms' files of one study that both name Exampleamide carry two ids of
 *  one analyte. Only what the link brings together is compared: values that stay where they are (in that study and arm
 *  already, their analyte kept or first stated) are not compared with what they sit beside already (final review INT-4). */
export function collisions(picked: { row: LinkPiece; target: LinkTarget }[], studies: SubjectRow[], existing: Held = {},
                           analytes: Entity[] = []): Collision[] {
  const named = (id: string) => normLabel(analytes.find((a) => a.id === id)?.label ?? id);
  const analyteOf = (p: { row: LinkPiece; target: LinkTarget }) => {
    const own = p.row.own.analyte;
    if (p.target.analyte === NEW) return normLabel(p.target.newAnalyte);
    if (!p.target.analyte) return own ? normLabel(own.label) : "";
    return own?.id === p.target.analyte && !analytes.some((a) => a.id === own.id) ? normLabel(own.label) : named(p.target.analyte);
  };
  /** every value already in the target's study and arm, with no analyte or one of the name it is linked with now */
  const staysOf = (p: { row: LinkPiece; target: LinkTarget }, analyte: string) => p.target.study !== NEW && p.target.arm !== NEW
    && p.row.values.length > 0 && p.row.values.every((v) => v.entity.study === p.target.study && (v.entity.arm ?? "") === p.target.arm
      && (!v.entity.analyte || named(v.entity.analyte) === analyte || (p.row.own.analyte?.id === v.entity.analyte && normLabel(p.row.own.analyte.label) === analyte)));
  const groups = new Map<string, { row: LinkPiece; target: LinkTarget; arm: string; analyte: string; stays: boolean }[]>();
  for (const p of picked.filter((x) => x.target.study && x.row.pairs.length)) {
    const arm = choiceKey(p.target.arm, p.target.newArm);
    const key = `${choiceKey(p.target.study, p.target.newStudy)}|${arm}`;
    const analyte = analyteOf(p);
    groups.set(key, [...(groups.get(key) ?? []), { ...p, arm, analyte, stays: staysOf(p, analyte) }]);
  }
  const out: Collision[] = [];
  const say = (pair: string) => { const [s, period] = pair.split(" · "); return `subject ${s}${period ? `, period ${period}` : ""}`; };
  /** the first pair of `mine` that one of `theirs` meets, said with its period when either states one */
  const shared = (mine: string[], theirs: string[]) => {
    for (const p of mine) {
      const q = theirs.find((x) => pairsMeet(p, x));
      if (q !== undefined) return p.split(" · ")[1] ? p : q;
    }
    return undefined;
  };
  for (const list of groups.values()) {
    const t = list[0].target;
    const study = t.study === NEW ? t.newStudy.trim() : studies.find((s) => s.subject === t.study)?.label ?? t.study;
    for (let i = 0; i < list.length; i += 1) {
      for (let j = i + 1; j < list.length; j += 1) {
        if (list[i].row.sha === list[j].row.sha || (list[i].stays && list[j].stays) || !analytesMeet(list[i].analyte, list[j].analyte)) continue;
        const both = shared(list[i].row.pairs, list[j].row.pairs);
        if (both) out.push({ files: [list[i].row.name, list[j].row.name], study, example: say(both), keys: [list[i].row.key, list[j].row.key] });
      }
      const held = t.study === NEW || list[i].stays ? [] : (existing[t.study] ?? [])
        .filter((v) => v.arm === list[i].arm && analytesMeet(v.analyte ? named(v.analyte) : "", list[i].analyte) && v.sha !== list[i].row.sha);
      const there = shared(list[i].row.pairs, held.map((v) => v.pair));
      if (there) out.push({ files: [list[i].row.name], study, example: say(there), keys: [list[i].row.key] });
    }
  }
  return out;
}

/** Loose numbers alike, said once: the same words but for their digits, in one sheet or on one page ("12 like “vessel_1”
 *  … “vessel_12”" in "sheet Dissolution, cells N1 to Y1"). */
export type LooseGroup = { key: string; label: string; place: string; items: Outside[] };

export function looseGroups(outside: Outside[]): LooseGroup[] {
  const groups = new Map<string, Outside[]>();
  for (const o of outside) {
    const where = /^s:'((?:[^']|'')+)'!/.exec(o.where)?.[1] ?? /^p:(\d+)\//.exec(o.where)?.[1] ?? "";
    const key = `${where}|${o.text === null ? "" : o.text.replace(/\d+/g, "#")}`;
    groups.set(key, [...(groups.get(key) ?? []), o]);
  }
  return [...groups.entries()].map(([key, list]) => {
    const first = list[0], last = list[list.length - 1];
    const label = first.text === null ? `${plural(list.length, "loose number")} (${WITHHELD})`
      : list.length === 1 ? `“${first.text}”` : `${list.length} like “${first.text}” … “${last.text}”`;
    const cells = list.map((o) => /!([A-Z]{1,3}[0-9]+)$/.exec(o.where)?.[1]).filter(Boolean);
    const sheet = /^s:'((?:[^']|'')+)'!/.exec(first.where)?.[1]?.replace(/''/g, "'");
    const place = list.length === 1 ? placeText(first.where)
      : sheet && cells.length === list.length ? `sheet ${sheet}, cells ${cells[0]} to ${cells[cells.length - 1]}`
        : [...new Set(list.map((o) => whereIs(o.where).name))].join(", ");
    return { key, label, place, items: list };
  });
}

/** A file's numbers not read, by what a person does about them: loose numbers (alike ones together) to mark as not
 *  data, the notes a person marked as not data (to restore), tables and texts not read (to read or mark), tables with
 *  numbers no column picks up (their layout to correct), and why the file could not be read. */
export type NotReadRow = {
  item: WorkItem; file: DeliveryFile; loose: LooseGroup[]; marked: Outside[]; unread: Region[]; silent: Region[]; failed: string | null;
  /** its studies and products are all confirmed with the sheet form: a read table can be set aside whole (`WorkItem.elsewhere`) */
  elsewhere: boolean;
};

export function notReadRows(items: WorkItem[], page: DeliveryPage | null): NotReadRow[] {
  if (!page?.enabled) return [];
  const files = page.deliveries.flatMap((d) => d.files);
  return items.filter((i) => i.id.startsWith("notread:") && i.ref).flatMap((item) => {
    const file = files.find((f) => f.sha256 === item.ref && !f.repeat) ?? files.find((f) => f.sha256 === item.ref);
    if (!file) return [];
    const state = new Map(file.regions.map((r) => [r.region_id, r.state]));
    // a note no longer counted beside no table, or beside one no layout reads, was marked as not data by a person
    const marked = file.outside.filter((o) => !o.counted && !(o.region !== null && ["mapped", "waiting"].includes(state.get(o.region) ?? "")));
    const failed = ["failed", "unreadable", "unsupported"].includes(file.state) ? file.reason || "it could not be read" : null;
    return [{ item, file, loose: looseGroups(file.outside.filter((o) => o.counted)), marked, failed, elsewhere: Boolean(item.elsewhere),
              unread: file.regions.filter((r) => r.state === "unread"), silent: file.regions.filter((r) => r.state === "mapped" && r.silent > 0) }];
  });
}

/** A table layout to check in To do's queue: its row of the delivery page, whether it reads its table as not data
 *  (those can be approved together), and whether what it reads is kept but not used by the model (excretion: kept in
 *  the record, no dataset is made from it; intake check EXCRETION_NOT_LANDED). */
export type LayoutRow = { item: WorkItem; mapping: MappingRow; notData: boolean; kept: boolean };

export function layoutRows(items: WorkItem[], page: DeliveryPage | null): LayoutRow[] {
  if (!page?.enabled) return [];
  return items.filter((i) => i.id.startsWith("layout:")).flatMap((item) => {
    const [id, version] = item.id.slice("layout:".length).split("@");
    const mapping = page.mappings.find((m) => m.mapping_id === id && m.version === Number(version));
    return mapping ? [{ item, mapping, notData: mapping.kind === "not_data", kept: mapping.kind === "excretion" }] : [];
  });
}

/** A layout's columns in one line, alike neighbours together ("subject ← 'Subject' · period ← 'Period' · concentration
 *  ← 11 columns '0.5' … '24'"), the columns it does not read counted at the end. */
export function columnSummary(columns: { column: number; header: string | null; role: string; field: string | null }[]): string {
  const said = (c: (typeof columns)[number]) => (c.field ?? c.role).replace(/_/g, " ");
  const head = (c: (typeof columns)[number]) => `'${c.header ?? `column ${c.column}`}'`;
  const read = columns.filter((c) => c.role !== "ignore");
  const parts: string[] = [];
  for (let i = 0; i < read.length;) {
    let j = i;
    while (j + 1 < read.length && said(read[j + 1]) === said(read[i])) j += 1;
    parts.push(j === i ? `${said(read[i])} ← ${head(read[i])}` : `${said(read[i])} ← ${j - i + 1} columns ${head(read[i])} … ${head(read[j])}`);
    i = j + 1;
  }
  const ignored = columns.length - read.length;
  return [...parts, ignored ? `${plural(ignored, "column")} not read` : ""].filter(Boolean).join(" · ") || "no column is read";
}

/** What a batch of "Mark as not data" did, said once (review CODE-10): one file by its name and its loose numbers
 *  ("OJ-101 plasma means.xlsx: “Note: …” marked as not data."), several collapsed ("45 loose numbers in 3 files marked
 *  as not data: a.xlsx (12), b.xlsx (30), c.xlsx (3)."), then what is left and the files a refusal kept back. */
export function markedText(done: { file: string; groups: LooseGroup[] }[], left: number, refused = 0): string {
  const count = (g: LooseGroup[]) => g.reduce((n, x) => n + x.items.length, 0);
  const said = !done.length ? "" : done.length === 1 ? `${done[0].file}: ${done[0].groups.map((g) => g.label).join(", ")} marked as not data.`
    : `${plural(done.reduce((n, d) => n + count(d.groups), 0), "loose number")} in ${plural(done.length, "file")} marked as not data: `
      + `${done.map((d) => `${d.file} (${count(d.groups)})`).join(", ")}.`;
  const rest = done.length ? (left ? ` ${plural(left, "loose number")} left.` : " No loose number is left.") : "";
  return `${said}${rest}${refused ? `${said ? " " : ""}${plural(refused, "file")} not marked: see ${refused === 1 ? "its row" : "their rows"}.` : ""}`;
}

/** What a Restore of notes marked in this visit did, said on the line that said what was marked (gate-todo review: that
 *  line, "No loose number is left", no longer held once they were back): "“Note: …” in messy-delivery.xlsx restored: back
 *  in To do, to decide again." */
export function restoredText(label: string): string {
  return `${label.charAt(0).toUpperCase()}${label.slice(1)} restored: back in To do, to decide again.`;
}

/** The cells a sheet-form draft's own words name as neither a value nor marked (sheet_form: "Cells say '12.3*',
 *  '>1000': mark them as 'no sample' or correct the file."), to set as "no sample" when the sheet is read (review OWN-2 c). */
export function noSampleCells(texts: string[]): string[] {
  const out: string[] = [];
  for (const text of texts) {
    const said = /Cells say (.+?): mark them as 'no sample' or correct the file/.exec(text)?.[1];
    if (!said) continue;
    for (const m of said.matchAll(/'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g)) {
      const token = (m[1] ?? m[2] ?? "").replace(/\\(.)/g, "$1");
      if (token && !out.includes(token)) out.push(token);
    }
  }
  return out;
}
