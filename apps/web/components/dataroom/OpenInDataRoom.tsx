"use client";

// "Open in the Data room" on the earlier Inputs page (plan 2026-11-21 v2 §4): the project's recorded client files are
// added to the Data room once each (`POST …/dataroom/import-existing`), then the Data room opens, where Run reads them.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "@/lib/api";
import { useMutation } from "@/lib/hooks";

import { UPLOADS } from "./acts";

export function OpenInDataRoom({ projectId }: { projectId: string }) {
  const router = useRouter();
  const { run, busy } = useMutation();
  const [problem, setProblem] = useState<string | null>(null);
  const href = `/projects/${encodeURIComponent(projectId)}/dataroom`;
  return (
    <p className="dr-entry" data-testid="inputs-dataroom">
      <a href={href} data-testid="open-in-dataroom" aria-disabled={busy} onClick={async (e) => {
        e.preventDefault();
        if (busy) return;
        const got = await run(() => send("post", "/api/v1/projects/{project_id}/dataroom/import-existing", { project_id: projectId }),
                              { reads: [UPLOADS] });
        if (got.problem) setProblem(got.problem); else router.push(href);
      }}>{busy ? "Opening the Data room…" : "Open in the Data room"}</a>
      <span className="muted"> · the client&apos;s files read again, every value with its source</span>
      {problem && <span className="dr-bad" role="alert"> · {problem}</span>}
    </p>
  );
}
