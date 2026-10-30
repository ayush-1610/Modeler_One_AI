"use client";

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Block } from "@/components/start/Blocks";
import { apiFile } from "@/lib/api";
import type { BriefView } from "@/lib/brief";

/** Block 5: what only the client can send (page review 1, the owner's decision 2b of 2026-10-29), from the data plan,
 *  which follows the brief. The agents find the rest in the documents and the literature, so nothing else is listed.
 *  The request downloads as the client-data workbook with these items in front, for the client to fill and return. */
export function ClientRequest({ projectId, view }: { projectId: string; view: BriefView }) {
  const lines = view.start.client_request;
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
    <Block n={5} title="What to request from the client" testId="start-request"
           lede="Only what the client alone holds. The agents find the rest in the documents and the literature.">
      {lines.length ? (
        <>
          <ul className="client-request" data-testid="client-request">
            {lines.map((l) => (
              <li key={`${l.req_id}:${l.product ?? ""}`} data-testid={`request-${l.req_id}`}>
                <strong>{l.what}</strong>{l.product ? ` (${l.product})` : ""}
                <span className="muted"> · for {l.why}{l.required ? "" : " · if available"}</span>
              </li>
            ))}
          </ul>
          <button type="button" className="btn" data-testid="request-download" onClick={download}>
            Download the request (.xlsx)
          </button>
          {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
        </>
      ) : (
        <p className="muted" data-testid="client-request-empty">Nothing yet: the applications and the proposal name no data that
          only the client holds.</p>
      )}
    </Block>
  );
}
