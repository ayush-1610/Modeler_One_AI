"use client";

import Link from "next/link";
import { useState } from "react";

import { DocumentViewer } from "@/components/brief/DocumentViewer";
import { PageShell, SidePanel } from "@/components/kit";
import { DrugAndFiles } from "@/components/start/Blocks";
import { DataChecklist } from "@/components/start/DataChecklist";
import { ProposalNotes } from "@/components/start/ProposalNotes";
import { RiskPicker } from "@/components/start/RiskPicker";
import { ScopeGates } from "@/components/start/ScopeGates";
import { ShortBrief } from "@/components/start/ShortBrief";
import { narrow, send } from "@/lib/api";
import type { BriefView, Citation, DocumentView } from "@/lib/brief";
import type { PlanView } from "@/lib/data-plan";
import { useMutation, useResource } from "@/lib/hooks";
import { STEP_ROUTES } from "@/lib/pipeline";
import type { BriefChange } from "@/lib/start";

type Focus = { sha256: string; page: number; quote: string | null } | null;

// The order the viewer lists documents in, so it opens on the proposal: documents are stored by content hash, and a
// client file or the PubChem record listed first would open instead. The client's files come last (read in Inputs).
const VIEWER_ORDER = ["proposal", "annex", "context", "retrieved_record", "paper", "other", "client_file"];

function forViewer(documents: DocumentView[]): DocumentView[] {
  const rank = (d: DocumentView) => {
    const i = VIEWER_ORDER.indexOf(d.role);
    return i < 0 ? VIEWER_ORDER.length : i;
  };
  return [...documents].sort((a, b) => rank(a) - rank(b) || a.uploaded_at.localeCompare(b.uploaded_at));
}

/** Step 1 · Start (redesign §3.1): the drug and its files, the short brief, the model risk, the scope gates and the
 *  data checklist on one screen. Nothing here is approved: a person reviews everything once, at the MAP signature
 *  (D-27). The step is done when the side panel has nothing left. */
export function StartScreen({ projectId }: { projectId: string }) {
  const page = useResource("/api/v1/projects/{project_id}/brief", { project_id: projectId },
    { select: (d) => narrow<BriefView>(d), poll: (d) => d.extraction_running });
  const docs = useResource("/api/v1/projects/{project_id}/documents", { project_id: projectId });
  const plan = useResource("/api/v1/projects/{project_id}/requirements", { project_id: projectId },
    { select: (d) => narrow<PlanView>(d) });
  const client = useResource("/api/v1/projects/{project_id}/client-data", { project_id: projectId });
  const { run, busy } = useMutation();
  const [focus, setFocus] = useState<Focus>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const view = page.data;

  if (page.problem) return <div className="banner err">{page.problem}</div>;
  if (!view) return <p className="muted">Loading the project…</p>;
  const documents = forViewer(docs.data?.documents ?? []);
  const open = (c: Citation) => setFocus({ sha256: c.doc_sha256, page: c.page, quote: c.quote });

  async function save(changes: BriefChange[]): Promise<string | null> {
    const { problem } = await run(() => send("put", "/api/v1/projects/{project_id}/brief", { project_id: projectId }, { changes }));
    return problem;
  }

  async function remove(group: string, index: number, reason: string): Promise<string | null> {
    const { problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief/items:remove", { project_id: projectId },
      { group, index, reason }));
    return problem;
  }

  async function answer(questionId: string, text: string, status: "answered" | "accepted_as_limitation") {
    const { problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief/questions/{question_id}",
      { project_id: projectId, question_id: questionId }, { answer: text, status }));
    if (problem) setNotice(problem);
  }

  async function readAgain() {
    const { data, problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief:extract", { project_id: projectId }, {}));
    setNotice(problem ?? (data?.agents ? "The intake agent is reading the documents; the screen fills in as it finishes."
      : (data?.problem ?? "Identity resolved; fill the rest by hand.")));
  }

  const problems = view.start.problems;
  const agent = view.agents.enabled ? `${view.agents.provider} · ${view.agents.model}` : null;
  const riskKey = ["m15.influence_rating", "m15.consequence_rating", "acceptance.tier", "m15.risk_justification"]
    .map((p) => view.brief.fields[p]?.at ?? "").join("|");

  return (
    <PageShell
      eyebrow="Step 1 of 4"
      title={<>Start · <span data-testid="start-title">{view.brief.drug_name}</span></>}
      lede="Confirm what the agents read from the proposal, and say what is modelled. Nothing is approved here: the one review is at the MAP signature."
      actions={(
        <>
          <span className={`chip ${agent ? "brand" : "neutral"}`} title={view.agents.problem ?? ""}>{agent ? `agent: ${agent}` : "agents off"}</span>
          <button type="button" className="btn" disabled={busy || view.extraction_running} onClick={readAgain} data-testid="start-read">
            {view.extraction_running ? "Reading the documents…" : "Read the documents again"}
          </button>
        </>
      )}
      side={(
        <>
          {problems.length ? (
            <SidePanel title={`Waiting on you (${problems.length})`} tone="warn" testId="start-waiting">
              <ul className="start-waiting">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
            </SidePanel>
          ) : (
            <SidePanel title="Start is done" tone="ok" testId="start-done">
              <p style={{ margin: 0 }}>Everything the inputs need from the brief is here.</p>
              <Link className="btn primary" href={STEP_ROUTES.inputs(projectId)}>Go to the inputs</Link>
            </SidePanel>
          )}
          {documents.length > 0 && <DocumentViewer projectId={projectId} documents={documents} focus={focus} />}
        </>
      )}
    >
      {notice && <div className="banner ok" data-testid="start-notice">{notice}</div>}
      <DrugAndFiles projectId={projectId} view={view} documents={documents} save={save} open={open} run={run} busy={busy}
                    onNotice={setNotice} />
      <ShortBrief view={view} save={save} open={open} onAnswer={answer} />
      <RiskPicker key={riskKey} view={view} save={save} open={open} />
      <ScopeGates view={view} save={save} open={open} />
      <DataChecklist projectId={projectId} plan={plan.data} planProblem={plan.problem}
                     reconciliation={client.data ? client.data.reconciliation.rows : null} run={run} busy={busy} />
      <ProposalNotes view={view} save={save} open={open} remove={remove} onAnswer={answer} />
    </PageShell>
  );
}
