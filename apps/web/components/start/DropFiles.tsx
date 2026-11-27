"use client";

// One drop zone of the "Start from proposal" page (plan 2026-11-27 step 1; the owner's D2: nothing is tagged at upload,
// the Data room's A7 sorts the client's files from their content). The page has two: the technical proposal and its
// annexes, read for the brief, and the client's files, which go to the Data room as they came.

import { useState } from "react";

export function DropFiles({ files, onChange, title, hint, accept, testId }: {
  files: File[]; onChange: (next: File[]) => void; title: string; hint: string; accept?: string; testId: string;
}) {
  const [dragging, setDragging] = useState(false);
  function add(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list).filter((f) => !files.some((p) => p.name === f.name && p.size === f.size));
    onChange([...files, ...incoming]);
  }
  return (
    <div className="file-picker">
      <label className={`dropzone${dragging ? " over" : ""}`}
             onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
             onDrop={(e) => { e.preventDefault(); setDragging(false); add(e.dataTransfer.files); }}>
        <input type="file" data-testid={testId} multiple accept={accept} hidden
               onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
        <strong>{title}</strong> or click to choose
        <span className="muted">{hint}</span>
      </label>
      {files.length > 0 && (
        <ul className="picked" data-testid={`${testId}-list`}>
          {files.map((f, i) => (
            <li key={`${f.name}-${f.size}`}>
              <span className="picked-name">{f.name}</span>
              <span className="muted">{Math.max(1, Math.round(f.size / 1024))} KB</span>
              <button type="button" className="link-btn" onClick={() => onChange(files.filter((_, j) => j !== i))}
                      aria-label={`Remove ${f.name}`}>Remove</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
