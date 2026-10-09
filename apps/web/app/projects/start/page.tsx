"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card } from "@/components/ui";
import { upload } from "@/lib/api";

const ACCEPT = ".pdf,.docx,.md,.markdown,.txt,.csv,.tsv,.xlsx,.xlsm,.xls";

/** P0 · Initiate (plan §5.2): the drug, the technical proposal, any context. Nothing else is asked here. */
export default function StartProjectPage() {
  const router = useRouter();
  const [drug, setDrug] = useState("");
  const [name, setName] = useState("");
  const [context, setContext] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  function addFiles(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list);
    setFiles((prev) => [...prev, ...incoming.filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))]);
  }

  async function start() {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.set("drug_name", drug.trim());
    if (name.trim()) form.set("name", name.trim());
    if (context.trim()) form.set("context", context.trim());
    files.forEach((f) => form.append("files", f));
    const env = await upload("/api/v1/projects:initiate", {}, form);
    setBusy(false);
    if (env.errors?.length || !env.data) {
      setError(env.errors?.[0]?.message ?? "The project could not be started.");
      return;
    }
    router.push(`/projects/${env.data.project_id}/brief`);
  }

  const ready = drug.trim().length > 0 && (files.length > 0 || context.trim().length > 0) && !busy;

  return (
    <main>
      <h1>Start a project</h1>
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        <strong>P0 · Initiate.</strong> Give the drug and upload the technical proposal you shared with the client (and any
        annexes). The intake agent reads them and prepares the Project Brief for your review: every value it fills cites
        the page and the exact words it came from; anything the documents do not state is left for you, never guessed.
      </p>

      <div className="cols-2">
        <Card title="The drug and the project">
          <div className="field">
            <label htmlFor="drug">Drug (INN or code) *</label>
            <input id="drug" data-testid="drug-name" value={drug} onChange={(e) => setDrug(e.target.value)} placeholder="e.g. Dapagliflozin" />
          </div>
          <div className="field">
            <label htmlFor="name">Project name (optional)</label>
            <input id="name" value={name} onChange={(e) => setName(e.target.value)}
                   placeholder={drug ? `${drug} PBPK` : "defaults to “<drug> PBPK”"} />
          </div>
          <div className="field">
            <label htmlFor="context">Context (optional)</label>
            <textarea id="context" rows={6} value={context} onChange={(e) => setContext(e.target.value)}
                      placeholder="Anything the proposal does not say: client, deadline, what was agreed in the kick-off…" />
          </div>
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>
            The context you type here is stored as a document too, so the agent can cite it like the proposal.
          </p>
        </Card>

        <Card title="Technical proposal and annexes">
          <label
            className={`dropzone${dragging ? " over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
          >
            <input type="file" data-testid="proposal-files" multiple accept={ACCEPT} onChange={(e) => addFiles(e.target.files)} hidden />
            <strong>Drop files here</strong> or click to choose
            <span className="muted">PDF, Word (.docx), Markdown, text, CSV or Excel (.xlsx)</span>
          </label>
          {files.length > 0 && (
            <table style={{ marginTop: 12 }}>
              <tbody>
                {files.map((f) => (
                  <tr key={`${f.name}-${f.size}`}>
                    <td>{f.name}</td>
                    <td className="num muted">{(f.size / 1024).toFixed(0)} KB</td>
                    <td className="num">
                      <button className="btn" onClick={() => setFiles(files.filter((x) => x !== f))}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      {error && <div className="banner err" data-testid="start-error" style={{ marginTop: 16 }}>{error}</div>}
      <div className="row" style={{ marginTop: 16 }}>
        <button className="btn primary" data-testid="start-project" disabled={!ready} onClick={start}>
          {busy ? "Uploading…" : "Start the project and prepare the brief"}
        </button>
        <span className="muted">
          or <Link href="/projects/new">start from a published model or your own parameters</Link> (quick start, no proposal)
        </span>
      </div>
    </main>
  );
}
