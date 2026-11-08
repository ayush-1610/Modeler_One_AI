"use client";

// What only the client can send, as one workbook to send them (page review 1, decision 2b): the data plan's client items
// in front of the client-data workbook, for the client to fill and return. On Inputs, beside what is still missing (the
// owner, 2026-11-06: not on Start, where the question and the scope are settled).

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { apiFile } from "@/lib/api";

export function ClientRequest({ projectId }: { projectId: string }) {
  const [problem, setProblem] = useState<string | null>(null);

  async function download() {
    const { file, problem: refused } = await apiFile(`/api/v1/projects/${encodeURIComponent(projectId)}/client-data/request.xlsx`);
    setProblem(file ? null : `The request could not be downloaded: ${refused}`);
    if (!file) return;
    const url = URL.createObjectURL(file);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${projectId}-data-request.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="client-request-download">
      <button type="button" className="link-btn" data-testid="request-download" onClick={download}>
        Download the request for the client (.xlsx)
      </button>
      <span className="muted"> · what only the client holds, in the client-data workbook</span>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </div>
  );
}
