"use client";

// The "study not stated" values (contracts 2026-11-12 §8.10): what code read from a table whose study or product no
// label states. A person links each table's values to a study or a product that exists, or names a new one (the name
// as they write it: the ledger never makes a second one of the same name), and with it the arm of the study or the
// batch of the product and the values' analyte, each an existing one or a new one the person names (plan 2026-11-14
// §2.2.2: the Test and the Reference file of one study land as two arms). A link replaces the earlier one whole, so the
// form starts from the arm and analyte the values have and sends them again unless the person chooses others. A name
// that exists already is refused in the server's words, and the section is read again. Until the values are linked,
// or their table is set aside as not data, they block every confirmation of the delivery.

import { useState } from "react";

import { send, type Schema } from "@/lib/api";

import {
  Problem, TUPLE_HEADS, TupleCells, Why, fieldText, plural, useDecide, type Page, type SubjectRow, type Value,
} from "./shared";
import { ValueSource } from "./ValueSource";

const NEW = "__new__";      // the select's "a new one" choice (never an entity's id)
const SHOWN = 6;            // values of a table listed before "show all"
type Entity = Schema<"DeliveryEntity">;

type Group = { id: string; file: string | null; kind: string | null; values: Value[] };

/** The unassigned values by the table they were read from (the facts of a file together). */
function groups(values: Value[]): Group[] {
  const out = new Map<string, Group>();
  for (const v of values) {
    const id = v.id.includes("#") ? v.id.split("#")[0] : `facts:${v.file_sha256 ?? "entered"}`;
    const group = out.get(id) ?? { id, file: v.file, kind: v.table_kind, values: [] };
    group.values.push(v);
    out.set(id, group);
  }
  return [...out.values()];
}

/** The one entity of a role every value of the table shares (its own arm, batch or analyte), with its label. */
function own(values: Value[], role: "arm" | "batch" | "analyte"): Entity | null {
  const ids = new Set(values.map((v) => v.entity[role] ?? ""));
  const [id] = [...ids];
  return ids.size === 1 && id ? { id, label: values[0].labels[role] ?? id } : null;
}

/** A select of existing entities and "A new …", with the new one's name beside it when chosen. */
function Choose({ label, value, onChange, named, onNamed, options, none, newWord, testId, context }: {
  label: string; value: string; onChange: (v: string) => void; named: string; onNamed: (v: string) => void;
  options: Entity[];
  /** the empty choice's words; left out, there is none */
  none?: string; newWord: string; testId: string;
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
               data-testid={`${testId.replace(/^assign-/, "assign-new-")}`} />
      )}
    </>
  );
}

