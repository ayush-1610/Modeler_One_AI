"use client";

// After an upload (docs/plans/2026-11-03-inputs-and-client-data.md §3.1): the files whose content says something other
// than their tag, with what prompted it, quoted; the person uses the proposed tag or keeps theirs, with no reason asked.
// Files that need OCR, or could not be read, are said too, so nothing is skipped silently.

import { useState } from "react";

import { post, type Schema } from "@/lib/api";
import { tagLabel } from "@/lib/fileTags";

export type UploadedFile = {
  file: string; sha256?: string | null; problem?: string | null; needs_ocr?: boolean;
  tag?: Schema<"FileTagView"> | null; tag_proposal?: Schema<"TagProposalView"> | null;
};

export function needsALook(files: UploadedFile[]): boolean {
  return files.some((f) => f.problem || f.needs_ocr || f.tag_proposal?.decided === "open");
}

export function TagProposals({ projectId, files, testId = "tag-proposals" }: {
  projectId: string; files: UploadedFile[]; testId?: string;
}) {
  const [decided, setDecided] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const shown = files.filter((f) => f.problem || f.needs_ocr || f.tag_proposal?.decided === "open");
  if (!shown.length) return null;

  async function decide(f: UploadedFile, kind: Schema<"FileTagView">["kind"], said: string) {
    if (!f.sha256) return;
    const env = await post("/api/v1/projects/{project_id}/documents/{sha256}:tag", { project_id: projectId, sha256: f.sha256 },
                           { kind, study: f.tag?.study ?? "" });
    if (env.errors?.length) {
      setProblem(env.errors[0].message);
      return;
    }
    setDecided((before) => ({ ...before, [f.file]: said }));
  }

  return (
    <ul className="tag-proposals" data-testid={testId}>
      {shown.map((f) => {
        const proposal = f.tag_proposal?.decided === "open" ? f.tag_proposal : null;
        return (
          <li key={f.file} data-testid={`tag-proposal-${f.file}`}>
            <span className="picked-name">{f.file}</span>
            {f.problem && <span className="chip high">Not read: {f.problem}</span>}
            {f.needs_ocr && <span className="chip medium">Needs OCR: kept, not read yet</span>}
            {proposal && !decided[f.file] && (
              <span className="tag-proposal">
                <span>
                  <strong>The content suggests “{tagLabel(proposal.kind)}”</strong> (tagged “{tagLabel(f.tag?.kind)}”): {proposal.why}.
                </span>
                <span className="row">
                  <button type="button" className="btn small primary" data-testid={`tag-use-${f.file}`}
                          onClick={() => decide(f, proposal.kind, `now “${tagLabel(proposal.kind)}”`)}>
                    Use “{tagLabel(proposal.kind)}”
                  </button>
                  <button type="button" className="btn small" data-testid={`tag-keep-${f.file}`}
                          onClick={() => f.tag && decide(f, f.tag.kind, `kept “${tagLabel(f.tag.kind)}”`)}>
                    Keep “{tagLabel(f.tag?.kind)}”
                  </button>
                </span>
              </span>
            )}
            {decided[f.file] && <span className="chip low">Tag {decided[f.file]}</span>}
          </li>
        );
      })}
      {problem && <li className="banner err" role="alert">{problem}</li>}
    </ul>
  );
}
