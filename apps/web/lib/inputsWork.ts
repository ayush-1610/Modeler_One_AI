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
  AREA_NAME, STATUS_WORD, type Status, type Tab, checkFix, checkLabel, factText, layoutOrigin, placeText, plural, tableKindText, todoLabel,
  whenText, whereIs,
} from "./words";

type DeliveryPage = Schema<"DeliveryPage">;
type DeliveryFile = Schema<"DeliveryFile">;
type SubjectRow = Schema<"DeliverySubjectRow">;
type ReviewPage = Schema<"ClientReviewPage">;
type ReviewGroup = Schema<"ReviewGroup">;
type ReviewItem = Schema<"ReviewItem">;

/** An open item of the /inputs to-do (components/inputs/InputsTodo.tsx `TodoItem`), as far as the work model reads it. */
export type TodoLike = { kind: string; target: string; message: string; tab?: string; dataset_id?: string | null };
/** The /inputs page, as far as the work model reads it. */
export type InputsLike = {
  todo: TodoLike[];
  compound: { id: string; state: string; tab: string }[];
  studies: { study_id: string; excluded: string | null; blinded: boolean }[];
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
  conflicts: { id: string; field: string; kind: string; time: number | null }[];
  links: { id: string; state: string; file: string; study_label: string | null }[];
  requirements: { req_id: string; status: string; disposition: string | null; label: string }[];
  spot_check: { state: string };
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
  /** what a file-level item is about: the delivery file's sha256 ("entered" for values a person entered), or the table
   *  layout's id; To do's batch tables (slice 4) build the item's row from it */
  ref?: string;
};

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

