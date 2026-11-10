"use client";

// "Add data" (docs/plans/2026-10-28-project-document-library.md, PR 2; the owner's decisions 10–12 of 2026-10-29): a
// centred card over the page, opened from the sidebar at any step of a project. The person picks files and says what
// they relate to: a step and, optionally, a task. Each file goes where its name says: client data with its tag
// (formulation or dissolution, a clinical study and which one, bioanalytical, in vitro or physico-chemistry, other;
// plan 2026-11-03 §3.1), read on Inputs, or a document (annex, paper, context, proposal, other); the guess is switched
// per file. Everything added is kept in this project's library, with who added it and when. Every file is read for its
// data (plan 2026-11-10, R2; the owner's decision 1): client data always, a document unless "Read for data" is unticked;
// the agent reads them one after the other on Inputs. Files go up a few at a time, so any number of files can be added.

import Link from "next/link";
import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { ReadingStatus } from "@/components/inputs/ReadingTray";
import { TagProposals, type UploadedFile } from "@/components/library/TagProposals";
import { upload } from "@/lib/api";
import { guessStudy, guessTag, TAG_KINDS, TAG_LABELS, type TagKind, tagsField } from "@/lib/fileTags";
import { useMutation } from "@/lib/hooks";

type DocRole = "annex" | "paper" | "context" | "proposal" | "other";
type Goes = `client:${TagKind}` | `doc:${DocRole}`;

const DOCS: [DocRole, string][] = [
  ["annex", "Annex"], ["paper", "Paper"], ["context", "Context"], ["proposal", "Proposal"], ["other", "Other document"],
];
const ADDED_AS: Record<DocRole, string> = {
  annex: "an annex", paper: "a paper", context: "context", proposal: "part of the proposal", other: "a document",
};

/** Where a file goes by its name: client data with its tag, else a document (an annex). */
function guessGoes(name: string): Goes {
  const tag = guessTag(name);
  return tag === "proposal" ? (WORKBOOK.test(name) ? "client:other" : "doc:annex") : `client:${tag}`;
}
export const RELATED_STEPS: [string, string][] = [["start", "Start"], ["inputs", "Inputs"], ["review", "Review & sign"], ["run", "Run"]];
const WORKBOOK = /\.(xlsx|xlsm|xls|csv|tsv)$/i;
const ACCEPT = ".pdf,.docx,.md,.markdown,.txt,.json,.csv,.tsv,.xlsx,.xlsm,.xls,.png,.jpg,.jpeg";
/** What the reading agent reads for data (the API's READ_FOR_DATA). */
const READABLE = /\.(pdf|docx|xlsx|xlsm|xls|csv|tsv)$/i;
/** Each upload carries at most this many files and bytes: a large delivery goes up in several short requests. */
const BATCH_FILES = 8;
const BATCH_BYTES = 40 * 1024 * 1024;

/** The files in batches of at most BATCH_FILES and BATCH_BYTES (a larger file goes on its own). */
export function batches<T extends { file: { size: number } }>(list: T[]): T[][] {
  const out: T[][] = [];
  let current: T[] = [];
  let bytes = 0;
  for (const item of list) {
    if (current.length && (current.length >= BATCH_FILES || bytes + item.file.size > BATCH_BYTES)) {
      out.push(current);
      current = [];
      bytes = 0;
    }
    current.push(item);
    bytes += item.file.size;
  }
  if (current.length) out.push(current);
  return out;
}

/** The step of the page a path shows, to preselect what added files relate to ("" where no step is open). */
export function stepOf(path: string): string {
  const page = /^\/projects\/[^/]+(\/[^/]+)?/.exec(path)?.[1] ?? "";
  return { "/start": "start", "/inputs": "inputs", "/plan": "review", "": "run" }[page] ?? "";
}

