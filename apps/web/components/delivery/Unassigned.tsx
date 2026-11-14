"use client";

// The "study not stated" values (contracts 2026-11-12 §8.10): what code read from a table whose study or product no
// label states. A person assigns each table's values to a study or a product that exists, or names a new one (the name
// as they write it: the ledger never makes a second one of the same name); the table's own arm or batch is kept unless
// the person chooses another. Until they are assigned, or their table is set aside as not data, they block every
// confirmation of the delivery.

import { useState } from "react";

import { send } from "@/lib/api";

import { Problem, TUPLE_HEADS, TupleCells, Why, fieldText, plural, useDecide, type Page, type SubjectRow, type Value } from "./shared";
import { ValueSource } from "./ValueSource";

const NEW = "__new__";      // the select's "a new one" choice (never an entity's id)
const SHOWN = 6;            // values of a table listed before "show all"

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

/** The one entity of a role every value of the table shares (its own arm, its own batch), with its label. */
function own(values: Value[], role: "arm" | "batch"): { id: string; label: string } | null {
  const ids = new Set(values.map((v) => v.entity[role] ?? ""));
  const [id] = [...ids];
  return ids.size === 1 && id ? { id, label: values[0].labels[role] ?? id } : null;
}

function Assign({ projectId, group, subjects }: { projectId: string; group: Group; subjects: SubjectRow[] }) {
  const { decide, busy, problem } = useDecide();
  const [study, setStudy] = useState("");
  const [newStudy, setNewStudy] = useState("");
  const [product, setProduct] = useState("");
  const [newProduct, setNewProduct] = useState("");
  const tableArm = own(group.values, "arm"), tableBatch = own(group.values, "batch");
  const [arm, setArm] = useState(tableArm?.id ?? "");
  const [batch, setBatch] = useState(tableBatch?.id ?? "");
  const [all, setAll] = useState(false);
  const [source, setSource] = useState<string | null>(null);
  const studies = subjects.filter((s) => s.subject_type === "study");
  const products = subjects.filter((s) => s.subject_type === "product");
  const arms = [...(tableArm ? [{ ...tableArm, label: `${tableArm.label} (the table's own)` }] : []),
                ...(studies.find((s) => s.subject === study)?.arms ?? []).filter((a) => a.id !== tableArm?.id)];
  const batches = [...(tableBatch ? [{ ...tableBatch, label: `${tableBatch.label} (the table's own)` }] : []),
                   ...(products.find((p) => p.subject === product)?.batches ?? []).filter((b) => b.id !== tableBatch?.id)];
  // a study or a product is named, and a new one has its name
  const ready = Boolean(study || product) && (study !== NEW || Boolean(newStudy.trim())) && (product !== NEW || Boolean(newProduct.trim()));
  const key = group.id.replace(/[^A-Za-z0-9-]/g, "-");

  async function assign(why: string) {
    await decide(() => send("post", "/api/v1/projects/{project_id}/delivery/values:assign", { project_id: projectId }, {
      targets: group.values.map((v) => v.id), why,
      ...(study === NEW ? { new_study: newStudy.trim() } : study ? { study } : {}),
      ...(study && arm ? { arm } : {}),
      ...(product === NEW ? { new_product: newProduct.trim() } : product ? { product } : {}),
      ...(product && batch ? { batch } : {}),
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
      <Why action="Assign" label="Why these values belong there" busy={busy} onSubmit={assign} disabled={!ready} testId={`assign-${key}`}>
        <label className="delivery-pick">Study
          <select value={study} onChange={(e) => { setStudy(e.target.value); setArm(tableArm?.id ?? ""); }} data-testid={`assign-study-${key}`}>
            <option value="">no study</option>
            {studies.map((s) => <option key={s.subject} value={s.subject}>{s.label}</option>)}
            <option value={NEW}>a new study…</option>
          </select>
        </label>
        {study === NEW && (
          <input type="text" aria-label="The new study's name" placeholder="the study's name, as the client writes it" maxLength={80}
                 value={newStudy} onChange={(e) => setNewStudy(e.target.value)} data-testid={`assign-new-study-${key}`} />
        )}
        {study && arms.length > 0 && (
          <label className="delivery-pick">Arm
            <select value={arm} onChange={(e) => setArm(e.target.value)} data-testid={`assign-arm-${key}`}>
              <option value="">no arm</option>
              {arms.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
            </select>
          </label>
        )}
        <label className="delivery-pick">Product
          <select value={product} onChange={(e) => { setProduct(e.target.value); setBatch(tableBatch?.id ?? ""); }} data-testid={`assign-product-${key}`}>
            <option value="">no product</option>
            {products.map((p) => <option key={p.subject} value={p.subject}>{p.label}</option>)}
            <option value={NEW}>a new product…</option>
          </select>
        </label>
        {product === NEW && (
          <input type="text" aria-label="The new product's name" placeholder="the product's name, as the client writes it" maxLength={80}
                 value={newProduct} onChange={(e) => setNewProduct(e.target.value)} data-testid={`assign-new-product-${key}`} />
        )}
        {product && batches.length > 0 && (
          <label className="delivery-pick">Batch
            <select value={batch} onChange={(e) => setBatch(e.target.value)} data-testid={`assign-batch-${key}`}>
              <option value="">no batch</option>
              {batches.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
            </select>
          </label>
        )}
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
        <h3>Study not stated</h3>
        <span className="chip medium">to assign</span>
      </div>
      <p className="muted m-0">No label in these tables says which study or product their values belong to. Assign each table,
        or set it aside as not data in its file&apos;s regions above. Until then nothing of this delivery can be confirmed.</p>
      <ul className="delivery-plain">
        {groups(page.unassigned).map((g) => <Assign key={g.id} projectId={projectId} group={g} subjects={page.subjects} />)}
      </ul>
    </section>
  );
}
