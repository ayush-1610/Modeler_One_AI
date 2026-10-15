"use client";

// Who may open this project (production readiness P3). A project's creator is its first member and adds the people
// who have signed in to this workspace; a person's access is their sign-in's `projects` and these memberships. Every
// change is in the audit trail; removing someone needs a reason, and a project keeps at least one member.

import { useState } from "react";

import { ApiProblem, Card } from "@/components/ui";
import { send } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";

export function MembersPanel({ projectId }: { projectId: string }) {
  const { data, problem } = useResource("/api/v1/projects/{project_id}/members", { project_id: projectId });
  const { run, busy } = useMutation();
  const [adding, setAdding] = useState("");
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState<{ ok: boolean; message: string } | null>(null);

  if (problem) return <Card title="Members"><ApiProblem problem={problem} /></Card>;
  if (!data) return null;

  async function add() {
    const result = await run(() => send("post", "/api/v1/projects/{project_id}/members", { project_id: projectId },
                                        { subject: adding, reason: reason.trim() }));
    setOutcome(result.problem ? { ok: false, message: result.problem } : { ok: true, message: "Member added." });
    if (!result.problem) {
      setAdding("");
      setReason("");
    }
  }

  async function remove(subject: string, name: string) {
    if (!reason.trim()) {
      setOutcome({ ok: false, message: `Say why ${name} no longer has access (the reason is kept in the audit trail).` });
      return;
    }
    const result = await run(() => send("post", "/api/v1/projects/{project_id}/members:remove", { project_id: projectId },
                                        { subject, reason: reason.trim() }));
    setOutcome(result.problem ? { ok: false, message: result.problem } : { ok: true, message: `${name} removed.` });
    if (!result.problem) setReason("");
  }

  return (
    <Card title="Members" action={<span className="muted">{data.members.length} with access</span>}>
      <div data-testid="members-panel">
        {!data.managed && (
          <p className="muted" style={{ marginTop: 0 }}>
            This deployment&apos;s development sign-in opens every project. Members take effect when people sign in
            through Keycloak.
          </p>
        )}
        <table>
          <thead><tr><th>Member</th><th>Added by</th><th>Since</th><th /></tr></thead>
          <tbody>
            {data.members.map((m) => (
              <tr key={m.subject} data-testid={`member-${m.subject}`}>
                <td>{m.name}</td>
                <td>{m.added_by}</td>
                <td>{m.added_at.slice(0, 10)}</td>
                <td className="num">
                  <button className="btn" disabled={busy || data.members.length < 2} onClick={() => remove(m.subject, m.name)}
                          title={data.members.length < 2 ? "A project keeps at least one member" : undefined}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="spread" style={{ marginTop: 10, gap: 8 }}>
          <select aria-label="Person to add" value={adding} onChange={(e) => setAdding(e.target.value)}
                  disabled={data.people.length === 0}>
            <option value="">{data.people.length ? "Add a person…" : "Everyone who has signed in is a member"}</option>
            {data.people.map((p) => <option key={p.subject} value={p.subject}>{p.name}</option>)}
          </select>
          <input aria-label="Reason" placeholder="Reason (required to remove)" value={reason} style={{ flex: 1 }}
                 onChange={(e) => setReason(e.target.value)} />
          <button className="btn" disabled={busy || !adding} onClick={add}>{busy ? "Saving…" : "Add member"}</button>
        </div>
        <span className={outcome?.ok ? "muted" : ""} data-testid="members-outcome">
          {outcome && (outcome.ok ? outcome.message : <span className="chip high">{outcome.message}</span>)}
        </span>
      </div>
    </Card>
  );
}