export function AddData({ projectId, step: initial, onClose }: { projectId: string; step: string; onClose: () => void }) {
  const { run, busy } = useMutation();
  const [files, setFiles] = useState<{ file: File; goes: Goes; study: string; read: boolean }[]>([]);
  const [uploaded, setUploaded] = useState<UploadedFile[]>([]);
  const [step, setStep] = useState(initial);
  const [task, setTask] = useState("");
  const [added, setAdded] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [picker, setPicker] = useState(0);

  function pick(list: FileList | null) {
    setFiles(Array.from(list ?? []).map((file) => {
      const goes = guessGoes(file.name);
      return { file, goes, study: goes === "client:clinical" ? guessStudy(file.name) : "", read: true };
    }));
    setProblem(null);
  }

  async function add() {
    const notes: string[] = [];
    const problems: string[] = [];
    const kept: File[] = [];   // the files refused stay listed, so the person can switch where they go and try again
    const groups = new Map<string, typeof files>();   // the client files go up together, with their tags
    files.forEach((f) => {
      const key = f.goes.startsWith("client:") ? "client" : `${f.goes}:${f.read && READABLE.test(f.file.name) ? "read" : "keep"}`;
      groups.set(key, [...(groups.get(key) ?? []), f]);
    });
    for (const [key, group] of groups) {
      const role = key.startsWith("doc:") ? (key.split(":")[1] as DocRole) : null;
      const read = key.endsWith(":read");
      for (const list of batches(group)) {
        const form = new FormData();
        list.forEach(({ file }) => form.append("files", file));
        form.set("step", step);
        if (task.trim()) form.set("task", task.trim());
        const names = list.map(({ file }) => file.name).join(", ");
        let failed: string | null;
        if (role === null) {
          form.set("tags", tagsField(list.map(({ file, goes, study }) => ({ file, tag: goes.slice(7) as TagKind, study }))));
          const result = await run(() => upload("/api/v1/projects/{project_id}/client-data", { project_id: projectId }, form));
          failed = result.problem;
          if (!failed && result.data) setUploaded((before) => [...before, ...result.data!.read]);
          if (!failed) notes.push(`${names}: added as client data; the agent reads it on Inputs`);
        } else {
          form.set("role", role);
          if (read) form.set("read", "true");
          const result = await run(() => upload("/api/v1/projects/{project_id}/documents", { project_id: projectId }, form));
          failed = result.problem;
          if (!failed && result.data) {
            const reading = result.data.reading;
            const as = `added as ${ADDED_AS[role]}`;
            if (reading.length) notes.push(`${reading.join(", ")}: ${as}; the agent reads it for data on Inputs`);
            const stored = list.map(({ file }) => file.name).filter((name) => !reading.includes(name));
            if (stored.length) notes.push(`${stored.join(", ")}: ${as}${step === "start" ? "; “Read the proposal again” on Start reads it into the brief" : ""}`);
            if (result.data.not_read.length) problems.push(...result.data.not_read);
          }
        }
        if (failed) {
          problems.push(`${names}: ${failed}`);
          kept.push(...list.map(({ file }) => file));
        }
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
        Files for any step of this project: Excel, CSV, Word, PDF, JSON, Markdown or text, as many as the delivery has.
        Say what each is: client data with its tag (a hint for reading it, not a fact) or a document. The agent reads
        each PDF, Word and Excel file for its data, documents too unless you untick &ldquo;Read for data&rdquo;. Each is
        kept in the project&apos;s library with what it relates to; nothing is shared with another project.
      </p>
      <label className="add-data-field">
        <span>Files</span>
        <input key={picker} type="file" multiple accept={ACCEPT} disabled={busy} data-testid="add-data-files"
               onChange={(e) => pick(e.target.files)} />
      </label>
      {files.length > 0 && (
        <ul className="add-data-list">
          {files.map(({ file, goes, study }, i) => (
            <li key={`${file.name}-${i}`}>
              <span className="add-data-name">{file.name}</span>
              <span className="tag-fields">
                <select aria-label={`Where ${file.name} goes`} value={goes} data-testid={`add-data-goes-${file.name}`}
                        onChange={(e) => {
                          const next = e.target.value as Goes;
                          setFiles(files.map((f, j) => (j === i ? { ...f, goes: next,
                            study: next === "client:clinical" ? f.study || guessStudy(f.file.name) : "" } : f)));
                        }}>
                  <optgroup label="Client data (read on Inputs)">
                    {TAG_KINDS.map((kind) => <option key={kind} value={`client:${kind}`}>{TAG_LABELS[kind]}</option>)}
                  </optgroup>
                  <optgroup label="Document">
                    {DOCS.map(([role, label]) => <option key={role} value={`doc:${role}`}>{label}</option>)}
                  </optgroup>
                </select>
                {goes.startsWith("doc:") && READABLE.test(file.name) && (
                  <label className="add-data-read" title="The reading agent reads it for study data, profiles and dissolution">
                    <input type="checkbox" checked={files[i].read} data-testid={`add-data-read-${file.name}`}
                           onChange={(e) => setFiles(files.map((f, j) => (j === i ? { ...f, read: e.target.checked } : f)))} />
                    Read for data
                  </label>
                )}
                {goes === "client:clinical" && (
                  <input type="text" maxLength={80} value={study} aria-label={`Which study ${file.name} belongs to`}
                         placeholder="Which study (optional)"
                         onChange={(e) => setFiles(files.map((f, j) => (j === i ? { ...f, study: e.target.value } : f)))} />
                )}
              </span>
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
      <TagProposals projectId={projectId} files={uploaded} testId="add-data-tag-proposals" />
      {added.length > 0 && (
        <div className="banner ok add-data-done" data-testid="add-data-done">
          {added.join(" · ")}.{" "}
          <Link href={`/projects/${encodeURIComponent(projectId)}/library`} onClick={onClose}>See them in the library</Link>
        </div>
      )}
      {added.length > 0 && <ReadingStatus projectId={projectId} onOpen={onClose} />}
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
