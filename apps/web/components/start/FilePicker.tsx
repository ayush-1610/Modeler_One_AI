"use client";

// One upload for the proposal, its annexes and the client's data files (map rows p0-files, p3-upload). Each file says
// what it is, guessed from its type and changeable: the proposal's documents are read for the brief, the client's files
// go straight to Inputs.

import { useState } from "react";

export type FileRole = "proposal" | "client";
export type Picked = { file: File; role: FileRole };

export const ACCEPT = ".pdf,.docx,.md,.markdown,.txt,.csv,.tsv,.xlsx,.xlsm,.xls";

/** A workbook or a table is the client's data; a PDF, Word, Markdown or text file is part of the proposal. */
export function guessRole(name: string): FileRole {
  return /\.(xlsx|xlsm|xls|csv|tsv)$/i.test(name) ? "client" : "proposal";
}

export function FilePicker({ picked, onChange, testId = "start-files" }: {
  picked: Picked[]; onChange: (next: Picked[]) => void; testId?: string;
}) {
  const [dragging, setDragging] = useState(false);
  function add(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list).filter((f) => !picked.some((p) => p.file.name === f.name && p.file.size === f.size));
    onChange([...picked, ...incoming.map((file) => ({ file, role: guessRole(file.name) }))]);
  }
  return (
    <div className="file-picker">
      <label className={`dropzone${dragging ? " over" : ""}`}
             onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
             onDrop={(e) => { e.preventDefault(); setDragging(false); add(e.dataTransfer.files); }}>
        <input type="file" data-testid={testId} multiple accept={ACCEPT} onChange={(e) => { add(e.target.files); e.target.value = ""; }}
               hidden />
        <strong>Drop the proposal, its annexes and the client&apos;s files here</strong> or click to choose
        <span className="muted">PDF, Word (.docx), Markdown, text, CSV or Excel</span>
      </label>
      {picked.length > 0 && (
        <ul className="picked">
          {picked.map((p, i) => (
            <li key={`${p.file.name}-${p.file.size}`}>
              <span className="picked-name">{p.file.name}</span>
              <span className="muted">{Math.max(1, Math.round(p.file.size / 1024))} KB</span>
              <select aria-label={`What ${p.file.name} is`} value={p.role}
                      onChange={(e) => onChange(picked.map((x, j) => (j === i ? { ...x, role: e.target.value as FileRole } : x)))}>
                <option value="proposal">proposal or annex</option>
                <option value="client">client data</option>
              </select>
              <button type="button" className="link-btn" onClick={() => onChange(picked.filter((_, j) => j !== i))}>Remove</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
