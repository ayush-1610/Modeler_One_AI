"use client";

// The Delivery section's shared pieces (contracts 2026-11-12 §8.10): the answers' types, how a value and the tuple it
// is read with are written, and the small form every decision that needs a reason is made with. A blinded study's
// value is never written: the API withholds it (D-15), and the page says so in its place.

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { ReasonForm } from "@/components/kit/Reason";
import type { Envelope, Schema } from "@/lib/api";
import {
  alreadyDecidedText, checkGist, checkText, conditionsInWords, engineWords, labelWord, layoutFieldText, whereIs,
} from "@/lib/words";
import { useMutation, type After, type Outcome, type Read } from "@/lib/hooks";

import { cardAfter, pageKey, writePage } from "./writes";

export type Page = Schema<"DeliveryPage">;
export type FileRow = Schema<"DeliveryFile">;
export type Region = Schema<"DeliveryRegion">;
export type SubjectRow = Schema<"DeliverySubjectRow">;
export type Subject = Schema<"DeliverySubject">;
export type Value = Schema<"DeliveryValue">;
export type MappingRow = Schema<"DeliveryMappingRow">;
export type Blocker = Schema<"DeliveryBlocker">;
export type Rules = Schema<"DeliveryRules">;
export type SubjectKind = SubjectRow["subject_type"];

/** What stands in place of a blinded study's value, everywhere. */
export const WITHHELD = "withheld (blinded)";

