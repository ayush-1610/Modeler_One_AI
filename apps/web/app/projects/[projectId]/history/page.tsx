import Link from "next/link";
import type { ReactNode } from "react";

import { StatusIndicator } from "@/components/kit/StatusIndicator";
import { AuditTable, SignatureTable } from "@/components/records/HistoryTables";
import { getArtifacts, getAudit, getHistory, getStale, type Change } from "@/lib/pipeline";
import { getSignatures } from "@/lib/reads";
import { ApiProblem, Hero } from "@/components/kit";
import { Clip } from "@/components/kit/Clip";

// A project's History (P-21, the console redesign's slice 7): one record at a time, in tabs whose choice is in the
// address (?tab=): the audit trail (`GET /audit`), the signatures given on its records (`GET /signatures`, R-N09: the
// decisions on its campaigns' escalations included, which the audit trail's filter leaves out), every artifact's
// versions (`GET /artifacts`, a version's changes from `/history`), and what is out of date (`GET /stale`). Whether
// the company's hash chain verifies is said in the header, on every tab. Nothing is ever deleted, only superseded.

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

const ARTIFACTS_SHOWN = 25;
const TABS = ["audit", "signatures", "versions", "stale"] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = { audit: "Audit trail", signatures: "Signatures", versions: "Versions", stale: "Out of date" };

function ChangeRow({ change }: { change: Change }) {
  return (
    <tr>
      <td><code>{change.path}</code></td>
      <td>{change.kind === "added" ? "—" : <span className="diff-del"><Clip text={show(change.before)} /></span>}</td>
      <td>{change.kind === "removed" ? "—" : <span className="diff-add"><Clip text={show(change.after)} /></span>}</td>
    </tr>
  );
}