export type AskLine = { req: string; what: string; subjects: string[]; required: boolean; why: string };
export type CheckLine = { raw: string; label: string; ok: boolean; detail: string[]; fix: string };
export type Counts = Record<Status, number> & { open: number };
export type InModel = { studies: number; formulations: number; values: number };

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
  const groups = (review?.groups ?? []).filter((g) => g.kind !== "sheet");
  const taken = new Set<string>();
  const out: Subject[] = [];
  for (const row of delivery?.enabled ? delivery.subjects : []) {
    const named = groups.filter((g) => row.legacy_groups.includes(g.id) && !taken.has(g.id));
    const same = groups.filter((g) => !taken.has(g.id) && !named.includes(g) && g.kind === row.subject_type
                                    && normLabel(groupLabel(g)) === normLabel(row.label));
    const joined = [...named, ...same];
    joined.forEach((g) => taken.add(g.id));
    const path: Subject["path"] = row.confirm_on === "delivery" ? "delivery" : joined.length ? "sheet-form" : "read-only";
    const c = row.confirmation;
    // signed and loaded on the delivery, or confirmed with the sheet form (whichever is confirmed first is what loads)
    const sheets = joined.length > 0 && joined.every((g) => g.state === "confirmed");
    const done = path === "delivery" ? Boolean(c?.current && c.landed) || sheets : path === "sheet-form" ? sheets : false;
    const files = [...new Set([...row.files, ...joined.flatMap(groupShas)].map(fileOf))];
    out.push({
      key: joined[0]?.id ?? `${row.subject_type}:${row.label}`, kind: row.subject_type, label: row.label, path, row, groups: joined,
      aliases: joined.map(groupLabel).filter((l) => normLabel(l) !== normLabel(row.label)),
      area: joined[0] ? (joined[0].tab as Tab) : KIND_AREA[row.subject_type], files,
      blinded: row.blinded || (row.subject_type === "study" && blindedStudies.has(normLabel(row.label))), done,
    });
  }
  for (const g of groups.filter((x) => !taken.has(x.id))) {
    const kind = g.kind as Subject["kind"];
    out.push({
      key: g.id, kind, label: groupLabel(g), path: "sheet-form", row: null, groups: [g], aliases: [],
      area: (g.tab as Tab) ?? KIND_AREA[kind], files: groupShas(g).map(fileOf),
      blinded: kind === "study" && blindedStudies.has(normLabel(groupLabel(g))), done: g.state === "confirmed",
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

/** A file's id in the Unassigned list of the delivery review (its table, or its facts): the anchor of its link form. */
export const unassignedAnchor = (valueId: string, sha: string | null) =>
  `delivery-unassigned-${(valueId.includes("#") ? valueId.split("#")[0] : `facts:${sha ?? "entered"}`).replace(/[^A-Za-z0-9-]/g, "-")}`;

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
const CARD_ITEM = /^(fact|need|check|differ|same|hold):/;
/** A card's failed checks counted as another of its rows (a fact not stated, a required item, a disagreement). */
const SETTLED_ELSEWHERE = new Set(["LANDING_FIELD_MISSING", "DOSE_MISSING", "REQUIRED_ITEM_UNDISPOSED", "CONFLICT_OPEN"]);
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
            detail: `The sheet form read this file as ${read.label}; its ${plural(values.length, "value")} are not linked to a study in the delivery. If it is ${alias.label}, link them to it with their arm.` });
    } else {
      add({ ...base, id: `link:${sha}`, subjects: held.subjects,
            label: `Link the ${plural(values.length, "value")} of ${name} to a study or product`,
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
    add({
      id: `notread:${f.sha256}`, group: held.group ?? "notread", status: "to_decide", area: "files",
      label: `${f.name}: ${failed ? `could not be read${f.reason ? ` (${f.reason})` : ""}` : parts.join(" · ")}`,
      where: { tab: "todo", anchor: notReadRowId(f.file_id) }, pipeline: "delivery",
      blocked: f.state === "unsupported" ? "Not a kind of file the reader takes." : undefined, why: held.why,
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
    add({
      id: `todo:${t.kind}:${t.target}`, group: decide ? "disagree" : "missing", status: decide ? "to_decide" : "missing", area: tab,
      label: todoLabel(t.kind, t.target), where: { tab, anchor: `todo-${t.kind}-${t.target}` }, pipeline: "inputs",
      blocked: blinded ? "Blinded until the plan is signed: its facts are set afterwards." : undefined,
      files: [], subjects: [], weight: 1, todo: t,
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
              blocked: s.blinded ? "Blinded until the plan is signed." : undefined, detail: also,
              files: s.files, subjects: [s.key], weight: 1, issue: { group: g.id, issue: issue.id } });
      }
      if (s.path === "delivery") continue;
      for (const i of g.items.filter((x) => x.kind === "draft")) draftItem(add, g, i, `${KIND_WORD[s.kind]} ${s.label}`, [s.key], s.blinded, fileOf, also);
    }
  }
  // a sheet whose study or product is not stated yet: its card asks for it, and its data join that card once read
  for (const g of (review?.groups ?? []).filter((x) => x.kind === "sheet" && x.state === "to_confirm")) {
    for (const i of g.items.filter((x) => x.kind === "draft")) draftItem(add, g, i, g.title, [], false, fileOf);
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
    const failing = card.checks.filter((c) => c.severity === "fail" && !c.overridden);
    const facts = new Map<string, string>();
    for (const g of card.gaps) if (!facts.has(g.tag)) facts.set(g.tag, `delivery-gap-${g.tag}`);
    for (const c of failing) {
      const field = c.code === "LANDING_FIELD_MISSING" ? /needs (\w+)/.exec(c.message ?? "")?.[1] : c.code === "DOSE_MISSING" ? "dose" : undefined;
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
            detail: "Record that it is asked of the client, taken from the literature or not needed.", where: at(`delivery-requirement-${r.req_id}`) });
    }
    for (const c of failing) {
      if (SETTLED_ELSEWHERE.has(c.code) || (c.code === "MAPPING_NOT_APPROVED" && layoutIds.some((id) => c.message?.includes(id)))) continue;
      add({ ...base, id: `check:${s.key}:${c.id}`, group: "disagree", status: "to_decide", label: `${name}: ${c.message ?? "a check failed"}`,
            detail: "A check failed: correct the values, or say why it holds as it is.", where: at(`delivery-check-${c.id}`) });
    }
    for (const x of card.conflicts) {
      add({ ...base, id: `differ:${s.key}:${x.id}`, group: "disagree", status: "to_decide",
            label: `${name}: the files give different ${x.kind === "unit" ? "units" : "values"} for ${x.field.replace(/_/g, " ")}${x.time !== null ? ` at ${x.time}` : ""}`,
            where: at(`delivery-conflict-${x.id}`) });
    }
    for (const l of card.links.filter((x) => x.state !== "refused")) {
      add({ ...base, id: `same:${s.key}:${l.id}`, group: "disagree", status: "to_decide", label: `${name}: is ${l.file} about the same study?`,
            detail: `It names ${l.study_label ? `study ${l.study_label}` : "a study"} in its text.`, where: at(`delivery-link-${l.id.replace(/[^A-Za-z0-9-]/g, "-")}`) });
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
      add({ ...base, id: `confirm:${s.key}`, group: "done", status: "done", label: name, inModel: inModelText(s) });
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
            blocked: s.blinded ? "Blinded until the plan is signed: it is confirmed afterwards." : undefined });
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
          blocked: s.blinded ? "Blinded until the plan is signed: it is confirmed afterwards." : undefined });
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

  const checks = (inputs?.readiness?.content?.checks ?? []).map((c) => ({
    raw: c.check, label: checkLabel(c.check, c.detail, c.ok), ok: c.ok, detail: c.detail, fix: checkFix(c.check),
  }));
  return {
    items, subjects, counts, byArea, byFile, fileWork, next: open[0] ?? null, ask: askLines(delivery), checks,
    inModel: inModel(inputs), ready: !open.length && !checking && Boolean(inputs?.readiness?.content?.ready), checking,
  };
}

