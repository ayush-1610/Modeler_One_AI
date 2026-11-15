"use client";

// Where one file's values go, edited (contracts 2026-11-12 §8.10; plan 2026-11-14 slice 4): the expanded row of To do's
// link table (components/inputs/todo/LinkTable.tsx), no longer a list of its own. A person links the file's values to a
// study that exists or a new one they name (the ledger never makes a second one of the same name), with its arm, or to
// a product with its batch, and states their analyte: each an existing one or a new one (plan §2.2.2: the Test and the
// Reference file of one study land as two arms). A file with more than one table can send each table (with the facts
// read beside it) to its own place: "Each table to its own place", one set of choices per table, as each table was
// linked before slice 4. A link replaces the earlier one whole, so the form starts from the arm, batch and analyte the
// file (or table) gives its values and sends them again unless the person chooses others. The choice is the row's own
// (the table's bulk bar reads it too); "Link" here sends this file alone. A name that exists already is refused in the
// server's words. Until the values are linked, or their table is marked as not data, they block every confirmation of
// the delivery.

import { useState } from "react";

import { type Schema } from "@/lib/api";
import { NEW, analyteChoice, analyteChoices, normLabel, type LinkPart, type LinkRow, type LinkTarget } from "@/lib/inputsWork";

import { Problem, TUPLE_HEADS, TupleCells, Why, fieldText, plural, type SubjectRow } from "./shared";
import { ValueSource } from "./ValueSource";

const SHOWN = 6;            // values of a file listed before "Show all"
type Entity = Schema<"DeliveryEntity">;

/** A select of existing entities and "A new …", with the new one's name beside it when chosen. */
function Choose({ label, value, onChange, named, onNamed, options, none, newWord, testId, newTestId, context }: {
  label: string; value: string; onChange: (v: string) => void; named: string; onNamed: (v: string) => void;
  options: Entity[];
  /** the empty choice's words; left out, there is none */
  none?: string; newWord: string; testId: string; newTestId: string;
  /** what the choice is for, read with the select: "for the 76 values of 230-23.xlsx" */
  context: string;
}) {
  return (
    <>
      <label className="delivery-pick">{label}
        <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={`${label} ${context}`} data-testid={testId}>
          {none !== undefined && <option value="">{none}</option>}
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          <option value={NEW}>{newWord}</option>
        </select>
      </label>
      {value === NEW && (
        <input type="text" aria-label={`The new ${label.toLowerCase()}'s name ${context}`} maxLength={80} value={named}
               placeholder={`the ${label.toLowerCase()}'s name, as the client writes it`} onChange={(e) => onNamed(e.target.value)}
               data-testid={newTestId} />
      )}
    </>
  );
}

/** The arm, batch or analyte choices: the file's own first (as read from it), then the study's or product's. */
function withOwn(own: Entity | null, others: Entity[]): Entity[] {
  return [...(own ? [{ ...own, label: `${own.label} (the file's own)` }] : []), ...others.filter((o) => o.id !== own?.id)];
}

/** The choices of where one file's values go, as fields (the row's editor and the table's bulk bar both read `target`). */
export function TargetFields({ row, target, onTarget, subjects, analytes, keyId, context, used = [], noneAnalyte }: {
  row: Pick<LinkRow, "own">; target: LinkTarget; onTarget: (t: LinkTarget) => void; subjects: SubjectRow[]; analytes: Entity[];
  /** the test ids' key (`link-study-<key>`) */
  keyId: string;
  context: string;
  /** the analyte ids the chosen study's values carry: of two analytes of one name, the one it uses is offered */
  used?: string[];
  /** the analyte's empty choice in words, where the values have no one analyte of their own (the bulk bar's picked files) */
  noneAnalyte?: string;
}) {
  const set = (patch: Partial<LinkTarget>) => onTarget({ ...target, ...patch });
  const studies = subjects.filter((s) => s.subject_type === "study");
  const products = subjects.filter((s) => s.subject_type === "product");
  const arms = withOwn(row.own.arm, studies.find((s) => s.subject === target.study)?.arms ?? []);
  const batches = withOwn(row.own.batch, products.find((p) => p.subject === target.product)?.batches ?? []);
  // one option per analyte's name (review OWN-11), the file's own name marked as its own
  const mine = row.own.analyte ? normLabel(row.own.analyte.label) : null;
  const kinds = analyteChoices(analytes, row.own.analyte, used)
    .map((a) => (normLabel(a.label) === mine ? { ...a, label: `${a.label} (the file's own)` } : a));
  const analyte = analyteChoice(target.analyte, kinds, analytes, row.own.analyte);
  return (
    <span className="link-fields">
      <Choose label="Study" value={target.study} named={target.newStudy} onNamed={(v) => set({ newStudy: v })} none="no study"
              newWord="A new study…" context={context} testId={`link-study-${keyId}`} newTestId={`link-new-study-${keyId}`}
              onChange={(v) => set({ study: v, arm: row.own.arm?.id ?? "", newArm: "" })}
              options={studies.map((s) => ({ id: s.subject, label: s.label }))} />
      {target.study && (
        <Choose label="Arm" value={target.arm} onChange={(v) => set({ arm: v })} named={target.newArm} onNamed={(v) => set({ newArm: v })}
                none="no arm" newWord="A new arm…" options={arms} context={context} testId={`link-arm-${keyId}`} newTestId={`link-new-arm-${keyId}`} />
      )}
      <Choose label="Product" value={target.product} named={target.newProduct} onNamed={(v) => set({ newProduct: v })} none="no product"
              newWord="A new product…" context={context} testId={`link-product-${keyId}`} newTestId={`link-new-product-${keyId}`}
              onChange={(v) => set({ product: v, batch: row.own.batch?.id ?? "", newBatch: "" })}
              options={products.map((p) => ({ id: p.subject, label: p.label }))} />
      {target.product && (
        <Choose label="Batch" value={target.batch} onChange={(v) => set({ batch: v })} named={target.newBatch} onNamed={(v) => set({ newBatch: v })}
                none="no batch" newWord="A new batch…" options={batches} context={context} testId={`link-batch-${keyId}`}
                newTestId={`link-new-batch-${keyId}`} />
      )}
      <Choose label="Analyte" value={analyte} onChange={(v) => set({ analyte: v })} named={target.newAnalyte}
              onNamed={(v) => set({ newAnalyte: v })} none={row.own.analyte ? undefined : noneAnalyte ?? "as the file says (none stated)"}
              newWord="A new analyte…" options={kinds} context={context} testId={`link-analyte-${keyId}`} newTestId={`link-new-analyte-${keyId}`} />
    </span>
  );
}

