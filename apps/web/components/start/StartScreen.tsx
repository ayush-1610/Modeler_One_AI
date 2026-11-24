"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Hero } from "@/components/kit";
import { SourcePeek } from "@/components/kit/SourcePeek";
import { DrugAndFiles } from "@/components/start/Blocks";
import { RiskPicker } from "@/components/start/RiskPicker";
import { ScopeGates } from "@/components/start/ScopeGates";
import { ShortBrief } from "@/components/start/ShortBrief";
import { narrow, send } from "@/lib/api";
import type { BriefView, Citation, DocumentView } from "@/lib/brief";
import { useMutation, useResource, type After } from "@/lib/hooks";
import { STEP_ROUTES } from "@/lib/pipeline";
import { intakeStopped, LINEAR_DRAFT, marks as startMarks, recordOf, type BriefChange } from "@/lib/start";

type Focus = { sha256: string | null; page: number; quote: string | null; title?: string; locator?: string } | null;

// The order the viewer lists documents in, so it opens on the proposal: documents are stored by content hash, and a
// client file or the PubChem record listed first would open instead. The client's files come last (read in Inputs).
/** A change on Start (the brief, an answer, the proposal read again): the brief and its documents; the data plan, the
 *  client data's plan and the inputs follow the brief; the step bar, drawn on the server, says what Start still needs. */
const BRIEF_CHANGED: After = {
  reads: ["/api/v1/projects/{project_id}/brief", "/api/v1/projects/{project_id}/documents", "/api/v1/projects/{project_id}/steps",
          "/api/v1/projects/{project_id}/inputs", "/api/v1/projects/{project_id}/client-data"],
  server: true,
};
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
export function StartScreen({ projectId, steps }: { projectId: string; steps?: ReactNode }) {
  const page = useResource("/api/v1/projects/{project_id}/brief", { project_id: projectId },
    { select: (d) => narrow<BriefView>(d), poll: (d) => d.extraction_running });
  const docs = useResource("/api/v1/projects/{project_id}/documents", { project_id: projectId });
  const { run, busy } = useMutation();
  const [focus, setFocus] = useState<Focus>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const view = page.data;

  const lede = "Confirm what the agents read from the proposal, and say what is modelled. Nothing is approved here: the one "
    + "review is at the MAP signature.";
  if (page.problem || !view) {
    return (
      <>
        <Hero tone="start" eyebrow="Step 1 of 4" title="Start" lede={lede} />
        {steps}
        <div className="start-screen">
          {page.problem ? <div className="banner err">{page.problem}</div> : <p className="muted">Loading the project…</p>}
        </div>
      </>
    );
  }
  const documents = forViewer(docs.data?.documents ?? []);
  // a quote from a file the project's library does not hold (a Data room file): its quote and where, not a stored page
  const open = (c: Citation) => setFocus(docs.data && !documents.some((d) => d.sha256 === c.doc_sha256)
    ? { sha256: null, page: c.page, quote: c.quote, title: c.source, locator: c.locator }
    : { sha256: c.doc_sha256, page: c.page, quote: c.quote });

  async function save(changes: BriefChange[]): Promise<string | null> {
    const { problem } = await run(() => send("put", "/api/v1/projects/{project_id}/brief", { project_id: projectId }, { changes }), BRIEF_CHANGED);
    return problem;
  }

  async function answer(questionId: string, text: string, status: "answered" | "accepted_as_limitation") {
    const { problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief/questions/{question_id}",
      { project_id: projectId, question_id: questionId }, { answer: text, status }), BRIEF_CHANGED);
    if (problem) setNotice(problem);
  }

  // the Data room's confirmed question card and studies drafted into the brief (plan 2026-11-24 §7, phase 4): each a
  // draft to confirm below; a person's own value is never overwritten, and where it differs the room's advice says so
  async function fillFromRoom() {
    const { data, problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief:from-dataroom", { project_id: projectId }, {}),
      BRIEF_CHANGED);
    if (problem || !data) {
      setNotice(problem ?? "The Data room could not be read.");
      return;
    }
    const drafted = data.drafted.length;
    const kept = data.kept.length;
    setNotice((drafted ? `The Data room drafted ${drafted} ${drafted === 1 ? "field" : "fields"}; each waits for you below.`
      : "Nothing new from the Data room: Start already holds what it says.")
      + (kept ? ` ${kept} ${kept === 1 ? "value" : "values"} you or a document set ${kept === 1 ? "was" : "were"} kept.` : ""));
  }

  async function readAgain() {
    const { data, problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief:extract", { project_id: projectId }, {}), BRIEF_CHANGED);
    setNotice(problem ?? (data?.agents ? "The intake agent is reading the documents; the screen fills in as it finishes."
      : `${data?.problem ? `${data.problem}. ` : ""}Code read the proposal again; each draft waits for you below.`));
  }

  // every draft on Start, confirmed as shown in one step (the owner, 2026-11-07: "the user will just see through and only
  // change" what is wrong); the model risk keeps its own save, a person's rating
  const drafts = [...new Set(view.start.issues.filter((i) => i.message.endsWith("confirm the draft, or change it"))
    .map((i) => i.path))];
  async function confirmAll() {
    const problem = await save(drafts.map((path): BriefChange =>
      path === "scope.nonlinearity" && recordOf(view!, path).value === LINEAR_DRAFT ? { path, status: "NOT_APPLICABLE" }
        : { path, status: "CONFIRMED" }));
    if (problem) setNotice(problem);
  }

  const marks = startMarks(view, answer);
  const waiting = view.start.issues.length;
  const riskKey = ["m15.influence_rating", "m15.consequence_rating", "acceptance.tier", "m15.risk_justification",
    "m15.influence_suggested", "m15.consequence_suggested"].map((p) => view.brief.fields[p]?.at ?? "").join("|");

  return (
    <>
    <Hero tone="start" eyebrow="Step 1 of 4" title={<>Start · {view.brief.drug_name}</>} lede={lede}
          actions={(
            <>
              {view.start.room?.confirmed_card && (
                <button type="button" className="btn" disabled={busy || view.extraction_running} onClick={fillFromRoom}
                        data-testid="start-fill-from-room"
                        title="Draft the question, applications, products, scenarios and populations the Data room's confirmed card and studies state">
                  Fill from the Data room
                </button>
              )}
              <button type="button" className="btn" disabled={busy || view.extraction_running} onClick={readAgain} data-testid="start-read">
                {view.extraction_running ? "Reading the proposal…" : "Read the proposal again"}
              </button>
            </>
          )} />
    {steps}
    <div className="start-screen">
      <div className="start-top">
        {(notice || view.extraction_running) && (
          <p className="start-notice muted" data-testid="start-notice">
            {view.extraction_running ? "The intake agent is reading the documents; the screen fills in as it finishes." : notice}
          </p>
        )}
      </div>
      <IntakeStatus view={view} />
      <RoomAdvice view={view} />
      <DrugAndFiles projectId={projectId} view={view} documents={documents} save={save} open={open} marks={marks} />
      <ShortBrief view={view} save={save} open={open} marks={marks} />
      <RiskPicker key={riskKey} view={view} save={save} open={open} marks={marks} />
      <ScopeGates view={view} save={save} open={open} marks={marks} />
      <div className={`start-continue${waiting ? " needs-you" : ""}`} data-testid={waiting ? "start-waiting" : "start-done"}>
        {waiting ? (
          <>
            <span><span aria-hidden>⚠ </span>{waiting} {waiting === 1 ? "thing still needs" : "things still need"} you, marked in red above.
              Start is done when none is left.</span>
            {drafts.length > 1 && (
              <button type="button" className="btn" data-testid="start-confirm-all" onClick={confirmAll}
                      title="Each draft is kept as it is shown above, recorded as confirmed by you">
                Confirm all {drafts.length} drafts as shown</button>
            )}
            <button type="button" className="btn primary" disabled data-testid="start-continue">Continue to Inputs</button>
          </>
        ) : (
          <>
            <span>Start is done: everything the inputs need from the brief is here.</span>
            <Link className="btn primary" href={STEP_ROUTES.inputs(projectId)} data-testid="start-continue">Continue to Inputs</Link>
          </>
        )}
      </div>
      {focus && (
        <SourcePeek projectId={projectId} source={{ doc_sha256: focus.sha256, page: focus.page, quote: focus.quote, title: focus.title,
                                                    locator: focus.locator }}
                    onClose={() => setFocus(null)} />
      )}
    </div>
    </>
  );
}

