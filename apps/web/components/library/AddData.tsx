"use client";

// "Add data" (docs/plans/2026-10-28-project-document-library.md, PR 2; the owner's decisions 10–12 of 2026-10-29): a
// centred card over the page, opened from the sidebar at any step of a project. The person picks files and says what
// they relate to: a step and, optionally, a task. Each file goes where its type says, a workbook to client data (read
// on Inputs) and anything else to the documents as an annex; the guess is switched per file. Everything added is kept
// in this project's library, with who added it and when.

import Link from "next/link";
import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { upload } from "@/lib/api";
import { useMutation } from "@/lib/hooks";

type Goes = "client" | "annex" | "paper" | "context" | "proposal" | "other";

const GOES: [Goes, string][] = [
  ["client", "Client data (read on Inputs)"], ["annex", "Document: annex"], ["paper", "Document: paper"],
  ["context", "Document: context"], ["proposal", "Document: proposal"], ["other", "Document: other"],
];
const ADDED_AS: Record<Exclude<Goes, "client">, string> = {
  annex: "an annex", paper: "a paper", context: "context", proposal: "part of the proposal", other: "a document",
};
export const RELATED_STEPS: [string, string][] = [["start", "Start"], ["inputs", "Inputs"], ["review", "Review & sign"], ["run", "Run"]];
const WORKBOOK = /\.(xlsx|xlsm|xls|csv|tsv)$/i;
const ACCEPT = ".pdf,.docx,.md,.markdown,.txt,.json,.csv,.tsv,.xlsx,.xlsm,.xls,.png,.jpg,.jpeg";

/** The step of the page a path shows, to preselect what added files relate to ("" where no step is open). */
export function stepOf(path: string): string {
  const page = /^\/projects\/[^/]+(\/[^/]+)?/.exec(path)?.[1] ?? "";
  return { "/start": "start", "/inputs": "inputs", "/plan": "review", "": "run" }[page] ?? "";
}

export function AddData({ projectId, step: initial, onClose }: { projectId: string; step: string; onClose: () => void }) {
  const { run, busy } = useMutation();
  const [files, setFiles] = useState<{ file: File; goes: Goes }[]>([]);
  const [step, setStep] = useState(initial);
  const [task, setTask] = useState("");
  const [added, setAdded] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [picker, setPicker] = useState(0);

  function pick(list: FileList | null) {
    setFiles(Array.from(list ?? []).map((file) => ({ file, goes: WORKBOOK.test(file.name) ? "client" : "annex" })));
    setProblem(null);
  }

  async function add() {
    const notes: string[] = [];
    const problems: string[] = [];
    const kept: File[] = [];   // the files refused stay listed, so the person can switch where they go and try again
    const groups = new Map<Goes, File[]>();
    files.forEach(({ file, goes }) => groups.set(goes, [...(groups.get(goes) ?? []), file]));
    for (const [goes, list] of groups) {
      const form = new FormData();
      list.forEach((f) => form.append("files", f));
      form.set("step", step);
      if (task.trim()) form.set("task", task.trim());
      const names = list.map((f) => f.name).join(", ");
      let failed: string | null;
      if (goes === "client") {
        ({ problem: failed } = await run(() => upload("/api/v1/projects/{project_id}/client-data", { project_id: projectId }, form)));
      } else {
        form.set("role", goes);
        ({ problem: failed } = await run(() => upload("/api/v1/projects/{project_id}/documents", { project_id: projectId }, form)));
      }
      if (failed) {
        problems.push(`${names}: ${failed}`);
        kept.push(...list);
      } else if (goes === "client") {
        notes.push(`${names}: added as client data, read on Inputs`);
      } else {
        notes.push(`${names}: added as ${ADDED_AS[goes]}${step === "start" ? "; “Read the proposal again” on Start reads it into the brief" : ""}`);
      }
    }
    setAdded((before) => [...before, ...notes]);
    setProblem(problems.join(" · ") || null);
    setFiles((before) => before.filter(({ file }) => kept.includes(file)));
    if (!kept.length) setPicker((n) => n + 1);   // a fresh file picker once everything is in
  }

  return (
    <Dialog title="Add data" onClose={onClose} testId="add-data">
      <p className="muted add-data-lede">
        Files for any step of this project: PDF, Word, Excel, CSV, JSON, Markdown or text. Each is kept in the project&apos;s
        library with what it relates to; nothing is shared with another project.
      </p>
      <label className="add-data-field">
        <span>Files</span>
        <input key={picker} type="file" multiple accept={ACCEPT} disabled={busy} data-testid="add-data-files"
               onChange={(e) => pick(e.target.files)} />
      </label>
      {files.length > 0 && (
        <ul className="add-data-list">
          {files.map(({ file, goes }, i) => (
            <li key={`${file.name}-${i}`}>
              <span className="add-data-name">{file.name}</span>
              <select aria-label={`Where ${file.name} goes`} value={goes} data-testid={`add-data-goes-${file.name}`}
                      onChange={(e) => setFiles(files.map((f, j) => (j === i ? { ...f, goes: e.target.value as Goes } : f)))}>
                {GOES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </li>
          ))}
        </ul>
      )}
      <div className="add-data-relates">
        <label className="add-data-field">
          <span>Relates to</span>
          <select value={step} data-testid="add-data-step" onChange={(e) => setStep(e.target.value)}>
            <option value="">choose a step</option>
            {RELATED_STEPS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="add-data-field">
          <span>Task <span className="muted">(optional)</span></span>
          <input type="text" maxLength={120} value={task} placeholder="e.g. Formulations, the food-effect study"
                 data-testid="add-data-task" onChange={(e) => setTask(e.target.value)} />
        </label>
      </div>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      {added.length > 0 && (
        <div className="banner ok add-data-done" data-testid="add-data-done">
          {added.join(" · ")}.{" "}
          <Link href={`/projects/${encodeURIComponent(projectId)}/library`} onClick={onClose}>See them in the library</Link>
        </div>
      )}
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose} data-testid="add-data-close">{added.length ? "Done" : "Cancel"}</button>
        <button type="button" className="btn primary" disabled={busy || !files.length || !step} onClick={add}
                data-testid="add-data-submit">
          {busy ? "Adding…" : "Add"}
        </button>
      </div>
    </Dialog>
  );
}
