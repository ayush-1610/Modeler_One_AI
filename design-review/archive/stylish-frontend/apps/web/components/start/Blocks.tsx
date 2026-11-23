"use client";

import Link from "next/link";
import { type ReactNode } from "react";

import { EmptyState, InlineIssue } from "@/components/kit";
import { FieldRow, NeedsYou, QuestionRow } from "@/components/start/FieldRow";
import type { BriefView, DocumentView } from "@/lib/brief";
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
/** Block 1: the drug and its identity (PubChem), and the files: named in one line, listed in the project's document
 *  library. Files are added with "Add data" in the sidebar, at any step (the library plan, PR 2). */
export function DrugAndFiles({ projectId, view, documents, save, open, marks }: {
  projectId: string; view: BriefView; documents: DocumentView[]; save: Save; open: Open; marks: Marks;
}) {
  const shown = documents.filter((d) => d.role !== "retrieved_record" && !d.withdrawn);

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
        <p className="start-files" data-testid="start-files">
          {shown.length} {shown.length === 1 ? "file" : "files"}: {shown.map((d) => d.name).join(", ")}.{" "}
          <Link href={`/projects/${encodeURIComponent(projectId)}/library`} data-testid="start-library">
            See them in the Project Document Library</Link>, with what each contributed.
        </p>
      )}
      <p className="muted start-add-hint">Add more files with <strong>+ Add data</strong> in the sidebar.</p>
    </Block>
  );
}

export function Problem({ text }: { text: string | null }) {
  return text ? <InlineIssue severity="error">{text}</InlineIssue> : null;
}