function draftItem(add: (i: Omit<WorkItem, "open">) => void, g: ReviewGroup, i: ReviewItem, name: string, subjects: string[],
                   blinded: boolean, fileOf: (sha: string) => string, detail?: string) {
  const draft = i.draft as { sid?: string; needs?: string[]; labels?: Record<string, string> } | null | undefined;
  const needs = (draft?.needs ?? []).map((n) => draft?.labels?.[n] ?? n.replace(/_/g, " "));
  const sha = (i.source as { doc_sha256?: string | null } | null | undefined)?.doc_sha256;
  add({ id: `draft:${i.id}`, group: "missing", status: "missing", area: g.tab as Tab, pipeline: "sheet-form",
        label: g.kind === "sheet" ? `${i.label}: ${needs.length ? `not stated: ${needs.join(", ")}` : "to read"}`
          : `${name} · ${i.label}: ${needs.length ? `not stated: ${needs.join(", ")}` : "to read"}`,
        where: { tab: g.tab as Tab, anchor: `group-${g.id}` }, blocked: blinded ? "Blinded until the plan is signed." : undefined, detail,
        files: draft?.sid ? [draft.sid] : sha ? [fileOf(sha)] : [], subjects, weight: 1 });
}

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
 *  proposed and not yet confirmed is counted. */
export function inModel(inputs: InputsLike | null): InModel {
  const kept = (inputs?.compound ?? []).filter((r) => r.state === "kept");
  return {
    studies: (inputs?.studies ?? []).filter((s) => !s.excluded).length,
    formulations: new Set(kept.filter((r) => /^form\.[^.]+\.type$/.test(r.id)).map((r) => r.id.split(".")[1])).size,
    values: kept.filter((r) => r.tab === "compound").length,
  };
}

