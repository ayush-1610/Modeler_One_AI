"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { DropFiles, type Dropped } from "@/components/start/DropFiles";
import { Panel } from "@/components/kit/Panel";
import { upload } from "@/lib/api";
import { Hero } from "@/components/kit";

/** P0 · Initiate (plan §5.2; redesign §3.1, block 1), the "Start from proposal" page: the drug, any context, and one
 *  drop zone for everything (the owner, 2026-11-28). One way in (plan 2026-11-27 step 1; the owner's D1, D2): a file
 *  marked "Proposal" is read for the brief; every other file goes to the project's Data room as it came, untagged, and
 *  its run starts at once, whatever it may cost (the owner, 2026-11-28); the person lands on the Data room and watches
 *  the files read. With no client file the person lands on Start. */
export default function StartProjectPage() {
  const router = useRouter();
  const [drug, setDrug] = useState("");
  const [name, setName] = useState("");
  const [context, setContext] = useState("");
  const [files, setFiles] = useState<Dropped[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const proposal = files.filter((p) => p.proposal);
  const client = files.filter((p) => !p.proposal);

  async function start() {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.set("drug_name", drug.trim());
    if (name.trim()) form.set("name", name.trim());
    if (context.trim()) form.set("context", context.trim());
    form.set("dataroom", "true");
    proposal.forEach((p) => form.append("files", p.file));
    client.forEach((p) => form.append("client_files", p.file));
    const env = await upload("/api/v1/projects:initiate", {}, form);
    setBusy(false);
    if (env.errors?.length || !env.data) {
      setError(env.errors?.[0]?.message ?? "The project could not be started.");
      return;
    }
    const projectId = env.data.project_id;
    router.push(env.data.dataroom ? `/projects/${projectId}/dataroom` : `/projects/${projectId}/start`);
  }

  const ready = drug.trim().length > 0 && (proposal.length > 0 || context.trim().length > 0) && !busy;
  const where = client.length > 0 ? "You go to the Data room and watch the agents read the client's files."
    : "You go to Start, where the brief is drafted from the proposal.";

  return (
    <main>
      <Hero tone="new" eyebrow="Step 1 · Start" title="Start a project"
            lede={<>Give the drug and drop every file in one go. The proposal is read for the brief; the client&apos;s files go
              to the Data room, where the agents sort and read every one of them, and you confirm what they find. Anything the
              files do not state is left for you, never guessed.</>} />

      <div className="cols-2">
        <Panel title="The drug and the project">
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
          <p className="muted fs-13 m-0">
            The context you type here is stored as a document too, so the agent can cite it like the proposal.
          </p>
        </Panel>

        <Panel title="The files">
          <DropFiles files={files} onChange={setFiles} testId="proposal-files" />
          {files.length > 0 && (
            <p className="muted fs-13 m-0" data-testid="start-files-split">
              {proposal.length ? `${proposal.length} read for the brief` : "No file is marked Proposal"} ·{" "}
              {client.length} to the Data room
            </p>
          )}
        </Panel>
      </div>

      {error && <div className="banner err mt-16" role="alert" data-testid="start-error">{error}</div>}
      <div className="row mt-16">
        <button className="btn primary" data-testid="start-project" disabled={!ready} onClick={start}>
          {busy ? "Uploading…" : "Start the project"}
        </button>
        <span className="muted" data-testid="start-where">
          {drug.trim() && !proposal.length && !context.trim() ? "Mark the technical proposal, or describe the project in Context." : where}
        </span>
      </div>
    </main>
  );
}