/** Where Start's own word differs from the Data room's confirmed question card (plan 2026-11-24 §7, B5): advice, never a
 *  block. Both are kept; the person decides which stands. */
function RoomAdvice({ view }: { view: BriefView }) {
  const advice = view.start.room?.advice ?? [];
  if (!advice.length) return null;
  return (
    <div className="start-notice muted" data-testid="start-room-advice">
      <p>The Data room says otherwise (advice; Start is done without it):</p>
      <ul>{advice.map((a) => <li key={a.path} data-testid={`start-room-advice-${a.path}`}>{a.message}</li>)}</ul>
    </div>
  );
}

/** Who read the proposal for Start (the owner, 2026-11-07: the model risk was left empty with no word why): the intake
 *  agent, or, when it is off or its last read did not finish, code and the ICH M15 rule alone. */
function IntakeStatus({ view }: { view: BriefView }) {
  if (view.extraction_running) return null;
  const last = view.runs.find((r) => r.agent === "A1-proposal-intake");
  if (!view.agents.enabled) {
    return (
      <p className="start-notice muted" data-testid="start-intake">
        The intake agent is off on this server ({view.agents.problem ?? "no model configured"}): code read the proposal
        and the FDA label, and the ICH M15 rule (UNVERIFIED) drafted the model risk. Each draft waits for you below.
      </p>
    );
  }
  if (last && last.status !== "COMPLETED") {
    // why it stopped, in plain words (the owner, 2026-11-22: it stopped with no word why), and what it still filled
    const error = typeof last.summary?.error === "string" ? last.summary.error : "";
    const accepted = typeof last.summary?.accepted === "number" ? last.summary.accepted : 0;
    return (
      <p className="start-notice muted" data-testid="start-intake">
        The intake agent&apos;s last read ({last.model}) did not finish: {intakeStopped(last.status, error)}.
        {accepted > 0 ? ` It filled ${accepted} ${accepted === 1 ? "field" : "fields"}, each checked against its quote.` : ""}
        {" "}Code drafted what it left, and the ICH M15 rule (UNVERIFIED) the model risk if it had none.
      </p>
    );
  }
  return null;
}
