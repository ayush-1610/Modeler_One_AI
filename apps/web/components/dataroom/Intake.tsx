"use client";

// The delivery's way in (plan 2026-11-21 v2 §5 step 2): a drop zone for many files or a zip, the Run button, and the run's
// progress, stage by stage, with live counts and each stage's note ("Reading the files · 12 of 48 · Part D/Synopsis.pdf").
// A run that stops for a reason that passes is paused, not failed (plan 2026-11-24 §4): the page says where and why, when
// it goes on by itself, and offers Resume now. Before a run on a paid model it says what the run should cost, and asks once.

import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { send, upload, type Schema } from "@/lib/api";
import { baseName, when, type Run } from "@/lib/dataroom";
import { fetchResource, put, readAgain, useMutation } from "@/lib/hooks";

import { ESTIMATE, RESUME, RUN, UPLOADS } from "./acts";

type Estimate = Schema<"RoomRunEstimate">;
type Pause = NonNullable<Run["pause"]>;

const MARK: Record<Run["stages"][number]["state"], string> = {
  waiting: "○", running: "◌", done: "✓", skipped: "–", failed: "✕", paused: "‖",
};
const STATE: Record<Run["stages"][number]["state"], string> = {
  waiting: "waiting", running: "running", done: "done", skipped: "skipped", failed: "failed", paused: "paused",
};

const dollars = (n: number) => `$${n.toFixed(2)}`;
const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const lowerFirst = (text: string) => text.charAt(0).toLowerCase() + text.slice(1);

/** A finished run in one line: what was read and what waits (the steps open on a click). */
function summary(run: Run): string {
  const read = run.stages.find((s) => s.id === "read");
  const skipped = run.stages.filter((s) => s.state === "skipped" && s.note).length;
  return [read?.state === "done" ? read.note : "", skipped ? `${skipped} ${skipped === 1 ? "step waits" : "steps wait"} for an AI model` : "",
          run.finished_at ? `finished ${when(run.finished_at)}` : ""].filter(Boolean).join(" · ");
}

/** Where a paused run stopped, why, and when it goes on: "Paused at extraction: 7 of 11 files done. NVIDIA could not
 *  answer (…). Continues by itself at 14:20, or when you switch the model. Nothing finished is read again." */
export function pausedSentence(pause: Pause): string {
  const files = pause.per_file && pause.total ? `: ${pause.done} of ${pause.total} files done` : "";
  if (pause.reason === "budget_cap") {
    return `Paused: ${lowerFirst(pause.said)} Stopped at ${pause.where}${files}. It goes on when the limit is raised or the agent ` +
      "is switched to a free model. Nothing finished is read again.";
  }
  const next = pause.resume_at ? `Continues by itself at ${clock(pause.resume_at)}, or when you switch the model.`
    : pause.reason === "no_model" ? "Continues once its model is set up (Admin → Models), or when you resume it."
      : "It tried again three times by itself: a person must resume it.";
  return `Paused at ${pause.where}${files}. ${pause.said} ${next} Nothing finished is read again.`;
}

