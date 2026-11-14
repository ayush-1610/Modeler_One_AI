"use client";

// The Delivery section's shared pieces (contracts 2026-11-12 §8.10): the answers' types, how a value and the tuple it
// is read with are written, and the small form every decision that needs a reason is made with. A blinded study's
// value is never written: the API withholds it (D-15), and the page says so in its place.

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useState, type ReactNode } from "react";

import type { Envelope, Schema } from "@/lib/api";
import { whereIs } from "@/lib/words";
import { useMutation, type Outcome } from "@/lib/hooks";

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

/** A person's "not data" decision as a region's reason gives it ("rd-3: why"): its id and why; null for a rule's. */
export function personDecision(reason: string): { id: string; why: string } | null {
  const m = /^(rd-\d+): ([\s\S]*)$/.exec(reason);
  return m ? { id: m[1], why: m[2] } : null;
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
export const labelsText = (v: Value) => Object.entries(v.labels).map(([role, label]) => `${role} ${label}`).join(" · ");

export const conditionsText = (v: Value) => Object.entries(v.conditions).map(([k, x]) => `${words(k)} ${x}`).join(" · ");

export const fieldText = (field: string) => words(field);
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
const CARD = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;

/** The section's resources (the page, the cards, the mappings) read again. */
const readAgain = (client: QueryClient) => client.invalidateQueries({
  predicate: (q) => typeof q.queryKey[0] === "string" && q.queryKey[0].startsWith(DELIVERY),
});

/** A decision's outcome, with the code of the API's refusal (`CONFLICT`: the server moved on). */
export type Decided<T> = Outcome<T> & { code: string | null };

/** A change made on the section: `decide(() => send(...))` answers its outcome and keeps the API's refusal to show.
 *  A refusal that says the server moved on (409 `CONFLICT`: another reviewer decided first, a name exists already) is
 *  shown in the server's words and the section is read again, so the item shows what holds now (plan 2026-11-14
 *  §2.2.6). `{ refresh: false }`: the caller writes the answer into the page itself (`useWritePage`). */
export function useDecide() {
  const mutation = useMutation();
  const client = useQueryClient();
  const [problem, setProblem] = useState<string | null>(null);
  const decide = useCallback(async <T,>(call: () => Promise<Envelope<T>>, options?: { refresh?: boolean }): Promise<Decided<T>> => {
    let code: string | null = null;
    const out = await mutation.run(async () => {
      const env = await call();
      code = (env.errors?.[0]?.detail?.code as string | undefined) ?? null;
      return env;
    }, options);
    setProblem(out.problem);
    if (code === "CONFLICT") void readAgain(client);
    return { ...out, code };
  }, [mutation, client]);
  return { decide, busy: mutation.busy, problem, clear: () => setProblem(null) };
}

/** Write a decision's answer (the page, which `values:assign`, `regions:exclude` and `regions:restore` return) into
 *  the page's cache instead of reading everything again (plan 2026-11-14 §2.1): only the cards open on the page are
 *  read again, since what they show follows the decision. */
export function useWritePage(projectId: string) {
  const client = useQueryClient();
  return useCallback((page: Page) => {
    client.setQueryData([DELIVERY, { project_id: projectId }, {}], page);
    void client.invalidateQueries({ predicate: (q) => q.queryKey[0] === CARD });
  }, [client, projectId]);
}

/** A decision with its reason: what the API asks `why` for. The reason is kept on the audit trail. */
export function Why({ action, actionLabel, label, busy, onSubmit, onCancel, testId, optional = false, placeholder, children, disabled = false,
                     autoFocus = false }: {
  action: string;
  /** the button's name with its context, where the same button is repeated ("Link the 4 values of 230-23.xlsx") */
  actionLabel?: string;
  /** what the reason is for, read aloud with the field */
  label: string;
  busy: boolean;
  onSubmit: (why: string) => void | Promise<unknown>;
  onCancel?: () => void;
  testId?: string;
  /** the API takes this decision without a reason */
  optional?: boolean;
  placeholder?: string;
  /** more fields of the decision, before its reason */
  children?: ReactNode;
  disabled?: boolean;
  /** the reason field takes the focus when the form opens (a form opened by a button that then goes away) */
  autoFocus?: boolean;
}) {
  const [why, setWhy] = useState("");
  const ready = (optional || Boolean(why.trim())) && !disabled;
  return (
    <form className="delivery-why" data-testid={testId}
          onSubmit={(e) => { e.preventDefault(); if (ready && !busy) void onSubmit(why.trim()); }}>
      {children}
      <input type="text" aria-label={label} value={why} onChange={(e) => setWhy(e.target.value)} autoFocus={autoFocus}
             placeholder={placeholder ?? (optional ? "a note (optional)" : "why (kept on the audit trail)")}
             data-testid={testId && `${testId}-why`} />
      {/* while the decision is sent the button stays focusable (aria-disabled, the submit ignored): a disabled button
          would drop the focus to the page, out of a dialog */}
      <button type="submit" className="btn small primary" disabled={!ready} aria-disabled={busy || undefined} aria-label={actionLabel}
              data-testid={testId && `${testId}-submit`}>{action}</button>
      {onCancel && <button type="button" className="btn small" onClick={onCancel}>Cancel</button>}
    </form>
  );
}

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
