"use client";

// The one drop zone of the "Start from proposal" page (plan 2026-11-27 step 1; the owner, 2026-11-28: "can we have just
// one as we had"). Everything goes in together: the technical proposal, its annexes and the client's files, or one zip.
// No tag is asked (D2: the Data room's A7 sorts the client's files from their content). One mark per file, set or
// cleared with a click (the owner's rule 2): "Proposal", read for the brief; a file named like one (proposal,
// quotation, SOW) arrives marked. Every other file goes to the Data room. A ZIP is never the proposal.

import { useState } from "react";

import { isProposalName } from "@/lib/fileTags";

export type Dropped = { file: File; proposal: boolean };

const isZip = (name: string) => /\.zip$/i.test(name);

export function DropFiles({ files, onChange, testId }: {
  files: Dropped[]; onChange: (next: Dropped[]) => void; testId: string;
}) {
  const [dragging, setDragging] = useState(false);
  function add(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list).filter((f) => !files.some((p) => p.file.name === f.name && p.file.size === f.size));
    onChange([...files, ...incoming.map((file) => ({ file, proposal: isProposalName(file.name) }))]);
  }
  return (
    <div className="file-picker">
      <label className={`dropzone${dragging ? " over" : ""}`}
             onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
             onDrop={(e) => { e.preventDefault(); setDragging(false); add(e.dataTransfer.files); }}>
        <input type="file" data-testid={testId} multiple hidden onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
        <strong>Drop the proposal, its annexes and everything the client sent here</strong> or click to choose
        <span className="muted">Many files or one zip: PDFs, Word, PowerPoint, spreadsheets, text and SAS exports, scans (read
          by OCR). Nothing to tag: the agents sort the client&apos;s files.</span>
      </label>
      {files.length > 0 && (
        <ul className="picked" data-testid={`${testId}-list`}>
          {files.map((p, i) => (
            <li key={`${p.file.name}-${p.file.size}`}>
              <span className="picked-name">{p.file.name}</span>
              <span className="muted">{Math.max(1, Math.round(p.file.size / 1024))} KB</span>
              {isZip(p.file.name) ? <span className="muted">the client&apos;s files</span> : (
                <label className="picked-mark">
                  <input type="checkbox" checked={p.proposal} data-testid={`mark-proposal-${p.file.name}`}
                         onChange={() => onChange(files.map((x, j) => (j === i ? { ...x, proposal: !x.proposal } : x)))} />
                  Proposal
                </label>
              )}
              <button type="button" className="link-btn" onClick={() => onChange(files.filter((_, j) => j !== i))}
                      aria-label={`Remove ${p.file.name}`}>Remove</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
