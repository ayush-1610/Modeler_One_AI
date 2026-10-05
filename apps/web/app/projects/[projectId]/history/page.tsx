import Link from "next/link";

import { PhaseRail } from "@/components/PhaseRail";
import { ApiProblem, Card, StatusChip } from "@/components/ui";
import { getArtifacts, getAudit, getHistory, getPhases, type Change } from "@/lib/pipeline";

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function ChangeRow({ change }: { change: Change }) {
  return (
    <tr>
      <td><code>{change.path}</code></td>
      <td>{change.kind === "added" ? "—" : <span className="diff-del">{show(change.before)}</span>}</td>
      <td>{change.kind === "removed" ? "—" : <span className="diff-add">{show(change.after)}</span>}</td>
    </tr>
  );
}

/** Versions, staleness and the audit trail of a project (plan §13): nothing is ever deleted, only superseded. */
export default async function HistoryPage({
  params, searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ kind?: string; id?: string }>;
}) {
  const { projectId } = await params;
  const { kind, id } = await searchParams;
  const [artifacts, phases, audit, history] = await Promise.all([
    getArtifacts(projectId),
    getPhases(projectId),
    getAudit(projectId),
    kind && id ? getHistory(projectId, kind, id) : Promise.resolve(null),
  ]);
  const problem = artifacts.problem ?? phases.problem ?? audit.problem;

  return (
    <main>
      <h1>History</h1>
      <PhaseRail projectId={projectId} />
      <p className="muted">
        Every phase output is a version that names the exact inputs it was made from. An edit creates a new version;
        anything made from the old one is marked <strong>stale</strong> with its reason, never deleted or silently redone.
      </p>
      {problem && <ApiProblem problem={problem} />}

      {phases.data && phases.data.stale.length > 0 && (
        <Card title="Stale — made from inputs that have since changed">
          <table>
            <thead><tr><th>Artifact</th><th>Why</th></tr></thead>
            <tbody>
              {phases.data.stale.map((s) => (
                <tr key={`${s.ref.kind}/${s.ref.id}`}>
                  <td><code>{s.ref.kind}/{s.ref.id}@v{s.ref.version}</code></td>
                  <td>{s.reasons.join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Card title="Artifacts">
        {artifacts.data && artifacts.data.length > 0 ? (
          <table>
            <thead><tr><th>Artifact</th><th className="num">Version</th><th>Status</th><th>Last change</th><th>By</th></tr></thead>
            <tbody>
              {artifacts.data.map((a) => (
                <tr key={`${a.kind}/${a.id}`}>
                  <td>
                    <Link href={`/projects/${projectId}/history?kind=${a.kind}&id=${encodeURIComponent(a.id)}`}>
                      <code>{a.kind}/{a.id}</code>
                    </Link>
                  </td>
                  <td className="num">v{a.version}</td>
                  <td><StatusChip status={a.status} /></td>
                  <td>{a.reason || "—"}</td>
                  <td className="muted">{a.created_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted" style={{ margin: 0 }}>Nothing recorded yet. Start with the technical proposal (P0).</p>
        )}
      </Card>

      {history?.data && (
        <Card title={`${kind}/${id}: every version`}>
          {history.data.map((row) => (
            <div key={row.version} style={{ marginBottom: 16 }}>
              <div className="row">
                <strong>v{row.version}</strong>
                <StatusChip status={row.status} />
                <span className="muted">{new Date(row.created_at).toLocaleString()} · {row.created_by}</span>
                <span>{row.reason}</span>
              </div>
              {row.approvals.map((a) => (
                <p key={a.at} className="muted" style={{ margin: "4px 0" }}>
                  {a.meaning} by {a.printed_name || a.by} · {new Date(a.at).toLocaleString()}
                  {a.signature_id ? " · signed (Part 11)" : ""}
                </p>
              ))}
              {row.changes.length > 0 && (
                <table>
                  <thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead>
                  <tbody>{row.changes.slice(0, 200).map((c) => <ChangeRow key={c.path} change={c} />)}</tbody>
                </table>
              )}
            </div>
          ))}
        </Card>
      )}

      <Card title="Audit trail" action={audit.data ? (
        <span className={`chip ${audit.data.chain_verifies ? "low" : "high"}`}>
          {audit.data.chain_verifies ? "hash chain verifies" : "hash chain BROKEN"}
        </span>) : undefined}>
        {audit.data && audit.data.events.length > 0 ? (
          <table>
            <thead><tr><th className="num">#</th><th>When</th><th>Who</th><th>Action</th><th>Record</th><th>Reason</th></tr></thead>
            <tbody>
              {audit.data.events.map((e) => (
                <tr key={e.seq}>
                  <td className="num">{e.seq}</td>
                  <td className="muted">{new Date(e.occurred_at).toLocaleString()}</td>
                  <td>{e.actor}</td>
                  <td><code>{e.action}</code></td>
                  <td><code>{e.resource_type}:{e.resource_id.split("/").slice(1).join("/")}</code></td>
                  <td>{e.reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted" style={{ margin: 0 }}>No events yet.</p>
        )}
      </Card>
    </main>
  );
}
