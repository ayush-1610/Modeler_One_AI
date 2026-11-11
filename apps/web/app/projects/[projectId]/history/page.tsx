import Link from "next/link";

import { preloadSteps, Stepper } from "@/components/kit/Stepper";
import { ApiProblem, Card, StatusChip } from "@/components/ui";
import { getArtifacts, getAudit, getHistory, getStale, type Change } from "@/lib/pipeline";
import { Hero } from "@/components/kit";
import { Clip } from "@/components/kit/Clip";

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

const AUDIT_SHOWN = 50;
const ARTIFACTS_SHOWN = 25;

function ChangeRow({ change }: { change: Change }) {
  return (
    <tr>
      <td><code>{change.path}</code></td>
      <td>{change.kind === "added" ? "—" : <span className="diff-del"><Clip text={show(change.before)} /></span>}</td>
      <td>{change.kind === "removed" ? "—" : <span className="diff-add"><Clip text={show(change.after)} /></span>}</td>
    </tr>
  );
}

/** Versions, staleness and the audit trail of a project (plan §13): nothing is ever deleted, only superseded. */
export default async function HistoryPage({
  params, searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ kind?: string; id?: string; show?: string; audit?: string; artifacts?: string }>;
}) {
  const { projectId } = await params;
  const { kind, id, show: only, audit: auditAll, artifacts: artifactsAll } = await searchParams;
  preloadSteps(projectId); // the step bar's read runs beside the page's own, not after them (audit item 9)
  const [artifacts, stale, audit, history] = await Promise.all([
    getArtifacts(projectId),
    getStale(projectId),
    getAudit(projectId),
    kind && id ? getHistory(projectId, kind, id) : Promise.resolve(null),
  ]);
  const problem = artifacts.problem ?? stale.problem ?? audit.problem;
  // the artifacts by kind, with how many of each; one kind at a time when asked (`?show=evidence`)
  const kinds = new Map<string, number>();
  for (const a of artifacts.data ?? []) kinds.set(a.kind, (kinds.get(a.kind) ?? 0) + 1);
  const matching = (artifacts.data ?? []).filter((a) => !only || a.kind === only);
  const listed = artifactsAll === "all" ? matching : matching.slice(0, ARTIFACTS_SHOWN);
  const here = (q: Record<string, string | undefined>) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ kind, id, show: only, audit: auditAll, artifacts: artifactsAll, ...q })) if (v) p.set(k, v);
    const s = p.toString();
    return `/projects/${projectId}/history${s ? `?${s}` : ""}`;
  };
  // the audit trail newest first; the last 50 unless all are asked for (`?audit=all`)
  const events = [...(audit.data?.events ?? [])].reverse();
  const shownEvents = auditAll === "all" ? events : events.slice(0, AUDIT_SHOWN);

  return (
    <main>
      <Hero tone="history" eyebrow="Project record" title="History"
            lede={<>Every phase output is a version that names the exact inputs it was made from. An edit creates a new version;
              anything made from the old one is marked <strong>stale</strong> with its reason, never deleted or silently redone.</>} />
      <Stepper projectId={projectId} />
      {problem && <ApiProblem problem={problem} />}

      {stale.data && stale.data.length > 0 && (
        <Card title="Stale — made from inputs that have since changed">
          <table>
            <thead><tr><th>Artifact</th><th>Why</th></tr></thead>
            <tbody>
              {stale.data.map((s) => (
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
        {kinds.size > 1 && (
          <nav className="filter-links" aria-label="Show artifacts of one kind" data-testid="history-kinds">
            <a href={here({ show: undefined })} aria-current={!only}>All<span className="count">{artifacts.data?.length ?? 0}</span></a>
            {[...kinds].map(([k, n]) => (
              <a key={k} href={here({ show: k })} aria-current={only === k}>{k}<span className="count">{n}</span></a>
            ))}
          </nav>
        )}
        {listed.length > 0 ? (
          <>
          <table>
            <thead><tr><th>Artifact</th><th className="num">Version</th><th>Status</th><th>Last change</th><th>By</th></tr></thead>
            <tbody>
              {listed.map((a) => (
                <tr key={`${a.kind}/${a.id}`}>
                  <td>
                    <Link href={here({ kind: a.kind, id: a.id })}>
                      <code>{a.kind}/{a.id}</code>
                    </Link>
                  </td>
                  <td className="num">v{a.version}</td>
                  <td><StatusChip status={a.status} /></td>
                  <td><Clip text={a.reason} /></td>
                  <td className="muted">{a.created_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {matching.length > listed.length && (
            <p className="muted" style={{ margin: "12px 0 0" }} data-testid="artifacts-more">
              {listed.length} of {matching.length}. <a href={here({ artifacts: "all" })}>Show all {matching.length}</a>
            </p>
          )}
          </>
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
                <span style={{ flex: 1, minWidth: 0 }}><Clip text={row.reason} /></span>
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

      <Card title={`Audit trail${events.length ? ` · ${events.length} events, newest first` : ""}`} action={audit.data ? (
        <span className={`chip ${audit.data.chain_verifies ? "low" : "high"}`}>
          {audit.data.chain_verifies ? "hash chain verifies" : "hash chain BROKEN"}
        </span>) : undefined}>
        {events.length > 0 ? (
          <>
          <table>
            <thead><tr><th className="num">#</th><th>When</th><th>Who</th><th>Action</th><th>Record</th><th>Reason</th></tr></thead>
            <tbody>
              {shownEvents.map((e) => (
                <tr key={e.seq}>
                  <td className="num">{e.seq}</td>
                  <td className="muted">{new Date(e.occurred_at).toLocaleString()}</td>
                  <td>{e.actor}</td>
                  <td><code>{e.action}</code></td>
                  <td><code>{e.resource_type}:{e.resource_id.split("/").slice(1).join("/")}</code></td>
                  <td><Clip text={e.reason} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {events.length > shownEvents.length && (
            <p className="muted" style={{ margin: "12px 0 0" }} data-testid="audit-more">
              The {shownEvents.length} most recent of {events.length}.{" "}
              <a href={here({ audit: "all" })}>Show all {events.length}</a>
            </p>
          )}
          </>
        ) : (
          <p className="muted" style={{ margin: 0 }}>No events yet.</p>
        )}
      </Card>
    </main>
  );
}
