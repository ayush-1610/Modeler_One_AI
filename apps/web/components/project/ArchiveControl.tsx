"use client";

// Archive or restore a project from inside it (P-23 Settings, the console redesign's slice 3; before, only from the
// Projects list, which keeps its own). Both need a reason, kept in the audit trail; archiving hides the project from the
// list and erases nothing. Only the owner does it (the API's rule, `ownership`): the others are told who does.

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { send } from "@/lib/api";
import { useMutation, type After } from "@/lib/hooks";

const DONE: After = { reads: ["/api/v1/projects"], server: true };

export function ArchiveControl({ projectId, name, archived, mayChange, ownerName }: {
  projectId: string; name: string; archived: boolean; mayChange: boolean; ownerName: string | null;
}) {
  const { run, busy } = useMutation();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const action = archived ? "restore" : "archive";
  if (!mayChange) return <p className="muted m-0" data-testid="settings-archive-owner">Only the owner, {ownerName ?? "the project's owner"}, archives or restores it.</p>;
  async function confirm() {
    const route = action === "archive" ? "/api/v1/projects/{project_id}:archive" : "/api/v1/projects/{project_id}:restore";
    const result = await run(() => send("post", route, { project_id: projectId }, { reason: reason.trim() }), DONE);
    if (result.problem) setProblem(result.problem);
    else setOpen(false);
  }
  return (
    <>
      <button type="button" className="btn" data-testid={`settings-${action}`} onClick={() => { setOpen(true); setReason(""); setProblem(null); }}>
        {archived ? "Restore the project" : "Archive the project"}
      </button>
      {open && (
        <Dialog title={`${archived ? "Restore" : "Archive"} ${name}`} size="narrow" onClose={() => setOpen(false)} testId="settings-archive-dialog">
          <p className="muted">
            {archived ? "The project is shown in the projects list again."
              : "The project is hidden from the projects list. Nothing it holds is changed or erased, and it can be restored."}
          </p>
          <label htmlFor="settings-archive-reason" className="muted fs-13">Why (kept in the audit trail)</label>
          <textarea id="settings-archive-reason" rows={2} value={reason} className="w-full" data-testid="settings-archive-reason"
                    onChange={(e) => setReason(e.target.value)} />
          {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
          <div className="dialog-actions">
            <button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button>
            <button type="button" className="btn primary" disabled={busy || !reason.trim()} data-testid="settings-archive-confirm"
                    onClick={confirm}>{archived ? "Restore" : "Archive"}</button>
          </div>
        </Dialog>
      )}
    </>
  );
}