export function Progress({ run, onResume, busy = false }: { run: Run; onResume?: () => void; busy?: boolean }) {
  const [open, setOpen] = useState(run.state !== "done");
  if (run.state === "idle") return null;
  const running = run.state === "running";
  const pause = run.state === "paused" ? run.pause : null;
  const head = running ? "Reading the delivery…" : run.state === "failed" ? "The run stopped" : pause ? "The run is paused" : "Last run";
  return (
    <section className={`dr-progress ${run.state}`} aria-live="polite" data-testid="run-progress" data-state={run.state}>
      <header className="spread">
        <span className="dr-progress-head">
          <strong>{head}</strong>
          {run.state === "done" && <span className="muted dr-small" data-testid="run-summary">{summary(run)}</span>}
        </span>
        {!running && <button type="button" className="dr-link" aria-expanded={open} onClick={() => setOpen(!open)} data-testid="run-steps-toggle">
          {open ? "Hide the steps" : "Show the steps"}</button>}
      </header>
      {run.error && <p className="dr-bad" role="alert">{run.error}</p>}
      {pause && (
        <div className="dr-paused" data-testid="dr-run-paused" data-reason={pause.reason}>
          <p>{pausedSentence(pause)}</p>
          {pause.detail && <p className="muted dr-small dr-paused-detail">{pause.detail}</p>}
          {onResume && (
            <button type="button" className="btn" disabled={busy} onClick={onResume} data-testid="dr-run-resume">Resume now</button>
          )}
        </div>
      )}
      {(open || running) && (
        <ol className="dr-stages">
          {run.stages.map((s) => (
            <li key={s.id} className={s.state} data-testid={`stage-${s.id}`} data-state={s.state}>
              <span className="dr-stage-mark" aria-hidden>{MARK[s.state]}</span>
              <span className="dr-stage-label">{s.label}</span>
              <span className="sr-only">{STATE[s.state]}</span>
              {s.total > 0 && (s.state === "running" || s.state === "paused") && <span className="dr-stage-count tnum">{s.done} of {s.total}</span>}
              {s.note && <span className="dr-stage-note" data-testid={`stage-${s.id}-note`}>{s.state === "running" ? baseName(s.note) : s.note}</span>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function Intake({ projectId, run, files, uploads }: { projectId: string; run: Run | null; files: number; uploads: number }) {
  const client = useQueryClient();
  const { run: act, busy } = useMutation();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [ask, setAsk] = useState<Estimate | null>(null);
  const params = { project_id: projectId };
  const running = run?.state === "running";

  const add = async (list: FileList | File[]) => {
    const chosen = Array.from(list);
    if (!chosen.length) return;
    const form = new FormData();
    for (const f of chosen) form.append("files", f, f.name);
    const got = await act(() => upload(UPLOADS, params, form), { reads: [UPLOADS] });
    setNote(got.problem ? { ok: false, text: got.problem }
      : { ok: true, text: `${chosen.length} ${chosen.length === 1 ? "file" : "files"} added${got.data && got.data.added.length < chosen.length ? " (some were already here)" : ""}. Run reads them.` });
  };
  const start = async () => {
    setAsk(null);
    const got = await act(() => send("post", RUN, params, {}), { write: (data, c) => put(c, [RUN, params, {}], data) });
    if (got.problem) setNote({ ok: false, text: got.problem }); else setNote(null);
    void readAgain(client, [RUN]);
  };
  // a run whose agents start on a paid model says what it should cost first, and starts only on the person's word; the
  // estimate is a courtesy: when it cannot be read the run starts, and the paid models' hard cap still holds
  const begin = async () => {
    let estimate: Estimate | null = null;
    try {
      estimate = await fetchResource(client, ESTIMATE, params);
    } catch {
      estimate = null;
    }
    if (estimate?.paid) setAsk(estimate); else await start();
  };
  const resume = async () => {
    const got = await act(() => send("post", RESUME, params, {}), { write: (data, c) => put(c, [RUN, params, {}], data) });
    if (got.problem) setNote({ ok: false, text: got.problem }); else setNote(null);
    void readAgain(client, [RUN]);
  };
  const empty = uploads === 0;
  return (
    <div className={`dr-intake${empty ? " empty" : ""}`}>
      <div className={`dr-drop${over ? " over" : ""}`} role="button" tabIndex={0} data-testid="dataroom-drop"
           onClick={() => input.current?.click()} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
           onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
           onDrop={(e) => { e.preventDefault(); setOver(false); void add(e.dataTransfer.files); }}>
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M12 16V4 M7 9l5-5 5 5 M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
        </svg>
        <span className="dr-drop-text">
          <strong>{empty ? "Drop the client's delivery here" : "Add more files"}</strong>
          <span className="muted">{empty ? "A zip, or many files at once: PDFs, Word, spreadsheets, text exports, scans." : `${uploads} ${uploads === 1 ? "upload" : "uploads"} so far · ${files} files read`}</span>
        </span>
        <input ref={input} type="file" multiple hidden data-testid="dataroom-upload" onChange={(e) => { if (e.target.files) void add(e.target.files); e.target.value = ""; }} />
      </div>
      <button type="button" className="btn primary dr-run" disabled={busy || running || empty || ask !== null} onClick={() => void begin()} data-testid="dataroom-run">
        {running ? "Running…" : files ? "Run again" : "Run"}
      </button>
      {ask && (
        <div className="banner warn dr-intake-note dr-confirm" role="alertdialog" aria-label="A run on a paid model" data-testid="dr-run-estimate">
          <span>
            This run uses a paid model: about <strong className="tnum">{dollars(ask.usd)}</strong> ({dollars(ask.usd_low)} to{" "}
            {dollars(ask.usd_high)} for {ask.files} {ask.files === 1 ? "file" : "files"} still to read). It pauses at the{" "}
            {dollars(ask.run_cap_usd)} limit for paid models. Start?
          </span>
          <span className="dr-confirm-acts">
            <button type="button" className="btn primary" disabled={busy} onClick={() => void start()} data-testid="dr-run-confirm">Start</button>
            <button type="button" className="btn" onClick={() => setAsk(null)} data-testid="dr-run-cancel">Not now</button>
          </span>
        </div>
      )}
      {note && <div className={`banner ${note.ok ? "ok" : "err"} dr-intake-note`} role={note.ok ? "status" : "alert"} data-testid="intake-note">{note.text}</div>}
      {run && <Progress run={run} onResume={() => void resume()} busy={busy} />}
    </div>
  );
}
