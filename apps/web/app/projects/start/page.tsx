"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { InlineIssue, PageShell, SidePanel } from "@/components/kit";
import { FilePicker, type Picked } from "@/components/start/FilePicker";
import { upload, type Schema } from "@/lib/api";

/** Step 1 · Start, before the project exists (redesign §3.1, block 1): the drug, any context, and one upload for the
 *  proposal, its annexes and the client's files. The rest of Start opens on the project once it is created. */
export default function StartProjectPage() {
  const router = useRouter();
  const [drug, setDrug] = useState("");
  const [context, setContext] = useState("");
  const [picked, setPicked] = useState<Picked[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refused, setRefused] = useState<{ projectId: string; files: Schema<"ClientFileStarted">[] } | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.set("drug_name", drug.trim());
    if (context.trim()) form.set("context", context.trim());
    picked.forEach((p) => form.append(p.role === "client" ? "client_files" : "files", p.file));
    const env = await upload("/api/v1/projects:initiate", {}, form);
    setBusy(false);
    if (env.errors?.length || !env.data) {
      setError(env.errors?.[0]?.message ?? "The project could not be started.");
      return;
    }
    const unread = env.data.client_files.filter((f) => f.problem);
    if (unread.length) {
      setRefused({ projectId: env.data.project_id, files: unread });   // say what was not read before moving on
      return;
    }
    router.push(`/projects/${env.data.project_id}/start`);
  }

  const proposal = picked.some((p) => p.role === "proposal");
  const ready = drug.trim().length > 0 && (proposal || context.trim().length > 0) && !busy;

  return (
    <main>
      <PageShell
        eyebrow="Step 1 · Start"
        title="Start a project"
        lede={<>Name the drug and drop the files in one go: the proposal and its annexes are read for the brief, the
          client&apos;s data files go straight to Inputs. Every value the agent fills cites the page and the exact words it
          came from; what the documents do not state is left for you, never guessed.</>}
        side={
          <SidePanel title="What happens next">
            <ul className="missing-list">
              <li>The drug&apos;s identity is looked up in PubChem and checked against its structure.</li>
              <li>The agent fills the short brief from the documents, each value with its quote.</li>
              <li>The data checklist follows from the brief; the client&apos;s files are ticked off as they arrive.</li>
              <li>Nothing is approved here: you review everything once, when you sign the plan.</li>
            </ul>
          </SidePanel>
        }
      >
        <section className="card start-block">
          <h2><span className="block-n">1</span> The drug and the files</h2>
          <div className="field">
            <label htmlFor="drug">Drug (INN or code) *</label>
            <input id="drug" data-testid="drug-name" value={drug} onChange={(e) => setDrug(e.target.value)}
                   placeholder="e.g. Dapagliflozin" autoComplete="off" />
            <p className="muted hint">It also names the project: “{drug.trim() || "<drug>"} PBPK”.</p>
          </div>
          <div className="field">
            <label htmlFor="context">Context (optional)</label>
            <textarea id="context" rows={4} value={context} onChange={(e) => setContext(e.target.value)}
                      placeholder="Anything the proposal does not say: the client, a deadline, what was agreed at the kick-off…" />
            <p className="muted hint">Stored as a document too, so the agent can cite it like the proposal.</p>
          </div>
          <FilePicker picked={picked} onChange={setPicked} testId="proposal-files" />
        </section>
        {error && <div className="banner err" data-testid="start-error">{error}</div>}
        {refused && (
          <InlineIssue severity="warn" testId="start-unread">
            The project started, but {refused.files.length === 1 ? "one client file was" : `${refused.files.length} client files were`} not
            read: {refused.files.map((f) => `${f.file} (${f.problem})`).join("; ")}.{" "}
            <Link href={`/projects/${refused.projectId}/start`}>Continue to the project</Link>
          </InlineIssue>
        )}
        <div className="row">
          <button type="button" className="btn primary" data-testid="start-project" disabled={!ready || refused !== null}
                  onClick={start}>
            {busy ? "Uploading…" : "Start the project"}
          </button>
          {!proposal && !context.trim() && <span className="muted">Add the proposal, or describe the project in the context.</span>}
          <span className="muted">
            or <Link href="/projects/new">start from a published model or your own parameters</Link> (quick start, no proposal)
          </span>
        </div>
      </PageShell>
    </main>
  );
}
