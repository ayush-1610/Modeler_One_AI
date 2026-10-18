"use client";

// Block 1 of Start: the drug and its files (map rows p0-drug, p0-files, p3-upload, p1-pubchem, p1-mw). The identity
// comes from PubChem with a structure check (RDKit); one molecular weight, the free base's, serves the model and unit
// conversion. More files can be added at any time: the proposal's are read for the brief, the client's go to Inputs.

import Link from "next/link";
import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { FieldRow, type OpenQuote, type Run, type Save } from "@/components/start/Fields";
import { FilePicker, type Picked } from "@/components/start/FilePicker";
import { upload } from "@/lib/api";
import type { StartPage } from "@/lib/start";

const ROLE: Record<string, string> = {
  proposal: "proposal", annex: "annex", context: "your context", retrieved_record: "PubChem record", paper: "paper",
  other: "document",
};

export function DrugAndFiles({ projectId, view, onSave, onOpen, onShow, run, busy }: {
  projectId: string; view: StartPage; onSave: Save; onOpen: OpenQuote; onShow: (sha256: string) => void; run: Run;
  busy: boolean;
}) {
  const [picked, setPicked] = useState<Picked[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const documents = view.documents.filter((d) => d.role !== "client_file");

  async function add() {
    setProblem(null);
    const proposal = picked.filter((p) => p.role === "proposal");
    const client = picked.filter((p) => p.role === "client");
    const form = (files: Picked[]) => {
      const out = new FormData();
      files.forEach((p) => out.append("files", p.file));
      return out;
    };
    if (proposal.length) {
      const body = form(proposal);
      body.set("role", "proposal");
      const { problem: failed } = await run(() => upload("/api/v1/projects/{project_id}/documents", { project_id: projectId }, body));
      if (failed) { setProblem(failed); return; }
    }
    if (client.length) {
      const { problem: failed } = await run(() => upload("/api/v1/projects/{project_id}/client-data", { project_id: projectId },
                                                         form(client)));
      if (failed) { setProblem(failed); return; }
    }
    setPicked([]);
    setNotice(proposal.length ? "Added. “Read the documents again” fills the brief from the new pages; what you set is kept."
      : "Added to Inputs (Client data).");
  }

  return (
    <div className="drug-files">
      <div className="identity" data-testid="identity">
        {view.identity.filter((f) => f.path !== "drug.name").map((f) => (
          <FieldRow key={f.path} field={f} onSave={onSave} onOpen={onOpen} busy={busy}
                    hint={view.extraction_running ? "looking it up…" : "not found yet"} />
        ))}
      </div>
      <div className="files">
        <h3>Documents</h3>
        <ul className="doc-list">
          {documents.map((d) => (
            <li key={d.sha256}>
              <button type="button" className="link-btn" onClick={() => onShow(d.sha256)}>{d.name}</button>
              <span className="muted">{ROLE[d.role] ?? d.role} · {d.n_pages} page{d.n_pages === 1 ? "" : "s"}</span>
            </li>
          ))}
        </ul>
        <h3>The client&apos;s files</h3>
        {view.client_files.length === 0 ? <p className="muted">None yet. They go straight to Inputs.</p> : (
          <ul className="doc-list" data-testid="client-files">
            {view.client_files.map((f) => (
              <li key={f.id}>
                <span>{f.file}</span>
                {f.template && <span className="chip low">template, read</span>}
                <Link href={`/projects/${projectId}/client-data`} className="muted">in Inputs</Link>
              </li>
            ))}
          </ul>
        )}
        <details className="add-files">
          <summary>Add files</summary>
          <FilePicker picked={picked} onChange={setPicked} testId="add-files" />
          {picked.length > 0 && <button type="button" className="btn" disabled={busy} onClick={add}>Add {picked.length}</button>}
        </details>
        {notice && <InlineIssue severity="note">{notice}</InlineIssue>}
        {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      </div>
    </div>
  );
}
