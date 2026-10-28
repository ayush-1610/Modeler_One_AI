"use client";

import Link from "next/link";
import { useState } from "react";

import { DocumentViewer } from "@/components/brief/DocumentViewer";
import { Dialog } from "@/components/kit/Dialog";
import { DrugAndFiles } from "@/components/start/Blocks";
import { RiskPicker } from "@/components/start/RiskPicker";
import { ScopeGates } from "@/components/start/ScopeGates";
import { ShortBrief } from "@/components/start/ShortBrief";
import { narrow, send } from "@/lib/api";
import type { BriefView, Citation, DocumentView } from "@/lib/brief";
import { useMutation, useResource } from "@/lib/hooks";
import { STEP_ROUTES } from "@/lib/pipeline";
import { marks as startMarks, type BriefChange } from "@/lib/start";

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

/** Step 1 · Start (redesign §3.1; page review 1, 2026-10-27): the drug and its files, the question, the model risk and
 *  what is modelled, on one screen. Nothing here is approved: a person reviews everything once, at the MAP signature
 *  (D-27). Each box that still needs the person is marked in red where it is; until none is, Start cannot be left. A
 *  value's source is shown beside it, and its page opens over the screen. */
export function StartScreen({ projectId }: { projectId: string }) {
  const page = useResource("/api/v1/projects/{project_id}/brief", { project_id: projectId },
    { select: (d) => narrow<BriefView>(d), poll: (d) => d.extraction_running });
  const docs = useResource("/api/v1/projects/{project_id}/documents", { project_id: projectId });
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

  const marks = startMarks(view, answer);
  const waiting = view.start.issues.length;
  const riskKey = ["m15.influence_rating", "m15.consequence_rating", "acceptance.tier", "m15.risk_justification"]
    .map((p) => view.brief.fields[p]?.at ?? "").join("|");

  return (
    <div className="start-screen">
      <div className="start-top">
        <button type="button" className="btn" disabled={busy || view.extraction_running} onClick={readAgain} data-testid="start-read">
          {view.extraction_running ? "Reading the proposal…" : "Read the proposal again"}
        </button>
        {(notice || view.extraction_running) && (
          <p className="start-notice muted" data-testid="start-notice">
            {view.extraction_running ? "The intake agent is reading the documents; the screen fills in as it finishes." : notice}
          </p>
        )}
      </div>
      <DrugAndFiles projectId={projectId} view={view} documents={documents} save={save} open={open} marks={marks}
                    run={run} busy={busy} onNotice={setNotice} />
      <ShortBrief view={view} save={save} open={open} marks={marks} />
      <RiskPicker key={riskKey} view={view} save={save} marks={marks} />
      <ScopeGates view={view} save={save} open={open} marks={marks} />
      <div className={`start-continue${waiting ? " needs-you" : ""}`} data-testid={waiting ? "start-waiting" : "start-done"}>
        {waiting ? (
          <>
            <span><span aria-hidden>⚠ </span>{waiting} {waiting === 1 ? "thing still needs" : "things still need"} you, marked in red above.
              Start is done when none is left.</span>
            <button type="button" className="btn primary" disabled data-testid="start-continue">Continue to Inputs</button>
          </>
        ) : (
          <>
            <span>Start is done: everything the inputs need from the brief is here.</span>
            <Link className="btn primary" href={STEP_ROUTES.inputs(projectId)} data-testid="start-continue">Continue to Inputs</Link>
          </>
        )}
      </div>
      {focus && documents.length > 0 && (
        <Dialog title="Where the value comes from" size="wide" onClose={() => setFocus(null)} testId="start-source-dialog">
          <DocumentViewer projectId={projectId} documents={documents} focus={focus} />
          <div className="dialog-actions">
            <button type="button" className="btn" onClick={() => setFocus(null)}>Close</button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
