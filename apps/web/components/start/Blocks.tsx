"use client";

import { useState, type ReactNode } from "react";

import { EmptyState, InlineIssue } from "@/components/kit";
import { FieldRow } from "@/components/start/FieldRow";
import { upload } from "@/lib/api";
import type { BriefView, DocumentView, Question } from "@/lib/brief";
import type { useMutation } from "@/lib/hooks";
import { defOf, recordOf, type Open, type Save } from "@/lib/start";

/** One numbered block of the Start screen. */
export function Block({ n, title, lede, testId, children }: {
  n: number; title: string; lede?: ReactNode; testId: string; children: ReactNode;
}) {
  return (
    <section className="card start-block" data-testid={testId}>
      <header className="start-block-head">
        <span className="start-block-n" aria-hidden>{n}</span>
        <div>
          <h2>{title}</h2>
          {lede && <p className="muted">{lede}</p>}
        </div>
      </header>
      {children}
    </section>
  );
}

export function Fields({ view, paths, save, open, notApplicable = [], suggestions = {}, labels = {} }: {
  view: BriefView; paths: string[]; save: Save; open: Open; notApplicable?: string[]; suggestions?: Record<string, string[]>;
  /** A label for this screen where the catalog's speaks to the intake agent. */
  labels?: Record<string, string>;
}) {
  return (
    <div className="sb-rows">
      {paths.map((p) => (
        <FieldRow key={`${p}:${recordOf(view, p).at ?? ""}`} path={p} save={save} record={recordOf(view, p)}
                  def={labels[p] ? { ...defOf(view, p), label: labels[p] } : defOf(view, p)}
                  open={open} allowNotApplicable={notApplicable.includes(p)} suggestions={suggestions[p]} />
      ))}
    </div>
  );
}

const IDENTITY = ["drug.pubchem_cid", "drug.smiles", "drug.inchikey", "drug.mw_free_base"];
const WORKBOOK = /\.(xlsx|xlsm|xls|csv|tsv)$/i;

/** Block 1: the drug, its identity (PubChem, one molecular weight for the model and unit conversion) and the files. */
export function DrugAndFiles({ projectId, view, documents, save, open, run, busy, onNotice }: {
  projectId: string; view: BriefView; documents: DocumentView[]; save: Save; open: Open;
  run: ReturnType<typeof useMutation>["run"]; busy: boolean; onNotice: (text: string) => void;
}) {
  const [kind, setKind] = useState<"auto" | "document" | "client">("auto");
  const shown = documents.filter((d) => d.role !== "retrieved_record");

  async function add(list: FileList | null) {
    if (!list?.length) return;
    const files = Array.from(list);
    const toClient = files.filter((f) => kind === "client" || (kind === "auto" && WORKBOOK.test(f.name)));
    const toDocs = files.filter((f) => !toClient.includes(f));
    const notes: string[] = [];
    if (toDocs.length) {
      const form = new FormData();
      form.set("role", "annex");
      toDocs.forEach((f) => form.append("files", f));
      const { problem } = await run(() => upload("/api/v1/projects/{project_id}/documents", { project_id: projectId }, form));
      notes.push(problem ?? `${toDocs.length} document(s) added: read them again to fill the brief from them`);
    }
    if (toClient.length) {
      const form = new FormData();
      toClient.forEach((f) => form.append("files", f));
      const { problem } = await run(() => upload("/api/v1/projects/{project_id}/client-data", { project_id: projectId }, form));
      notes.push(problem ?? `${toClient.length} client file(s) stored for the Inputs step; the checklist ticks what they bring`);
    }
    onNotice(notes.join(" · "));
  }

  return (
    <Block n={1} title="The drug and the files" testId="start-drug"
           lede="The identity comes from PubChem; its molecular weight is the one the model and every unit conversion use.">
      <div className="sb-rows">
        <div className="sb-row">
          <div className="sb-label">Drug</div>
          <div className="sb-value"><span className="sb-text" data-testid="start-drug-name">{view.brief.drug_name}</span></div>
        </div>
      </div>
      <Fields view={view} paths={IDENTITY} save={save} open={open} />
      <h3 className="start-sub">Files</h3>
      {shown.length === 0 ? <EmptyState title="No files yet" /> : (
        <ul className="file-list" data-testid="start-files">
          {shown.map((d) => (
            <li key={d.sha256}><span>{d.name}</span><span className="muted">{d.role.replace(/_/g, " ")} · {d.n_pages} p.</span></li>
          ))}
        </ul>
      )}
      <div className="row" style={{ marginTop: 10 }}>
        <label className="btn">
          Add files
          <input type="file" multiple hidden disabled={busy} data-testid="start-add-files" onChange={(e) => add(e.target.files)} />
        </label>
        <select value={kind} aria-label="What the files are" onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="auto">Workbooks are client data, the rest documents</option>
          <option value="document">Proposal, annexes or papers</option>
          <option value="client">Client data</option>
        </select>
      </div>
    </Block>
  );
}

function QuestionRow({ q, label, onAnswer }: {
  q: Question; label: string; onAnswer: (id: string, text: string, status: "answered" | "accepted_as_limitation") => void;
}) {
  const [text, setText] = useState("");
  return (
    <div className="start-question" data-testid={`question-${q.id}`}>
      <p><strong>{label}:</strong> {q.question}</p>
      <div className="row">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="The answer, or why it is acceptable" />
        <button type="button" className="btn" disabled={!text.trim()} onClick={() => onAnswer(q.id, text, "answered")}>Answer</button>
        <button type="button" className="btn" disabled={!text.trim()}
                onClick={() => onAnswer(q.id, text, "accepted_as_limitation")}>Accept as a limitation</button>
      </div>
    </div>
  );
}

/** The open questions on a set of fields. Setting the field answers its question; these are the rest. */
export function OpenQuestions({ view, fields, onAnswer }: {
  view: BriefView; fields: Set<string>; onAnswer: (id: string, text: string, status: "answered" | "accepted_as_limitation") => void;
}) {
  const open = view.brief.questions.filter((q) => q.status === "open" && fields.has(q.field));
  if (!open.length) return null;
  return (
    <div className="start-questions">
      <h3 className="start-sub">Open questions</h3>
      {open.map((q) => {
        let label = q.field;
        try { label = defOf(view, q.field).label; } catch { /* a group field keeps its path */ }
        return <QuestionRow key={q.id} q={q} label={label} onAnswer={onAnswer} />;
      })}
    </div>
  );
}

export function Problem({ text }: { text: string | null }) {
  return text ? <InlineIssue severity="error">{text}</InlineIssue> : null;
}