/** What only the client can send, one line per requirement with the subjects it is asked for. */
export function askLines(delivery: DeliveryPage | null): AskLine[] {
  const out = new Map<string, AskLine>();
  for (const line of delivery?.enabled ? delivery.request : []) {
    const [what, subject] = line.what.split(" — ");
    const key = `${line.req_id}|${what}`;
    const known = out.get(key) ?? { req: line.req_id, what, subjects: [], required: line.required, why: line.why };
    const name = subject?.replace(/^(study|product) /, "");
    if (name && !known.subjects.includes(name)) known.subjects.push(name);
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
  /** the subject and period of each individual value ("001 · I") */
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
};

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
   *  name) and why; none while the alias question is open, or when its tables point to different places */
  suggested: { target: LinkTarget; why: string } | null;
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
const pairsOf = (values: Value[]) => [...new Set(values.filter((v) => v.labels.subject).map((v) => `${v.labels.subject} · ${v.labels.period ?? ""}`))];
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
      return {
        key: `${sha}#${id}`, sha, name: `${file}, ${place ? `its ${label.split(",")[0]} on ${place}` : label}`, values: vs, pairs: pairsOf(vs),
        own: ownOf(vs), label, place, goesTo: goes,
        suggested: found ? {
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
    const aliasRow = item.id.startsWith("alias:") && sheet ? prefixAlias(sheet, studies) : null;
    const base = { ...NO_TARGET, analyte: own.analyte?.id ?? "" };
    // the tables say where they go: all the same place, or (no table's title names one) the file's name does; tables
    // whose titles point to different places (or one does and another does not) start each in its own place
    const tabled = parts.filter((p) => p.key !== `${sha}#facts`);
    const said = tabled.map((p) => (p.suggested ? destinationKey(p.suggested.target) : ""));
    const split = !aliasRow && tabled.length > 1 && new Set(said).size > 1;
    const inName = said.every((k) => !k) ? fit(file, goesTo === "product" ? products : studies) : undefined;
    const suggested = aliasRow || split ? null : tabled.length && said[0] ? {
      why: `${tabled.length > 1 ? "its tables' titles name" : "its title names"} ${tabled[0].suggested!.why.replace(/^its title names /, "")}`,
      target: { ...tabled[0].suggested!.target, analyte: own.analyte?.id ?? "" },
    } : inName ? {
      why: `its file name names ${KIND_WORD[inName.subject_type].toLowerCase()} ${inName.label}`,
      target: inName.subject_type === "product" ? { ...base, product: inName.subject, batch: own.batch?.id ?? "" }
        : { ...base, study: inName.subject, arm: own.arm?.id ?? "" },
    } : null;
    return { item, key: sha, sha, name: file, fileId: sha === "entered" ? "entered" : f?.file_id ?? `sha-${sha.slice(0, 12)}`, file, values, holds,
             goesTo, own, pairs: pairsOf(values), parts, split, sheet,
             alias: aliasRow ? { study: aliasRow, target: { ...base, study: aliasRow.subject } } : null, suggested, blinded: values.some((v) => v.blinded) };
  });
  // the arm a row's study suggests: the arm its title names; else what sets its name apart from the study's other files,
  // the ones to link here and the ones linked already (so the second file of a pair is told apart from the first, linked
  // one, as the first was from it); else the sheet form's name past the study's
  const named = (sha: string) => fileOf(sha)?.name;
  const studyOf = (r: LinkRow) => r.alias?.study.subject ?? (r.suggested?.target.study || null);
  for (const r of rows) {
    const study = studyOf(r);
    if (!study) continue;
    const row = studies.find((s) => s.subject === study)!;
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

/** What a link still needs before it is sent, in words ("Pick a study or a product"), or null. */
export function targetProblem(t: LinkTarget): string | null {
  if (!t.study && !t.product) return "Pick a study or a product";
  for (const [choice, name, what] of [[t.study, t.newStudy, "study"], [t.arm, t.newArm, "arm"], [t.product, t.newProduct, "product"],
                                      [t.batch, t.newBatch, "batch"], [t.analyte, t.newAnalyte, "analyte"]] as const) {
    if (choice === NEW && !name.trim()) return `Name the new ${what}`;
  }
  return null;
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
/** What a study already holds, by its id: each individual value's arm ("" for none), analyte, pair and file. */
export type Held = Record<string, { arm: string; analyte: string; pair: string; sha?: string | null }[]>;

/** The individual values of a study's card (`/delivery/subjects/study/{id}`), as `collisions` compares them (the analyte
 *  by its name, as `collisions` does). */
export function heldBy(card: { tables: { file_sha256: string | null; values: Value[] }[] } | null | undefined): Held[string] {
  return (card?.tables ?? []).flatMap((t) => t.values.filter((v) => v.labels.subject).map((v) => ({
    arm: v.entity.arm ?? "", analyte: v.labels.analyte ? normLabel(v.labels.analyte) : v.entity.analyte ?? "",
    pair: `${v.labels.subject} · ${v.labels.period ?? ""}`, sha: v.file_sha256 ?? t.file_sha256,
  })));
}

/** Two files (or two files' tables) linked to one study in the same arm (no arm counts as one), with the same analyte,
 *  that hold the same subject in the same period: refused before anything is sent, each needs its own arm (plan
 *  §2.2.2). Tables of one file are not compared with each other (the file reads them together), nor with what the study
 *  holds of that file. `existing`: what each study already holds (`heldBy` its card). An analyte is compared by its
 *  name (`analytes`: the delivery's, to name a chosen one): the delivery gives each file's analyte an entity of its own,
 *  so the two arms' files of one study that both name Exampleamide carry two ids of one analyte. */
export function collisions(picked: { row: LinkPiece; target: LinkTarget }[], studies: SubjectRow[], existing: Held = {},
                           analytes: Entity[] = []): Collision[] {
  const named = (id: string) => normLabel(analytes.find((a) => a.id === id)?.label ?? id);
  const groups = new Map<string, { row: LinkPiece; target: LinkTarget; arm: string; analyte: string }[]>();
  for (const p of picked.filter((x) => x.target.study && x.row.pairs.length)) {
    const arm = choiceKey(p.target.arm, p.target.newArm);
    const analyte = p.target.analyte === NEW ? normLabel(p.target.newAnalyte) : p.target.analyte ? named(p.target.analyte)
      : p.row.own.analyte ? normLabel(p.row.own.analyte.label) : "";
    const key = `${choiceKey(p.target.study, p.target.newStudy)}|${arm}|${analyte}`;
    groups.set(key, [...(groups.get(key) ?? []), { ...p, arm, analyte }]);
  }
  const out: Collision[] = [];
  const say = (pair: string) => { const [s, period] = pair.split(" · "); return `subject ${s}${period ? `, period ${period}` : ""}`; };
  for (const list of groups.values()) {
    const t = list[0].target;
    const study = t.study === NEW ? t.newStudy.trim() : studies.find((s) => s.subject === t.study)?.label ?? t.study;
    for (let i = 0; i < list.length; i += 1) {
      for (let j = i + 1; j < list.length; j += 1) {
        if (list[i].row.sha === list[j].row.sha) continue;
        const shared = list[i].row.pairs.find((p) => list[j].row.pairs.includes(p));
        if (shared) out.push({ files: [list[i].row.name, list[j].row.name], study, example: say(shared), keys: [list[i].row.key, list[j].row.key] });
      }
      const held = t.study === NEW ? [] : (existing[t.study] ?? [])
        .filter((v) => v.arm === list[i].arm && (!v.analyte || !list[i].analyte || named(v.analyte) === list[i].analyte) && v.sha !== list[i].row.sha);
      const shared = list[i].row.pairs.find((p) => held.some((v) => v.pair === p));
      if (shared) out.push({ files: [list[i].row.name], study, example: say(shared), keys: [list[i].row.key] });
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
    return [{ item, file, loose: looseGroups(file.outside.filter((o) => o.counted)), marked, failed,
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
