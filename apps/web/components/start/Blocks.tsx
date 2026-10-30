"use client";

import { type ReactNode } from "react";

import { EmptyState, InlineIssue } from "@/components/kit";
import { FieldRow, NeedsYou, QuestionRow } from "@/components/start/FieldRow";
import { upload } from "@/lib/api";
import type { BriefView, DocumentView } from "@/lib/brief";
import type { useMutation } from "@/lib/hooks";
import { defOf, recordOf, type Marks, type Open, type Save } from "@/lib/start";

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

export function Fields({ view, paths, save, open, marks, notApplicable = [], suggestions = {}, labels = {}, extras = {},
  confirmable = [] }: {
  view: BriefView; paths: string[]; save: Save; open: Open; marks: Marks; notApplicable?: string[];
  /** Fields that need a person's word, confirmed in place (the ICH M15 texts). */
  confirmable?: string[];
  suggestions?: Record<string, string[]>;
  /** A label for this screen where the catalog's speaks to the intake agent. */
  labels?: Record<string, string>;
  /** Something shown under a field's value (what an application adds). */
  extras?: Record<string, ReactNode>;
}) {
  return (
    <div className="sb-rows">
      {paths.map((p) => (
        <FieldRow key={`${p}:${recordOf(view, p).at ?? ""}`} path={p} save={save} record={recordOf(view, p)}
                  def={labels[p] ? { ...defOf(view, p), label: labels[p] } : defOf(view, p)}
                  open={open} allowNotApplicable={notApplicable.includes(p)} suggestions={suggestions[p]} extra={extras[p]}
                  issues={marks.issues(p)} questions={marks.questions(p)} onAnswer={marks.answer}
                  confirmable={confirmable.includes(p)} />
      ))}
    </div>
  );
}

/** The issues and open questions of fields Start does not show (the molecular weight and InChIKey moved off it), shown
 *  in the block they belong to, so nothing that holds Start up is out of sight. */
export function HiddenMarks({ paths, marks }: { paths: string[]; marks: Marks }) {
  return (
    <>
      {paths.map((p) => (
        <div key={p}>
          <NeedsYou issues={marks.issues(p)} />
          {marks.questions(p).map((q) => <QuestionRow key={q.id} q={q} onAnswer={marks.answer} />)}
        </div>
      ))}
    </>
  );
}

// the molecular weight is shown on Inputs with its source (page review 1); the InChIKey is kept in the brief, not shown
const IDENTITY = ["drug.pubchem_cid", "drug.smiles"];
const OFF_SCREEN = ["drug.mw_free_base", "drug.inchikey"];
const WORKBOOK = /\.(xlsx|xlsm|xls|csv|tsv)$/i;

/** Block 1: the drug and its identity (PubChem), and the files. Until the project's document library replaces it, the
 *  files stay listed here; each added file goes where its type says (a workbook to client data, the rest to documents). */
export function DrugAndFiles({ projectId, view, documents, save, open, marks, run, busy, onNotice }: {
  projectId: string; view: BriefView; documents: DocumentView[]; save: Save; open: Open; marks: Marks;
  run: ReturnType<typeof useMutation>["run"]; busy: boolean; onNotice: (text: string) => void;
}) {
  const shown = documents.filter((d) => d.role !== "retrieved_record");

  async function add(list: FileList | null) {
    if (!list?.length) return;
    const files = Array.from(list);
    const toClient = files.filter((f) => WORKBOOK.test(f.name));
    const toDocs = files.filter((f) => !toClient.includes(f));
    const notes: string[] = [];
    if (toDocs.length) {
      const form = new FormData();
      form.set("role", "annex");
      toDocs.forEach((f) => form.append("files", f));
      const { problem } = await run(() => upload("/api/v1/projects/{project_id}/documents", { project_id: projectId }, form));
      notes.push(problem ?? `${toDocs.map((f) => f.name).join(", ")}: added as documents; read the proposal again to fill the brief from them`);
    }
    if (toClient.length) {
      const form = new FormData();
      toClient.forEach((f) => form.append("files", f));
      const { problem } = await run(() => upload("/api/v1/projects/{project_id}/client-data", { project_id: projectId }, form));
      notes.push(problem ?? `${toClient.map((f) => f.name).join(", ")}: added as client data, read on Inputs`);
    }
    onNotice(notes.join(" · "));
  }

  return (
    <Block n={1} title="The drug and the files" testId="start-drug">
      <div className="sb-rows">
        <div className="sb-row">
          <div className="sb-label">Drug</div>
          <div className="sb-value"><span className="sb-text" data-testid="start-drug-name">{view.brief.drug_name}</span></div>
        </div>
      </div>
      <Fields view={view} paths={IDENTITY} save={save} open={open} marks={marks} />
      <HiddenMarks paths={OFF_SCREEN} marks={marks} />
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
        <span className="muted" style={{ fontSize: 13 }}>Workbooks go to client data (Inputs), everything else to the documents.</span>
      </div>
    </Block>
  );
}

export function Problem({ text }: { text: string | null }) {
  return text ? <InlineIssue severity="error">{text}</InlineIssue> : null;
}