/** A file's tables each to its own place: whether they are, and each table's choices. */
export type Split = { on: boolean; set: (on: boolean) => void; target: (p: LinkPart) => LinkTarget; onTarget: (p: LinkPart, t: LinkTarget) => void };

/** One file's row, expanded: where its values go (all of them, or each table's), its values (the first few, then all),
 *  and "Link" for this file alone. */
export function LinkEditor({ projectId, row, target, onTarget, subjects, analytes, busy, missing, suggestions, onLink, problem, split,
                             used = () => [], action = "Link" }: {
  projectId: string; row: Pick<LinkRow, "values" | "file" | "fileId" | "parts" | "own">; target: LinkTarget; onTarget: (t: LinkTarget) => void;
  subjects: SubjectRow[]; analytes: Entity[];
  busy: boolean;
  /** the analyte ids a study's values carry (its card, when the page has read it) */
  used?: (study: string) => string[];
  /** the button's word: "Link", or "Link elsewhere" for values linked already (Client files) */
  action?: string;
  /** given for a file with more than one table */
  split?: Split;
  /** what the link still needs (a study or product, a new one's name, an arm that keeps two files apart), in words */
  missing: string | null;
  suggestions: string[];
  onLink: (why: string) => Promise<unknown>;
  problem: string | null;
}) {
  const [all, setAll] = useState(false);
  const [source, setSource] = useState<string | null>(null);
  const context = `for the ${plural(row.values.length, "value")} of ${row.file}`;
  const shown = all ? row.values : row.values.slice(0, SHOWN);
  return (
    <div className="link-editor" data-testid={`link-editor-${row.fileId}`}>
      <Why action={action} actionLabel={`${action} the ${plural(row.values.length, "value")} of ${row.file}`}
           label={`Why the values of ${row.file} belong there`}
           busy={busy} onSubmit={onLink} missing={missing} suggestions={suggestions} kind="link" testId={`link-edit-${row.fileId}`}
           placeholder="reason, e.g. the file name says 230-23 (kept on the audit trail)">
        {split && (
          <label className="only-mine link-split">
            <input type="checkbox" checked={split.on} onChange={(e) => split.set(e.target.checked)} data-testid={`link-split-${row.fileId}`}
                   aria-describedby={`link-split-note-${row.fileId}`} />
            Each table to its own place
            <span id={`link-split-note-${row.fileId}`} className="muted fs-12">
              {plural(row.parts.length, "part")}: {row.parts.map((p) => p.place || p.label).join(", ")}</span>
          </label>
        )}
        {split?.on ? row.parts.map((p, n) => (
          <fieldset key={p.key} className="link-part" data-testid={`link-part-${row.fileId}-${n}`}>
            <legend>{p.label}</legend>
            <TargetFields row={p} target={split.target(p)} onTarget={(t) => split.onTarget(p, t)} subjects={subjects} analytes={analytes}
                          keyId={`${row.fileId}-${n}`} context={`for the ${plural(p.values.length, "value")} of ${p.name}`}
                          used={used(split.target(p).study)} />
          </fieldset>
        )) : <TargetFields row={row} target={target} onTarget={onTarget} subjects={subjects} analytes={analytes} keyId={row.fileId} context={context}
                           used={used(target.study)} />}
      </Why>
      <Problem text={problem} testId={`link-problem-${row.fileId}`} />
      <details className="link-values" onToggle={(e) => { if (!(e.currentTarget as HTMLDetailsElement).open) setSource(null); }}>
        <summary data-testid={`link-values-${row.fileId}`}>Show its {plural(row.values.length, "value")}</summary>
        <div className="table-scroll">
          <table className="delivery-values">
            <caption className="sr-only">The values of {row.file}{action === "Link" ? " with no study or product" : ""}</caption>
            <thead><tr><th>Field</th>{TUPLE_HEADS}<th>Source</th></tr></thead>
            <tbody>
              {shown.map((v) => (
                <tr key={v.id} data-testid={`delivery-value-${v.id}`}>
                  <td>{fieldText(v.field)}</td><TupleCells v={v} />
                  <td>{v.anchor && <button type="button" className="link-btn" aria-expanded={source === v.id} data-testid={`delivery-source-open-${v.id}`}
                                           onClick={() => setSource(source === v.id ? null : v.id)}>{source === v.id ? "Hide" : "Show"}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {row.values.length > SHOWN && (
          <button type="button" className="link-btn" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${row.values.length}`}</button>
        )}
        {source && <ValueSource projectId={projectId} valueId={source} onClose={() => setSource(null)} />}
      </details>
    </div>
  );
}