/** The link form of one table's values: a study (and its arm) or a product (and its batch), and the analyte. */
function Assign({ projectId, group, subjects, analytes }: { projectId: string; group: Group; subjects: SubjectRow[]; analytes: Entity[] }) {
  const { decide, busy, problem } = useDecide();
  const tableArm = own(group.values, "arm"), tableBatch = own(group.values, "batch"), tableAnalyte = own(group.values, "analyte");
  const [study, setStudy] = useState("");
  const [newStudy, setNewStudy] = useState("");
  const [arm, setArm] = useState(tableArm?.id ?? "");
  const [newArm, setNewArm] = useState("");
  const [product, setProduct] = useState("");
  const [newProduct, setNewProduct] = useState("");
  const [batch, setBatch] = useState(tableBatch?.id ?? "");
  const [newBatch, setNewBatch] = useState("");
  const [analyte, setAnalyte] = useState(tableAnalyte?.id ?? "");
  const [newAnalyte, setNewAnalyte] = useState("");
  const [all, setAll] = useState(false);
  const [source, setSource] = useState<string | null>(null);
  const studies = subjects.filter((s) => s.subject_type === "study");
  const products = subjects.filter((s) => s.subject_type === "product");
  const arms = [...(tableArm ? [{ ...tableArm, label: `${tableArm.label} (the table's own)` }] : []),
                ...(studies.find((s) => s.subject === study)?.arms ?? []).filter((a) => a.id !== tableArm?.id)];
  const batches = [...(tableBatch ? [{ ...tableBatch, label: `${tableBatch.label} (the table's own)` }] : []),
                   ...(products.find((p) => p.subject === product)?.batches ?? []).filter((b) => b.id !== tableBatch?.id)];
  const analyteChoices = [...(tableAnalyte ? [{ ...tableAnalyte, label: `${tableAnalyte.label} (the file's own)` }] : []),
                          ...analytes.filter((a) => a.id !== tableAnalyte?.id)];
  const named = (choice: string, name: string) => choice !== NEW || Boolean(name.trim());
  // a study or a product is named, and every new one has its name
  const ready = Boolean(study || product) && named(study, newStudy) && named(product, newProduct)
    && (!study || named(arm, newArm)) && (!product || named(batch, newBatch)) && named(analyte, newAnalyte);
  const key = group.id.replace(/[^A-Za-z0-9-]/g, "-");
  const context = `for the ${plural(group.values.length, "value")} of ${group.file ?? "a person's entries"}`;

  async function assign(why: string) {
    // a link replaces the earlier one whole: the arm (batch) and the analyte shown are sent again as they stand
    await decide(() => send("post", "/api/v1/projects/{project_id}/delivery/values:assign", { project_id: projectId }, {
      targets: group.values.map((v) => v.id), why,
      ...(study === NEW ? { new_study: newStudy.trim() } : study ? { study } : {}),
      ...(study ? (arm === NEW ? { new_arm: newArm.trim() } : arm ? { arm } : {}) : {}),
      ...(product === NEW ? { new_product: newProduct.trim() } : product ? { product } : {}),
      ...(product ? (batch === NEW ? { new_batch: newBatch.trim() } : batch ? { batch } : {}) : {}),
      ...(analyte === NEW ? { new_analyte: newAnalyte.trim() } : analyte ? { analyte } : {}),
    }));
  }

  const shown = all ? group.values : group.values.slice(0, SHOWN);
  return (
    <li className="delivery-unassigned-table" data-testid={`delivery-unassigned-${key}`}>
      <div className="delivery-block-head">
        <strong>{group.file ?? "Entered by a person"}</strong>
        <span className="muted">{group.kind ? `${fieldText(group.kind)} table · ` : ""}{plural(group.values.length, "value")} with no study or product stated</span>
      </div>
      <div className="table-scroll">
        <table className="delivery-values">
          <caption className="sr-only">Values with no study stated, from {group.file ?? "a person"}</caption>
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
      {group.values.length > SHOWN && (
        <button type="button" className="link-btn" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${group.values.length}`}</button>
      )}
      {source && <ValueSource projectId={projectId} valueId={source} onClose={() => setSource(null)} />}
      <Why action="Link" actionLabel={`Link ${context.replace(/^for /, "")}`} label={`Why ${context.replace(/^for /, "")} belong there`}
           busy={busy} onSubmit={assign} disabled={!ready}
           testId={`assign-${key}`} placeholder="reason, e.g. the file name says 230-23 (kept on the audit trail)">
        <Choose label="Study" value={study} named={newStudy} onNamed={setNewStudy} none="no study" newWord="A new study…" context={context}
                onChange={(v) => { setStudy(v); setArm(tableArm?.id ?? ""); }} testId={`assign-study-${key}`}
                options={studies.map((s) => ({ id: s.subject, label: s.label }))} />
        {study && (
          <Choose label="Arm" value={arm} onChange={setArm} named={newArm} onNamed={setNewArm} none="no arm" newWord="A new arm…"
                  options={arms} context={context} testId={`assign-arm-${key}`} />
        )}
        <Choose label="Product" value={product} named={newProduct} onNamed={setNewProduct} none="no product" newWord="A new product…"
                context={context} onChange={(v) => { setProduct(v); setBatch(tableBatch?.id ?? ""); }} testId={`assign-product-${key}`}
                options={products.map((p) => ({ id: p.subject, label: p.label }))} />
        {product && (
          <Choose label="Batch" value={batch} onChange={setBatch} named={newBatch} onNamed={setNewBatch} none="no batch" newWord="A new batch…"
                  options={batches} context={context} testId={`assign-batch-${key}`} />
        )}
        <Choose label="Analyte" value={analyte} onChange={setAnalyte} named={newAnalyte} onNamed={setNewAnalyte}
                none={tableAnalyte ? undefined : "as the file says (none stated)"} newWord="A new analyte…" options={analyteChoices}
                context={context} testId={`assign-analyte-${key}`} />
      </Why>
      <Problem text={problem} testId={`assign-problem-${key}`} />
    </li>
  );
}

export function Unassigned({ projectId, page }: { projectId: string; page: Page }) {
  if (!page.unassigned.length) return null;
  // a blinded study's values are never counted here: the list says only that there are values to assign
  return (
    <section className="delivery-block" data-testid="delivery-unassigned">
      <div className="delivery-block-head">
        <h3>Values not linked to a study or product</h3>
        <span className="chip medium">to decide</span>
      </div>
      <p className="muted m-0">These files don&apos;t say which study or product their values belong to. Link each table, with its arm
        or batch and its analyte (an existing one or a new one you name), or mark it as not data in its file&apos;s tables above.
        Until then nothing of this delivery can be confirmed.</p>
      <ul className="delivery-plain">
        {groups(page.unassigned).map((g) => <Assign key={g.id} projectId={projectId} group={g} subjects={page.subjects} analytes={page.analytes} />)}
      </ul>
    </section>
  );
}
