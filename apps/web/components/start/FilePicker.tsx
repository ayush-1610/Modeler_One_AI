"use client";

// One upload for the proposal, its annexes and the client's data files (map rows p0-files, p3-upload), each tagged at a
// high level (docs/plans/2026-11-03-inputs-and-client-data.md §3.1; the owner, 2026-11-03): the proposal and its annexes
// are read for the brief; a client file says what it is (formulation or dissolution, a clinical study and which one,
// bioanalytical, in vitro or physico-chemistry, other). The tag is pre-filled from the name and changeable: it is a hint
// for reading the file, not a fact.

import { useState } from "react";

import { type FileTag, guessStudy, guessTag, TAG_KINDS, TAG_LABELS } from "@/lib/fileTags";

export type Picked = { file: File; tag: FileTag; study: string };

export const ACCEPT = ".pdf,.docx,.md,.markdown,.txt,.csv,.tsv,.xlsx,.xlsm,.xls,.png,.jpg,.jpeg";

export function picked(file: File): Picked {
  const tag = guessTag(file.name);
  return { file, tag, study: tag === "clinical" ? guessStudy(file.name) : "" };
}

/** The tag select and, for a clinical study, which one: shared by the "Start from proposal" page and "+ Add data". */
export function TagFields({ item, onChange, proposal = true, testId }: {
  item: Picked; onChange: (next: Picked) => void; proposal?: boolean; testId?: string;
}) {
  const name = item.file.name;
  return (
    <span className="tag-fields">
      <select aria-label={`What ${name} is`} value={item.tag} data-testid={testId}
              onChange={(e) => {
                const tag = e.target.value as FileTag;
                onChange({ ...item, tag, study: tag === "clinical" ? item.study || guessStudy(name) : "" });
              }}>
        {proposal && <option value="proposal">Proposal or annex (read for the brief)</option>}
        <optgroup label="Client data (read on Inputs)">
          {TAG_KINDS.map((kind) => <option key={kind} value={kind}>{TAG_LABELS[kind]}</option>)}
        </optgroup>
      </select>
      {item.tag === "clinical" && (
        <input type="text" maxLength={80} value={item.study} aria-label={`Which study ${name} belongs to`}
               placeholder="Which study (optional), e.g. EXZ-101" onChange={(e) => onChange({ ...item, study: e.target.value })} />
      )}
    </span>
  );
}

export function FilePicker({ picked: list, onChange, testId = "start-files" }: {
  picked: Picked[]; onChange: (next: Picked[]) => void; testId?: string;
}) {
  const [dragging, setDragging] = useState(false);
  function add(files: FileList | null) {
    if (!files) return;
    const incoming = Array.from(files).filter((f) => !list.some((p) => p.file.name === f.name && p.file.size === f.size));
    onChange([...list, ...incoming.map(picked)]);
  }
  return (
    <div className="file-picker">
      <label className={`dropzone${dragging ? " over" : ""}`}
             onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
             onDrop={(e) => { e.preventDefault(); setDragging(false); add(e.dataTransfer.files); }}>
        <input type="file" data-testid={testId} multiple accept={ACCEPT} onChange={(e) => { add(e.target.files); e.target.value = ""; }}
               hidden />
        <strong>Drop the proposal, its annexes and everything the client sent here</strong> or click to choose
        <span className="muted">Excel, CSV, Word (.docx), PDF, Markdown or text; scans and images are kept and flagged for OCR</span>
      </label>
      {list.length > 0 && (
        <>
          <p className="muted tag-lede">
            Say what each file is. The tag tells the agent where to look; if a file&apos;s content says otherwise, it proposes
            another tag and you keep one. Nothing is read into the project or confirmed here: that happens on Inputs.
          </p>
          <ul className="picked">
            {list.map((p, i) => (
              <li key={`${p.file.name}-${p.file.size}`}>
                <span className="picked-name">{p.file.name}</span>
                <span className="muted">{Math.max(1, Math.round(p.file.size / 1024))} KB</span>
                <TagFields item={p} onChange={(next) => onChange(list.map((x, j) => (j === i ? next : x)))} />
                <button type="button" className="link-btn" onClick={() => onChange(list.filter((_, j) => j !== i))}>Remove</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
