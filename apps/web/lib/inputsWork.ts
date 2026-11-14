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
  AREA_NAME, type Status, type Tab, checkFix, checkLabel, layoutOrigin, placeText, plural, tableKindText, todoLabel, whenText,
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
export type WorkSources = {
  inputs: InputsLike | null; review: ReviewPage | null; delivery: DeliveryPage | null; files?: FileLike[];
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
  tidy: "Clean-up in files whose data are confirmed with the sheet form: it holds up nothing; tidy it for the delivery record.",
  done: "Confirmed and in the model.",
};

/** Where an item is settled: the area, and the element (its data-testid) to bring into view there. `subject` opens a
 *  delivery subject's card; `file` opens a client file's row. */
export type Where = { tab: Tab; anchor?: string; subject?: string; file?: string };

export type WorkItem = {
  /** stable: layout:<mapping id> · link:<sha> · alias:<group id> · notread:<sha> · todo:<kind>:<target> ·
   *  draft:<item id> · issue:<group id>:<issue id> · confirm:<subject key> */
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
  next: WorkItem | null;
  ask: AskLine[];
  checks: CheckLine[];
  inModel: InModel;
  /** every model check passes and nothing is open */
  ready: boolean;
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
    const done = path === "delivery" ? Boolean(c?.current && c.landed)
      : path === "sheet-form" ? joined.every((g) => g.state === "confirmed") : false;
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

/** A file's id in the Unassigned list of the delivery review (its table, or its facts): the anchor of its link form. */
export const unassignedAnchor = (valueId: string, sha: string | null) =>
  `delivery-unassigned-${(valueId.includes("#") ? valueId.split("#")[0] : `facts:${sha ?? "entered"}`).replace(/[^A-Za-z0-9-]/g, "-")}`;

// --- the work ------------------------------------------------------------------------------------------------------------

/** The items that are a file's own work (counted on its row in Client files). */
const FILE_WORK = /^(layout|link|alias|notread|draft):/;
const DECIDE = new Set(["conflict", "correct", "pka", "review", "formulation", "process", "unit"]);
/** The to-do kinds settled inline in To do with their own form (the compound's values: the S0 batch, plan §2.1). */
export const INLINE_TODO = new Set(["missing", "conflict", "correct", "pka", "review"]);

/** Every open item once, with every count read from them. */
export function buildWork({ inputs, review, delivery, files = [] }: WorkSources): WorkModel {
  const on = Boolean(delivery?.enabled);
  const deliveryFiles = on ? delivery!.deliveries.flatMap((d) => d.files) : [];
  const bySha = new Map(files.map((f) => [f.sha256, f] as const));
  const firstOf = new Map<string, DeliveryFile>();
  for (const f of deliveryFiles) if (!f.repeat && !firstOf.has(f.sha256)) firstOf.set(f.sha256, f);
  for (const f of deliveryFiles) if (!firstOf.has(f.sha256)) firstOf.set(f.sha256, f);
  const fileOf = (sha: string) => bySha.get(sha)?.id ?? firstOf.get(sha)?.legacy_sid ?? `sha:${sha}`;
  const nameOf = (sha: string) => bySha.get(sha)?.file ?? firstOf.get(sha)?.name ?? "a file";
  const rowAnchor = (sha: string) => `inputs-file-${nameOf(sha)}`;
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

  // the delivery's subjects confirmed on the delivery and not yet signed: the delivery-wide clean-up holds them up
  // (SILENT_LOSS, OUTSIDE_NUMBERS, UNASSIGNED_VALUES gate every confirmation of the delivery's subjects)
  const holding = (deliveryIds: string[]) => subjects.filter((s) => s.path === "delivery" && !s.done && !s.blinded
    && s.row!.deliveries.some((d) => deliveryIds.includes(d))).map((s) => s.key);
  const tidyNote = "Every study and product of this delivery is confirmed with the sheet form: this holds up nothing.";

  // 1 · table layouts to check
  for (const m of on ? delivery!.mappings.filter((x) => x.status === "proposed") : []) {
    const shas = [...new Set(m.used_in.map((u) => u.file_sha256))];
    const blocks = holding(shas.map((s) => firstOf.get(s)?.delivery ?? ""));
    const first = m.used_in[0];
    const where = first ? `${first.file} (${placeText(first.where)})` : "no file uses it now";
    const more = shas.length > 1 ? ` and ${plural(shas.length - 1, "more file")}` : "";
    add({
      id: `layout:${m.mapping_id}`, group: blocks.length ? "layouts" : "tidy", status: "to_decide", area: "files",
      label: `${capital(tableKindText(m.kind))} · ${where}${more}`, detail: `${layoutOrigin(m.origin)} · version ${m.version}`,
      where: { tab: "files", anchor: `delivery-mapping-${m.mapping_id}` }, pipeline: "delivery",
      blocked: m.waiting ? "Being read again: it can be checked once the reading ends." : undefined,
      files: shas.map(fileOf), subjects: blocks, weight: m.used_in.length,
    });
  }

  // 2 · values to link to a study or product, one row per file; a file the sheet form read under a name that only starts
  // with a delivery study's ("230-23-REF" beside "230-23") asks "Same study as 230-23?" in its place (no silent merge)
  const unassigned = on ? delivery!.unassigned : [];
  const sheetNames = new Map<string, Subject>();
  for (const s of subjects) if (!s.row && s.kind === "study") for (const g of s.groups) for (const sha of groupShas(g)) sheetNames.set(sha, s);
  const studyRows = on ? delivery!.subjects.filter((r) => r.subject_type === "study") : [];
  const linkShas = [...new Set(unassigned.map((v) => v.file_sha256 ?? "entered"))];
  for (const sha of linkShas) {
    const values = unassigned.filter((v) => (v.file_sha256 ?? "entered") === sha);
    const name = sha === "entered" ? "values entered by a person" : nameOf(sha);
    const blocks = holding([...new Set(values.map((v) => v.delivery))]);
    const read = sheetNames.get(sha);
    const alias = read ? prefixAlias(read.label, studyRows) : null;
    const base = {
      group: (blocks.length ? "link" : "tidy") as Group, status: "to_decide" as Status, area: "files" as Tab, pipeline: "delivery" as const,
      where: { tab: "files" as Tab, anchor: unassignedAnchor(values[0].id, values[0].file_sha256) },
      files: sha === "entered" ? [] : [fileOf(sha)], weight: values.length,
    };
    if (alias && read) {
      add({ ...base, id: `alias:${read.key}`, area: "studies", subjects: [read.key, ...blocks],
            label: `Same study as ${alias.label}? ${read.label} · ${name}`,
            detail: `The sheet form read this file as ${read.label}; its ${plural(values.length, "value")} are not linked to a study in the delivery. If it is ${alias.label}, link them to it with their arm.` });
    } else {
      add({ ...base, id: `link:${sha}`, subjects: blocks,
            label: `Link the ${plural(values.length, "value")} of ${name} to a study or product`,
            detail: read ? `The sheet form read it as ${KIND_WORD[read.kind]} ${read.label}.` : undefined });
    }
  }
  // a sheet-form alias whose file the person has linked to the study it starts with: settled
  for (const s of subjects.filter((x) => !x.row && x.kind === "study")) {
    const alias = prefixAlias(s.label, studyRows);
    const shas = s.groups.flatMap(groupShas);
    if (!alias || items.some((i) => i.id === `alias:${s.key}`) || !shas.some((sha) => alias.files.includes(sha))) continue;
    add({ id: `alias:${s.key}`, group: "done", status: "done", area: "studies", pipeline: "delivery", subjects: [s.key],
          label: `Same study as ${alias.label}? ${s.label}`, inModel: `Its file is linked to ${alias.label} in the delivery.`,
          where: { tab: "files", anchor: `delivery-subject-${alias.subject}`, subject: `${alias.subject_type}/${alias.subject}` },
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
    const blocks = holding([f.delivery]);
    add({
      id: `notread:${f.sha256}`, group: blocks.length ? "notread" : "tidy", status: "to_decide", area: "files",
      label: `${f.name}: ${failed ? `could not be read${f.reason ? ` (${f.reason})` : ""}` : parts.join(" · ")}`,
      where: { tab: "files", anchor: rowAnchor(f.sha256), file: fileOf(f.sha256) }, pipeline: "delivery",
      blocked: f.state === "unsupported" ? "Not a kind of file the reader takes." : undefined,
      files: [fileOf(f.sha256)], subjects: blocks, weight: (c?.silent_loss ?? 0) + loose,
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

  // the sheet form's own open items, on subjects it confirms: the issues (settled with the card's own form) and the
  // sheets that do not say a fact (filled in on the card); a subject confirmed on the delivery asks them there instead
  for (const s of subjects.filter((x) => x.path === "sheet-form" && !x.done)) {
    for (const g of s.groups.filter((x) => x.state === "to_confirm")) {
      for (const issue of g.issues.filter((i) => i.selected === null && i.answered === null)) {
        add({ id: `issue:${g.id}:${issue.id}`, group: "disagree", status: "to_decide", area: g.tab as Tab, pipeline: "sheet-form",
              label: `${KIND_WORD[s.kind]} ${s.label}: ${issue.text}`, where: { tab: g.tab as Tab, anchor: `issue-${issue.id}` },
              blocked: s.blinded ? "Blinded until the plan is signed." : undefined,
              files: s.files, subjects: [s.key], weight: 1, issue: { group: g.id, issue: issue.id } });
      }
      for (const i of g.items.filter((x) => x.kind === "draft")) draftItem(add, g, i, `${KIND_WORD[s.kind]} ${s.label}`, [s.key], s.blinded, fileOf);
    }
  }
  // a sheet whose study or product is not stated yet: its card asks for it, and its data join that card once read
  for (const g of (review?.groups ?? []).filter((x) => x.kind === "sheet" && x.state === "to_confirm")) {
    for (const i of g.items.filter((x) => x.kind === "draft")) draftItem(add, g, i, g.title, [], false, fileOf);
  }

  // 0, 6 · the client's data to confirm, one row per card; done ones say what is in the model
  const holdFor = (s: Subject) => {
    if (s.path !== "delivery") return [];
    return items.filter((i) => i.subjects.includes(s.key) && (i.group === "layouts" || i.group === "link" || i.group === "notread"));
  };
  for (const s of subjects) {
    const name = `${KIND_WORD[s.kind]} ${s.label}`;
    const aliases = s.aliases.length ? ` · also read by the sheet form as ${s.aliases.join(", ")}` : "";
    const g = s.groups[0];
    const where: Where = s.path === "sheet-form" && g ? { tab: g.tab as Tab, anchor: `group-${g.id}` }
      : { tab: "files", anchor: `delivery-subject-${s.row!.subject}`, subject: `${s.row!.subject_type}/${s.row!.subject}` };
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
    const open = s.path === "sheet-form" ? s.groups.reduce((n, x) => n + (x.state === "to_confirm" ? x.open : 0), 0) : 0;
    const held = holdFor(s);
    const gate = held.length ? `Waits for the delivery clean-up: ${gateText(held)}` : "";
    const from = fromFiles(s.files);
    const detail = s.path === "delivery"
      ? [from, (c && !c.current ? "changed since it was signed: confirm again" : c && !c.landed ? "signed; the loading is not finished"
        : "confirm and sign on its card") + (gate ? ", once the delivery is cleaned up" : "")].filter(Boolean).join(" · ") + aliases
      : [from, open ? `${plural(open, "thing")} first, on its card` : ""].filter(Boolean).join(" · ") + aliases;
    add({ ...base, id: `confirm:${s.key}`, group: s.path === "sheet-form" && !open ? "ready" : "confirm", status: "to_confirm",
          label: name, detail: detail.replace(/^ · /, "") || undefined, gate: gate || undefined,
          blocked: s.blinded ? "Blinded until the plan is signed: it is confirmed afterwards." : undefined });
  }

  // counted: open, not blocked, and holding something up (the clean-up of a delivery confirmed with the sheet form is not)
  for (const i of items) i.open = i.status !== "done" && !i.blocked && i.group !== "tidy";
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

  const checks = (inputs?.readiness?.content?.checks ?? []).map((c) => ({
    raw: c.check, label: checkLabel(c.check, c.detail, c.ok), ok: c.ok, detail: c.detail, fix: checkFix(c.check),
  }));
  return {
    items, subjects, counts, byArea, byFile, next: open[0] ?? null, ask: askLines(delivery), checks,
    inModel: inModel(inputs), ready: !open.length && Boolean(inputs?.readiness?.content?.ready),
  };
}

function draftItem(add: (i: Omit<WorkItem, "open">) => void, g: ReviewGroup, i: ReviewItem, name: string, subjects: string[],
                   blinded: boolean, fileOf: (sha: string) => string) {
  const draft = i.draft as { sid?: string; needs?: string[]; labels?: Record<string, string> } | null | undefined;
  const needs = (draft?.needs ?? []).map((n) => draft?.labels?.[n] ?? n.replace(/_/g, " "));
  const sha = (i.source as { doc_sha256?: string | null } | null | undefined)?.doc_sha256;
  add({ id: `draft:${i.id}`, group: "missing", status: "missing", area: g.tab as Tab, pipeline: "sheet-form",
        label: g.kind === "sheet" ? `${i.label}: ${needs.length ? `not stated: ${needs.join(", ")}` : "to read"}`
          : `${name} · ${i.label}: ${needs.length ? `not stated: ${needs.join(", ")}` : "to read"}`,
        where: { tab: g.tab as Tab, anchor: `group-${g.id}` }, blocked: blinded ? "Blinded until the plan is signed." : undefined,
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

/** What a confirmed card put in the model: who confirmed or signed it, and when. */
function inModelText(s: Subject): string {
  const c = s.row?.confirmation;
  if (s.path === "delivery" && c) return `Signed by ${c.printed_name || c.by} on ${whenText(c.at)}; in the model.`;
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
