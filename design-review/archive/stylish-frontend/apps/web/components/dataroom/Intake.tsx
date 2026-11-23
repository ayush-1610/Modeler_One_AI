"use client";

// The delivery's way in (plan 2026-11-21 v2 §5 step 2): a drop zone for many files or a zip, the Run button, and the run's
// progress, stage by stage, with live counts and each stage's note ("Reading the files · 12 of 48 · Part D/Synopsis.pdf").

import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { send, upload } from "@/lib/api";
import { baseName, when, type Run } from "@/lib/dataroom";
import { put, readAgain, useMutation } from "@/lib/hooks";

import { RUN, UPLOADS } from "./acts";

const MARK: Record<Run["stages"][number]["state"], string> = { waiting: "○", running: "◌", done: "✓", skipped: "–", failed: "✕" };
const STATE: Record<Run["stages"][number]["state"], string> = {
  waiting: "waiting", running: "running", done: "done", skipped: "skipped", failed: "failed",
};

/** A finished run in one line: what was read and what waits (the steps open on a click). */
function summary(run: Run): string {
  const read = run.stages.find((s) => s.id === "read");
  const skipped = run.stages.filter((s) => s.state === "skipped" && s.note).length;
  return [read?.state === "done" ? read.note : "", skipped ? `${skipped} ${skipped === 1 ? "step waits" : "steps wait"} for an AI model` : "",
          run.finished_at ? `finished ${when(run.finished_at)}` : ""].filter(Boolean).join(" · ");
}

export function Progress({ run }: { run: Run }) {
  const [open, setOpen] = useState(run.state !== "done");
  if (run.state === "idle") return null;
  const running = run.state === "running";
  return (
    <section className={`dr-progress ${run.state}`} aria-live="polite" data-testid="run-progress" data-state={run.state}>
      <header className="spread">
        <span className="dr-progress-head">
          <strong>{running ? "Reading the delivery…" : run.state === "failed" ? "The run stopped" : "Last run"}</strong>
          {run.state === "done" && <span className="muted dr-small" data-testid="run-summary">{summary(run)}</span>}
        </span>
        {!running && <button type="button" className="dr-link" aria-expanded={open} onClick={() => setOpen(!open)} data-testid="run-steps-toggle">
          {open ? "Hide the steps" : "Show the steps"}</button>}
      </header>
      {run.error && <p className="dr-bad" role="alert">{run.error}</p>}
      {(open || running) && (
        <ol className="dr-stages">
          {run.stages.map((s) => (
            <li key={s.id} className={s.state} data-testid={`stage-${s.id}`} data-state={s.state}>
              <span className="dr-stage-mark" aria-hidden>{MARK[s.state]}</span>
              <span className="dr-stage-label">{s.label}</span>
              <span className="sr-only">{STATE[s.state]}</span>
              {s.total > 0 && s.state === "running" && <span className="dr-stage-count tnum">{s.done} of {s.total}</span>}
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
    const got = await act(() => send("post", RUN, params, {}), { write: (data, c) => put(c, [RUN, params, {}], data) });
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
      <button type="button" className="btn primary dr-run" disabled={busy || running || empty} onClick={() => void start()} data-testid="dataroom-run">
        {running ? "Running…" : files ? "Run again" : "Run"}
      </button>
      {note && <div className={`banner ${note.ok ? "ok" : "err"} dr-intake-note`} role={note.ok ? "status" : "alert"} data-testid="intake-note">{note.text}</div>}
      {run && <Progress run={run} />}
    </div>
  );
}
