"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { needsALook, TagProposals } from "@/components/library/TagProposals";
import { FilePicker, type Picked } from "@/components/start/FilePicker";
import { Card } from "@/components/ui";
import { upload, type Schema } from "@/lib/api";
import { tagsField } from "@/lib/fileTags";

/** P0 · Initiate (plan §5.2; redesign §3.1, block 1), the "Start from proposal" page: the drug, any context, and one
 *  upload for the technical proposal, its annexes and the client's data files, which go straight to Inputs (map rows
 *  p0-files, p3-upload). Each client file is tagged here (plan 2026-11-03 §3.1); nothing is read or confirmed here. */
export default function StartProjectPage() {
  const router = useRouter();
  const [drug, setDrug] = useState("");
  const [name, setName] = useState("");
  const [context, setContext] = useState("");
  const [files, setFiles] = useState<Picked[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState<{ projectId: string; files: Schema<"ClientFileStarted">[] } | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.set("drug_name", drug.trim());
    if (name.trim()) form.set("name", name.trim());
    if (context.trim()) form.set("context", context.trim());
    files.forEach((p) => form.append(p.tag === "proposal" ? "files" : "client_files", p.file));
    form.set("tags", tagsField(files));
    const env = await upload("/api/v1/projects:initiate", {}, form);
    setBusy(false);
    if (env.errors?.length || !env.data) {
      setError(env.errors?.[0]?.message ?? "The project could not be started.");
      return;
    }
    if (needsALook(env.data.client_files)) {
      // a tag the content contradicts, a scan, a file not read: said here before moving on, decided with one click
      setCheck({ projectId: env.data.project_id, files: env.data.client_files });
      return;
    }
    router.push(`/projects/${env.data.project_id}/start`);
  }

  const proposal = files.some((p) => p.tag === "proposal");
  const ready = drug.trim().length > 0 && (proposal || context.trim().length > 0) && !busy && check === null;

  return (
    <main>
      <h1>Start from proposal</h1>
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        Give the drug and drop every file in one go: the technical proposal you shared with the client and its annexes are
        read for the brief; the client&apos;s files, each tagged with what it is, are read in the background and wait on
        Inputs, marked “to confirm”. Every value an agent fills cites the page or cell it came from; anything the files do
        not state is left for you, never guessed.
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

        <Card title="The proposal, its annexes and the client's files, tagged">
          <FilePicker picked={files} onChange={setFiles} testId="proposal-files" />
        </Card>
      </div>

      {error && <div className="banner err" data-testid="start-error" style={{ marginTop: 16 }}>{error}</div>}
      {check && (
        <div className="banner warn start-check" data-testid="start-unread" style={{ marginTop: 16 }}>
          <strong>The project started. A look at {check.files.filter((f) => f.problem || f.needs_ocr || f.tag_proposal?.decided === "open").length === 1
            ? "one file" : "these files"} first:</strong>
          <TagProposals projectId={check.projectId} files={check.files} testId="start-tag-proposals" />
          <Link className="btn primary" href={`/projects/${check.projectId}/start`} data-testid="start-continue">Continue to Start</Link>
        </div>
      )}
      <div className="row" style={{ marginTop: 16 }}>
        <button className="btn primary" data-testid="start-project" disabled={!ready} onClick={start}>
          {busy ? "Uploading…" : "Start the project and prepare the brief"}
        </button>
        <span className="muted">
          A published OSP model of the drug can be taken as a source on the Inputs step.
        </span>
      </div>
    </main>
  );
}