function Panel({ title, aside, children, testId }: { title: string; aside?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <section className="panel" data-testid={testId}>
      <div className="panel-head"><h2>{title}</h2><span className="grow" />{aside}</div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export default async function HistoryPage({
  params, searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ tab?: string; kind?: string; id?: string; show?: string; artifacts?: string }>;
}) {
  const { projectId } = await params;
  const { tab: asked, kind, id, show: only, artifacts: artifactsAll } = await searchParams;
  // a version's link (?kind=&id=) opens Versions; else the tab asked for, else the audit trail
  const tab: Tab = TABS.find((t) => t === asked) ?? (kind && id ? "versions" : "audit");
  const [audit, stale, artifacts, history, signatures] = await Promise.all([
    getAudit(projectId),
    getStale(projectId),
    tab === "versions" ? getArtifacts(projectId) : Promise.resolve(null),
    tab === "versions" && kind && id ? getHistory(projectId, kind, id) : Promise.resolve(null),
    tab === "signatures" ? getSignatures(projectId) : Promise.resolve(null),
  ]);
  const base = `/projects/${encodeURIComponent(projectId)}/history`;
  const here = (q: Record<string, string | undefined>) => {
    const p = new URLSearchParams({ tab: "versions" });
    for (const [k, v] of Object.entries({ kind, id, show: only, artifacts: artifactsAll, ...q })) if (v) p.set(k, v);
    return `${base}?${p.toString()}`;
  };
  // the artifacts by kind, with how many of each; one kind at a time when asked (`?show=evidence`)
  const kinds = new Map<string, number>();
  for (const a of artifacts?.data ?? []) kinds.set(a.kind, (kinds.get(a.kind) ?? 0) + 1);
  const matching = (artifacts?.data ?? []).filter((a) => !only || a.kind === only);
  const listed = artifactsAll === "all" ? matching : matching.slice(0, ARTIFACTS_SHOWN);
  const staleRows = stale.data ?? [];
  const verifies = audit.data?.chain_verifies;

  return (
    <main>
      <Hero tone="history" eyebrow="Project record" title="History"
            lede={<>Every output is a version that names the inputs it was made from. An edit makes a new version; what was made
              from the old one is marked <strong>out of date</strong> with its reason, never deleted or silently redone.</>}
            actions={verifies === undefined ? null : (
              <span className={`chip ${verifies ? "low" : "high"}`} data-testid="history-chain">
                {verifies ? "hash chain verifies" : "hash chain BROKEN"}</span>
            )} />

      <nav className="tabs page-tabs" aria-label="History" data-testid="history-tabs">
        {TABS.map((t) => (
          <Link key={t} href={`${base}?tab=${t}`} prefetch={false} scroll={false} aria-current={t === tab ? "page" : undefined}
                data-testid={`history-tab-${t}`}>
            {TAB_LABEL[t]}
            {t === "audit" && audit.data && <span className="tab-count">{audit.data.events.length}</span>}
            {t === "stale" && staleRows.length > 0 && <span className="tab-count">{staleRows.length}</span>}
          </Link>
        ))}
      </nav>

      {tab === "audit" && (
        audit.problem ? <ApiProblem problem={audit.problem} />
          : <AuditTable events={audit.data?.events ?? []} projectId={projectId} />
      )}

      {tab === "signatures" && (
        signatures?.problem ? <ApiProblem problem={signatures.problem} /> : (
          <>
            <p className="muted fs-13 mt-0">Every signature given on this project&apos;s records, decisions on its campaigns included,
              read from the company&apos;s hash-chained audit trail. Each binds its record&apos;s hash.</p>
            <SignatureTable signatures={signatures?.data?.signatures ?? []} />
          </>
        )
      )}

      {tab === "versions" && (
        <>
          {artifacts?.problem && <ApiProblem problem={artifacts.problem} />}
          <Panel title="Artifacts" aside={<span className="muted fs-13">{matching.length} of {artifacts?.data?.length ?? 0}</span>}
                 testId="history-artifacts">
            {kinds.size > 1 && (
              <nav className="filter-links" aria-label="Show artifacts of one kind" data-testid="history-kinds">
                <a href={here({ show: undefined })} aria-current={!only}>All<span className="count">{artifacts?.data?.length ?? 0}</span></a>
                {[...kinds].map(([k, n]) => (
                  <a key={k} href={here({ show: k })} aria-current={only === k}>{k}<span className="count">{n}</span></a>
                ))}
              </nav>
            )}
            {listed.length > 0 ? (
              <>
                <div className="tbl-scroll">
                  <table>
                    <thead><tr><th scope="col">Artifact</th><th scope="col" className="num">Version</th><th scope="col">Status</th>
                      <th scope="col">Last change</th><th scope="col">By</th></tr></thead>
                    <tbody>
                      {listed.map((a) => (
                        <tr key={`${a.kind}/${a.id}`}>
                          <td><Link href={here({ kind: a.kind, id: a.id })} prefetch={false}><code>{a.kind}/{a.id}</code></Link></td>
                          <td className="num">v{a.version}</td>
                          <td><StatusIndicator status={a.status} /></td>
                          <td><Clip text={a.reason} /></td>
                          <td className="muted">{a.created_by}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {matching.length > listed.length && (
                  <p className="muted m-12-0-0" data-testid="artifacts-more">
                    {listed.length} of {matching.length}. <a href={here({ artifacts: "all" })}>Show all {matching.length}</a>
                  </p>
                )}
              </>
            ) : (
              <p className="muted m-0">Nothing recorded yet. Start with the technical proposal.</p>
            )}
          </Panel>
          {history?.data && (
            <Panel title={`${kind}/${id}: every version`} testId="history-versions">
              {history.data.map((row) => (
                <div key={row.version} className="mb-16">
                  <div className="row">
                    <strong>v{row.version}</strong>
                    <StatusIndicator status={row.status} />
                    <span className="muted">{new Date(row.created_at).toLocaleString()} · {row.created_by}</span>
                    <span className="flex-1 minw-0"><Clip text={row.reason} /></span>
                  </div>
                  {row.approvals.map((a) => (
                    <p key={a.at} className="muted m-4-0">
                      {a.meaning} by {a.printed_name || a.by} · {new Date(a.at).toLocaleString()}
                      {a.signature_id ? " · signed (Part 11)" : ""}
                    </p>
                  ))}
                  {row.changes.length > 0 && (
                    <div className="tbl-scroll">
                      <table>
                        <thead><tr><th scope="col">Field</th><th scope="col">Before</th><th scope="col">After</th></tr></thead>
                        <tbody>{row.changes.slice(0, 200).map((c) => <ChangeRow key={c.path} change={c} />)}</tbody>
                      </table>
                    </div>
                  )}
                </div>
              ))}
            </Panel>
          )}
        </>
      )}

      {tab === "stale" && (
        stale.problem ? <ApiProblem problem={stale.problem} /> : (
          <Panel title="Out of date" aside={<span className="muted fs-13">made from inputs that have since changed</span>}
                 testId="history-stale">
            {staleRows.length === 0 ? <p className="muted m-0" data-testid="stale-none">Nothing is out of date: every version is
              made from the latest of its inputs.</p> : (
              <div className="tbl-scroll">
                <table>
                  <thead><tr><th scope="col">Artifact</th><th scope="col">Why</th></tr></thead>
                  <tbody>
                    {staleRows.map((s) => (
                      <tr key={`${s.ref.kind}/${s.ref.id}`}>
                        <td><Link href={here({ kind: s.ref.kind, id: s.ref.id })} prefetch={false}><code>{s.ref.kind}/{s.ref.id}@v{s.ref.version}</code></Link></td>
                        <td>{s.reasons.join("; ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        )
      )}
    </main>
  );
}