export const plural = (n: number, word: string, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;
export const when = (iso: string | null | undefined) => (iso ? iso.slice(0, 16).replace("T", " ") : "");
const words = (text: string) => text.replace(/_/g, " ");

export const KIND_LABEL: Record<SubjectKind, string> = { study: "Study", product: "Product", compound: "Compound" };

/** What a blocker holds, in words (final review round 6: the confirm dialog said the API's detail as written, "2 failed
 *  checks: ABOVE_RANGE, LANDING_FIELD_MISSING", and a fact not stated by its field's id): the failed checks by what each
 *  says (`words.checkText`, the card's words; their count only for a blinded subject, whose messages are withheld), the
 *  facts not stated by their reasons; any other detail with its engine terms replaced. */
export function blockerDetail(b: Blocker, s: Subject): string {
  if (b.code === "CHECK_FAILED") {
    const said = s.checks.filter((c) => b.ids.includes(c.id) && c.message !== null)
      .map((c) => checkGist(checkText({ ...c, message: c.message as string })).gist);
    const n = b.ids.length || s.checks.filter((c) => c.severity === "fail" && !c.overridden).length;
    return said.length ? `${plural(n, "check")} to decide: ${[...new Set(said)].join("; ")}` : `${plural(n, "check")} to decide, on the card`;
  }
  if (b.code === "SCHEMA_GAP" && s.gaps.length) return [...new Set(s.gaps.map((g) => g.reason))].join("; ");
  return engineWords(b.detail);
}

/** A file's state in words (`DeliveryFile.state`). */
export const FILE_STATE: Record<string, { label: string; tone: string }> = {
  read: { label: "read", tone: "low" }, partly_read: { label: "partly read", tone: "medium" },
  unsupported: { label: "not supported", tone: "high" }, unreadable: { label: "not readable", tone: "high" },
  failed: { label: "failed", tone: "high" }, waiting: { label: "waiting", tone: "neutral" },
  not_read: { label: "not read", tone: "medium" },
};

/** A region's state in words (`DeliveryRegion.state`). */
export const REGION_STATE: Record<Region["state"], { label: string; tone: string }> = {
  mapped: { label: "read", tone: "low" }, excluded: { label: "set aside", tone: "neutral" },
  unread: { label: "not read", tone: "high" }, waiting: { label: "waiting", tone: "medium" },
};

/** A mapping version's status in words. */
export const MAPPING_STATE: Record<string, { label: string; tone: string }> = {
  approved: { label: "approved", tone: "low" }, proposed: { label: "waits for approval", tone: "medium" },
  rejected: { label: "rejected", tone: "high" },
};

// --- where a thing is in its file, in words -------------------------------------------------------------------------

/** A table by its short name and its file, for a button's label: "the table Sheet1 of 230-23 Fasting Reference.xlsx";
 *  a name that already says what it is ("table 1", "page 3, figure 2", "paragraphs 4 to 6") is not said twice. */
export function tableName(where: string, file: string, kind = "table"): string {
  const name = whereIs(where).name;
  const word = kind === "prose" ? "text" : kind === "figure" ? "figure" : "table";
  return /^(table|figure|paragraphs?|lines?|page) /.test(name) ? `${name} of ${file}` : `the ${word} ${name} of ${file}`;
}

/** What blocks a confirmation, in words (`DeliveryBlocker.code`); the API's own detail follows it. */
export const BLOCKER_LABEL: Record<string, string> = {
  SILENT_LOSS: "Not everything was read",
  OUTSIDE_NUMBERS: "Numbers outside every table",
  UNASSIGNED_VALUES: "Values with no study stated",
  SCHEMA_GAP: "A fact the study needs is not stated",
  CHECK_FAILED: "Failed checks",
  LINK_UNCONFIRMED: "A link between files waits",
  SPOT_CHECK: "Spot check",
  LOADED_ON_CLIENT_REVIEW: "Loaded from its card already",
  BLINDED: "Blinded study",
};

export function ChipFor({ state, table, testId }: { state: string | null | undefined; table: Record<string, { label: string; tone: string }>; testId?: string }) {
  if (!state) return null;
  const known = table[state];
  return <span className={`chip ${known?.tone ?? "neutral"}`} data-testid={testId}>{known?.label ?? words(state)}</span>;
}

// --- a value and the tuple it is read with ----------------------------------------------------------------------------

/** A number as the page writes it: as stored. Only a number code computed with a float's full length (an SD derived
 *  from an SE: 0.5143928459844673) is cut, to eight significant digits; no file writes a value that long. */
export const num = (x: number) => (String(x).replace(/[-.]/g, "").length > 12 ? String(Number(x.toPrecision(8))) : String(x));

/** The value as the ledger holds it: the number or text, "below the LLOQ" for a censored one, never a blinded one. */
export function valueText(v: Value): string {
  if (v.blinded) return WITHHELD;
  if (v.censored) return v.lloq !== null ? `below the LLOQ (${num(v.lloq)}${v.lloq_unit ? ` ${v.lloq_unit}` : ""})` : "below the LLOQ";
  if (v.value === null) return v.verbatim ?? "no value";
  return typeof v.value === "number" ? num(v.value) : String(v.value);
}

export const timeText = (v: Value) => (v.time === null ? "" : `${num(v.time)}${v.time_unit ? ` ${v.time_unit}` : ""}`);

/** The spread, n and interval stated with the value. */
export function spreadText(v: Value): string {
  return [
    v.spread !== null ? `± ${num(v.spread)}${v.spread_kind ? ` ${v.spread_kind}` : ""}` : "",
    v.interval ? `${v.interval_level !== null ? `${v.interval_level} % ` : ""}${v.interval_kind ?? "interval"} ${num(v.interval[0])} to ${num(v.interval[1])}` : "",
    v.n_at !== null ? `n ${v.n_at}` : "",
  ].filter(Boolean).join(" · ");
}

/** The labels a value is read with, as written in its file: "study 230-23 · analyte Exampleamide". */
export const labelsText = (v: Value) => Object.entries(v.labels).map(([role, label]) => labelWord(role, label)).join(" · ");

/** The conditions a value is read under, in words ("interval 0 to 4 h"), never the intake's field ids. */
export const conditionsText = (v: Value) => conditionsInWords(v.conditions);

/** A kind or a state the API sends as an id, its underscores turned to spaces ("pk summary"). */
export const fieldText = (field: string) => words(field);
/** A value's field as a values table's Field column says it: the intake vocabulary's words ("Amount excreted",
 *  "Cmax (PK parameter)"), never its id (`excretion.amount`; final review round 5, A11Y-7). */
export const valueField = (field: string) => layoutFieldText(field);
export const statisticText = (v: Value) => (v.statistic ? words(v.statistic) : "");
/** How a value was read (`DeliveryValue.level`, the evidence levels in ascending order), in words. */
const LEVEL: Record<string, string> = {
  digitized: "digitized from a figure", prose: "read from text", new_mapping: "by a table layout not approved yet",
  approved_mapping: "by an approved table layout", person_confirmed: "entered or confirmed by a person",
};
export const levelText = (level: string) => LEVEL[level] ?? words(level);

/** What a text typed for a value is sent as: a plain number as a number, anything else as written. */
export function typed(text: string): string | number {
  const t = text.trim();
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : t;
}

// --- decisions ------------------------------------------------------------------------------------------------------------

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;

/** The section's resources (the page, the cards, the mappings) read again. */
const readAgain = (client: QueryClient) => client.invalidateQueries({
  predicate: (q) => typeof q.queryKey[0] === "string" && q.queryKey[0].startsWith(DELIVERY),
});

/** A decision's outcome, with the code of the API's refusal (`CONFLICT`: the server moved on). */
export type Decided<T> = Outcome<T> & { code: string | null };

/** A change made on the section: `decide(() => send(...), after)` answers its outcome and keeps the API's refusal to
 *  show; `after` says what the decision made stale (its answer written into the page, `writes.ts`). A refusal that says
 *  the server moved on (409 `CONFLICT`: another reviewer decided first, a name exists already) is shown in the server's
 *  words and the section is read again, so the item shows what holds now (plan 2026-11-14 §2.2.6). */
export function useDecide() {
  const mutation = useMutation();
  const client = useQueryClient();
  const [problem, setProblem] = useState<string | null>(null);
  const decide = useCallback(async <T,>(call: () => Promise<Envelope<T>>, after: After<T>): Promise<Decided<T>> => {
    let code: string | null = null;
    let decided: unknown = null;
    const out = await mutation.run(async () => {
      const env = await call();
      code = (env.errors?.[0]?.detail?.code as string | undefined) ?? null;
      decided = env.errors?.[0]?.detail?.decided ?? null;
      return env;
    }, after);
    // a decision someone made already: who made it, when and why, never the line's id or a raw place (INT-11)
    const problem = code === "CONFLICT" ? alreadyDecidedText(decided) ?? out.problem : out.problem;
    setProblem(problem);
    if (code === "CONFLICT") void readAgain(client);
    return { ...out, problem, code };
  }, [mutation, client]);
  return { decide, busy: mutation.busy, problem, clear: () => setProblem(null) };
}

/** A decision on a subject's card (`:enter`, `:override`, `:dispose`, `:choose`, `:link`): its answer, the card, is
 *  written into the page and the delivery page is read again once (`writes.ts` `cardAfter`), so it costs two requests;
 *  more only when it changed another subject's row (a study blinded with the products that hold its values), whose card
 *  is read again then. The page is compared with what it was when the decision was sent. `reads`: what else the decision
 *  changed, read again with it (a study's purpose: `PURPOSE_READS`). */
export type CardDecide = (call: () => Promise<Envelope<Subject>>, reads?: readonly Read[]) => Promise<Decided<Subject>>;

export function useCardDecide(projectId: string) {
  const { decide, busy, problem, clear } = useDecide();
  const client = useQueryClient();
  const onCard: CardDecide = useCallback(
    (call, reads) => decide(call, { ...cardAfter(projectId, { before: client.getQueryData<Page>(pageKey(projectId)) }), reads }),
    [decide, client, projectId]);
  return { decide: onCard, busy, problem, clear };
}

/** What a decision the delivery page answers made stale (`values:assign`, `regions:exclude`, `regions:restore`): the
 *  page, written (`writePage`). */
export const pageAfter = (projectId: string): After<Page> => ({ write: (page, client) => writePage(client, projectId, page) });

/** Write a decision's answer (the page, which `values:assign`, `regions:exclude` and `regions:restore` return) into
 *  the page's cache instead of reading everything again (plan 2026-11-14 §2.1): only the cards of the subjects the
 *  decision changed are read again (`writes.ts`, slice 4). */
export function useWritePage(projectId: string) {
  const client = useQueryClient();
  return useCallback((page: Page) => writePage(client, projectId, page), [client, projectId]);
}

/** A decision with its reason: what the API asks `why` for. The reason is kept on the audit trail. The kit's
 *  `ReasonForm` (plan 2026-11-14 slice 4): suggestion chips and "use last" fill the field, never send it; pressed with
 *  the reason or another choice missing, it says what is missing. */
export const Why = ReasonForm;

/** A refusal shown where the decision was made. */
export function Problem({ text, testId }: { text: string | null; testId?: string }) {
  if (!text) return null;
  return <p className="delivery-problem" role="alert" data-testid={testId}>{text}</p>;
}

/** The tuple a value is read with, as table cells: the value, its unit, its time, its labels and its statistic. */
export function TupleCells({ v }: { v: Value }) {
  const spread = v.blinded ? "" : spreadText(v);
  return (
    <>
      <td className={v.blinded ? "delivery-withheld-cell" : "num"} data-testid={`tuple-value-${v.id}`}>
        {valueText(v)}
        {spread && <div className="muted fs-12">{spread}</div>}
      </td>
      <td>{v.unit ?? ""}</td>
      <td className="num">{timeText(v)}</td>
      <td>{labelsText(v)}{Object.keys(v.conditions).length > 0 && <div className="muted fs-12">{conditionsText(v)}</div>}</td>
      <td>{statisticText(v)}</td>
    </>
  );
}

export const TUPLE_HEADS = (
  <><th className="num">Value</th><th>Unit</th><th className="num">Time</th><th>Labels</th><th>Statistic</th></>
);
