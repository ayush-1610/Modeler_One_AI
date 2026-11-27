"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { DropFiles } from "@/components/start/DropFiles";
import { Panel } from "@/components/kit/Panel";
import { post, upload, type Schema } from "@/lib/api";
import { Hero } from "@/components/kit";

type Estimate = Schema<"RoomRunEstimate">;

const PROPOSAL_TYPES = ".pdf,.docx,.md,.markdown,.txt,.csv,.tsv,.xlsx,.xlsm,.xls";
const dollars = (n: number) => `$${n.toFixed(2)}`;

/** P0 · Initiate (plan §5.2; redesign §3.1, block 1), the "Start from proposal" page: the drug, any context, the
 *  technical proposal and its annexes (read for the brief), and the client's files. One way in (plan 2026-11-27 step 1;
 *  the owner's D1, D2): the client's files go to the project's Data room as they came, untagged, and its run starts at
 *  once (on a paid model, after the person's word on its cost); the person lands on the Data room and watches it read. */
export default function StartProjectPage() {
  const router = useRouter();
  const [drug, setDrug] = useState("");
  const [name, setName] = useState("");
  const [context, setContext] = useState("");
  const [proposal, setProposal] = useState<File[]>([]);
  const [client, setClient] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ask, setAsk] = useState<{ projectId: string; estimate: Estimate } | null>(null);

  // a ZIP is never the proposal: it is the client's files, read member by member in the Data room
  const addProposal = (next: File[]) => {
    setProposal(next.filter((f) => !/\.zip$/i.test(f.name)));
    const zips = next.filter((f) => /\.zip$/i.test(f.name) && !client.some((c) => c.name === f.name && c.size === f.size));
    if (zips.length) setClient([...client, ...zips]);
  };

  async function start() {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.set("drug_name", drug.trim());
    if (name.trim()) form.set("name", name.trim());
    if (context.trim()) form.set("context", context.trim());
    form.set("dataroom", "true");
    proposal.forEach((f) => form.append("files", f));
    client.forEach((f) => form.append("client_files", f));
    const env = await upload("/api/v1/projects:initiate", {}, form);
    setBusy(false);
    if (env.errors?.length || !env.data) {
      setError(env.errors?.[0]?.message ?? "The project could not be started.");
      return;
    }
    const projectId = env.data.project_id;
    const room = env.data.dataroom;
    if (room?.run === "asks" && room.estimate) {
      setAsk({ projectId, estimate: room.estimate });
      return;
    }
    router.push(room ? `/projects/${projectId}/dataroom` : `/projects/${projectId}/start`);
  }

  async function runNow() {
    if (!ask) return;
    setBusy(true);
    const env = await post("/api/v1/projects/{project_id}/dataroom/run", { project_id: ask.projectId }, {});
    setBusy(false);
    if (env.errors?.length) {
      setError(`The project started, but its run did not: ${env.errors[0].message}. Run it from the Data room.`);
      return;
    }
    router.push(`/projects/${ask.projectId}/dataroom`);
  }

  const ready = drug.trim().length > 0 && (proposal.length > 0 || context.trim().length > 0) && !busy && ask === null;

  return (
    <main>
      <Hero tone="new" eyebrow="Step 1 · Start" title="Start a project"
            lede={<>Give the drug and drop the files. The proposal is read for the brief. The client&apos;s files go to the Data
              room, where the agents sort and read every one of them; you confirm what they find. Anything the files do not
              state is left for you, never guessed.</>} />

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
          <div className="start-drops">
          <DropFiles files={proposal} onChange={addProposal} testId="proposal-files" accept={PROPOSAL_TYPES}
                     title="The technical proposal and its annexes"
                     hint="Read for the brief: PDF, Word (.docx), Markdown, text or a spreadsheet" />
          <DropFiles files={client} onChange={setClient} testId="client-files"
                     title="The client's files"
                     hint="Many files or one zip: PDFs, Word, PowerPoint, spreadsheets, text and SAS exports, scans (read by OCR). The agents sort them: you tag nothing." />
          </div>
        </Panel>
      </div>

      {error && <div className="banner err mt-16" role="alert" data-testid="start-error">{error}</div>}
      {ask && (
        <div className="banner warn mt-16 start-check" role="alertdialog" aria-label="A run on a paid model" data-testid="start-run-estimate">
          <span>
            The project started and its files are in the Data room. Its agents run on a paid model: about{" "}
            <strong className="tnum">{dollars(ask.estimate.usd)}</strong> ({dollars(ask.estimate.usd_low)} to{" "}
            {dollars(ask.estimate.usd_high)} for {ask.estimate.files} {ask.estimate.files === 1 ? "file" : "files"}). It pauses
            at the {dollars(ask.estimate.run_cap_usd)} limit for paid models. Start the run?
          </span>
          <span className="row">
            <button type="button" className="btn primary" disabled={busy} onClick={() => void runNow()} data-testid="start-run-confirm">
              Start the run</button>
            <button type="button" className="btn" disabled={busy} onClick={() => router.push(`/projects/${ask.projectId}/dataroom`)}
                    data-testid="start-run-later">Not now</button>
          </span>
        </div>
      )}
      <div className="row mt-16">
        <button className="btn primary" data-testid="start-project" disabled={!ready} onClick={start}>
          {busy && !ask ? "Uploading…" : "Start the project"}
        </button>
        <span className="muted">
          {client.length > 0 ? "You go to the Data room and watch the agents read the files." : "You go to Start, where the brief is drafted from the proposal."}
        </span>
      </div>
    </main>
  );
}
