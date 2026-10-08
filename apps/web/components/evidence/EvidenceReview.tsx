"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { DocumentViewer } from "@/components/brief/DocumentViewer";
import { Card } from "@/components/ui";
import type { Narrow, Schema } from "@/lib/api";
import type { DocumentView } from "@/lib/brief";
import { apiGet, apiSend, apiUpload } from "@/lib/writes";

type Evidence = {
  id: string;
  req_id: string | null;
  target: string;
  value: number | string | null;
  unit: string | null;
  value_pksim: number | null;
  unit_pksim: string | null;
  conversion: string;
  source_type: string;
  source: { doc_sha256: string | null; page: number | null; locator: string; title: string; authors: string;
            year: number | null; doi: string | null; pmid: string | null; url: string | null };
  quote: string;
  extraction: string;
  conditions: Record<string, string>;
  confidence: "A" | "B" | "C" | "D";
  flags: string[];
  purpose: string;
  provider: string;
  state: "PROPOSED" | "ACCEPTED" | "REJECTED";
  proposed_by: string;
  decided_by: string | null;
  decision_reason: string;
  note: string;
};

type Coverage = Schema<"CoverageRow">;

type AccessRequest = { id: string; title: string; authors: string; doi: string | null; needed_for: string; status: string };

// GET /projects/{id}/evidence (EvidencePage); the stored evidence items and paper requests are typed above
type EvidenceViewData = Narrow<Schema<"EvidencePage">, { evidence: Evidence[]; access_requests: AccessRequest[] }>;

const STATUS_CHIP: Record<string, string> = {
  ACCEPTED: "low", PROPOSED: "medium", CONFLICTING: "high", NOT_FOUND: "high", NOT_AVAILABLE: "neutral", WAIVED: "neutral",
};
const GRADE_CHIP: Record<string, string> = { A: "low", B: "brand", C: "medium", D: "high" };
const SOURCE_TYPES = ["REGULATORY_REVIEW", "PUBLICATION", "CLIENT_REPORT", "DATABASE", "OSP_LIBRARY", "PREDICTED", "ASSUMPTION"];

function EvidenceCard({ e, onOpen, onDecide }: {
  e: Evidence;
  onOpen: (e: Evidence) => void;
  onDecide: (e: Evidence, state: "ACCEPTED" | "REJECTED" | "PROPOSED", reason: string, valuePksim?: number) => Promise<string | null>;
}) {
  const [reason, setReason] = useState("");
  const [pksim, setPksim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const needsValue = e.value_pksim === null && typeof e.value === "number";
  const src = e.source;
  return (
    <div className={`evidence ${e.state.toLowerCase()}`} data-testid={`evidence-${e.id}`}>
      <div className="spread">
        <div className="row">
          <strong>{String(e.value)} {e.unit ?? ""}</strong>
          {e.value_pksim !== null && <span className="muted">→ {e.value_pksim.toPrecision(4)} {e.unit_pksim ?? ""} in PK-Sim</span>}
          <span className={`chip ${GRADE_CHIP[e.confidence]}`} title="confidence grade (plan §8.4)">grade {e.confidence}</span>
          <span className="chip neutral">{e.source_type.toLowerCase().replace(/_/g, " ")}</span>
          <span className={`chip ${e.state === "ACCEPTED" ? "low" : e.state === "REJECTED" ? "high" : "medium"}`}>{e.state.toLowerCase()}</span>
        </div>
        <code className="muted">{e.target}</code>
      </div>
      <p className="muted" style={{ margin: "4px 0", fontSize: 13 }}>
        {src.title || "source"}{src.authors ? ` · ${src.authors}` : ""}{src.year ? ` (${src.year})` : ""}
        {src.locator ? ` · ${src.locator}` : ""}{src.doi ? ` · doi ${src.doi}` : ""}{src.pmid ? ` · PMID ${src.pmid}` : ""}
        {src.doc_sha256 && <> · <button className="cite" onClick={() => onOpen(e)}>p.{src.page}</button></>}
      </p>
      {e.quote && <blockquote className="quote">“{e.quote}”</blockquote>}
      {Object.keys(e.conditions).length > 0 && (
        <p style={{ margin: "4px 0", fontSize: 13 }}>{Object.entries(e.conditions).map(([k, v]) => `${k}: ${v}`).join(" · ")}</p>
      )}
      {e.conversion && <p className="muted" style={{ margin: "2px 0", fontSize: 12 }}>conversion: {e.conversion}</p>}
      {e.flags.length > 0 && <ul className="flags">{e.flags.map((f) => <li key={f}>{f}</li>)}</ul>}
      {e.decision_reason && <p className="muted" style={{ margin: "2px 0", fontSize: 12 }}>{e.state.toLowerCase()} by {e.decided_by}: {e.decision_reason}</p>}
      <div className="row" style={{ marginTop: 6 }}>
        <input style={{ flex: 1, minWidth: 180 }} placeholder="reason (required)" value={reason} onChange={(ev) => setReason(ev.target.value)} />
        {needsValue && <input style={{ width: 150 }} placeholder="value in PK-Sim unit" value={pksim} onChange={(ev) => setPksim(ev.target.value)} />}
        <button className="btn" disabled={!reason.trim() || e.state === "ACCEPTED"} onClick={async () => {
          setError(await onDecide(e, "ACCEPTED", reason, pksim ? Number(pksim) : undefined));
        }}>Accept</button>
        <button className="btn" disabled={!reason.trim() || e.state === "REJECTED"} onClick={async () => {
          setError(await onDecide(e, "REJECTED", reason));
        }}>Reject</button>
      </div>
      {error && <div className="banner err" style={{ marginTop: 6 }}>{error}</div>}
    </div>
  );
}

function ManualForm({ row, onAdd }: { row: Coverage; onAdd: (body: Record<string, unknown>) => Promise<string | null> }) {
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  const [sourceType, setSourceType] = useState("PUBLICATION");
  const [doi, setDoi] = useState("");
  const [title, setTitle] = useState("");
  const [conditions, setConditions] = useState("");
  const [error, setError] = useState<string | null>(null);
  const target = row.target.includes("{") ? "" : row.target;
  const [concrete, setConcrete] = useState(target);
  return (
    <div className="editor">
      <div className="row">
        <input placeholder="target (CPF id)" value={concrete} onChange={(e) => setConcrete(e.target.value)} style={{ width: 210 }} />
        <input placeholder="value" value={value} onChange={(e) => setValue(e.target.value)} style={{ width: 110 }} />
        <input placeholder="unit as stated" value={unit} onChange={(e) => setUnit(e.target.value)} style={{ width: 110 }} />
        <select value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
          {SOURCE_TYPES.map((s) => <option key={s} value={s}>{s.toLowerCase().replace(/_/g, " ")}</option>)}
        </select>
      </div>
      <div className="row" style={{ marginTop: 6 }}>
        <input placeholder="DOI / PMID / URL" value={doi} onChange={(e) => setDoi(e.target.value)} style={{ width: 210 }} />
        <input placeholder="title" value={title} onChange={(e) => setTitle(e.target.value)} style={{ flex: 1 }} />
      </div>
      <input placeholder="conditions: species=human; method=equilibrium dialysis" value={conditions}
             onChange={(e) => setConditions(e.target.value)} style={{ width: "100%", marginTop: 6 }} />
      {error && <div className="banner err" style={{ marginTop: 6 }}>{error}</div>}
      <button className="btn primary" style={{ marginTop: 6 }} disabled={!value || !concrete} onClick={async () => {
        const parsed = Object.fromEntries(conditions.split(";").map((p) => p.split("=").map((x) => x.trim())).filter((p) => p.length === 2 && p[0]));
        const numeric = Number(value);
        const id = doi.trim();
        setError(await onAdd({
          req_id: row.req_id, target: concrete, value: Number.isFinite(numeric) ? numeric : value, unit: unit || null,
          source_type: sourceType, title, conditions: parsed,
          ...(id.startsWith("10.") ? { doi: id } : /^\d+$/.test(id) ? { pmid: id } : id ? { url: id } : {}),
        }));
      }}>Add value</button>
    </div>
  );
}

/** Review layer L2a (plan §5.2 P2): literature evidence per data-plan item, side by side, decided with reasons. */
export function EvidenceReview({ projectId }: { projectId: string }) {
  const [view, setView] = useState<EvidenceViewData | null>(null);
  const [docs, setDocs] = useState<DocumentView[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ sha256: string; page: number; quote: string | null } | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [v, d] = await Promise.all([
      apiGet<EvidenceViewData>(`/api/v1/projects/${projectId}/evidence`),
      apiGet<{ documents: DocumentView[] }>(`/api/v1/projects/${projectId}/documents`),
    ]);
    if (v.data) { setView(v.data); setProblem(null); } else setProblem(v.errors?.[0]?.message ?? "The evidence could not be read.");
    if (d.data) setDocs(d.data.documents);
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!view?.running) return;
    const t = setInterval(() => { void load(); }, 4000);
    return () => clearInterval(t);
  }, [view?.running, load]);

  const byId = useMemo(() => Object.fromEntries((view?.evidence ?? []).map((e) => [e.id, e])), [view]);
  const unlinked = useMemo(() => (view?.evidence ?? []).filter((e) =>
    !view?.coverage.some((c) => c.accepted.includes(e.id) || c.proposed.includes(e.id)) && e.state !== "REJECTED"), [view]);

  if (problem) return <div className="banner err">{problem}</div>;
  if (!view) return <p className="muted">Loading the evidence…</p>;

  async function act<T>(fn: () => Promise<{ data: T | null; errors: { message: string }[] }>): Promise<string | null> {
    setBusy(true);
    const env = await fn();
    setBusy(false);
    if (env.errors?.length) return env.errors[0].message;
    await load();
    return null;
  }
  const decide = (e: Evidence, state: string, reason: string, value?: number) =>
    act(() => apiSend(`/api/v1/projects/${projectId}/evidence/${e.id}:decide`, "POST",
      { state, reason, ...(value !== undefined ? { value_pksim: value, unit_pksim: null } : {}) }));
  const add = (body: Record<string, unknown>) => act(() => apiSend(`/api/v1/projects/${projectId}/evidence`, "POST", body));
  const open = (e: Evidence) => e.source.doc_sha256 && setFocus({ sha256: e.source.doc_sha256, page: e.source.page ?? 1, quote: e.quote });
  const notAvailable = async (row: Coverage) => {
    const reason = window.prompt(`Why is "${row.label}" not available? (this changes the data plan, which is re-approved)`);
    if (!reason) return;
    setNotice(await act(() => apiSend(`/api/v1/projects/${projectId}/requirements/${encodeURIComponent(row.req_id)}`, "PUT",
      { status: "NOT_AVAILABLE", reason })));
  };

  const approved = view.register?.status === "APPROVED";
  return (
    <>
      <Card>
        <div className="spread">
          <div>
            <h2 style={{ margin: 0 }}>Literature evidence</h2>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              data plan v{view.data_plan.version} ({view.data_plan.status.toLowerCase()}) · {view.evidence.length} proposals ·
              {" "}{view.coverage.filter((c) => c.status === "ACCEPTED").length} of {view.coverage.length} items with accepted evidence ·
              {" "}{view.blocking.length} required items open
            </p>
          </div>
          <div className="row">
            <span className={`chip ${view.agents.enabled ? "brand" : "neutral"}`} title={view.agents.problem ?? ""}>
              {view.agents.enabled ? `agent: ${view.agents.provider} · ${view.agents.model}` : "agents off"}
            </span>
            <button className="btn" disabled={busy || view.running || !view.agents.enabled}
                    onClick={async () => setNotice(await act(() => apiSend(`/api/v1/projects/${projectId}/evidence:research`, "POST", {}))
                      ?? "The literature agent is searching; proposals appear as it records them.")}>
              {view.running ? "Searching…" : "Run literature search"}
            </button>
            <button className="btn primary" disabled={busy || view.blocking.length > 0 || approved}
                    onClick={async () => setNotice(await act(() => apiSend(`/api/v1/projects/${projectId}/evidence:approve`, "POST", { note: "" })) ?? "Literature evidence approved.")}>
              {approved ? "Approved" : `Approve literature evidence${view.blocking.length ? ` (${view.blocking.length} open)` : ""}`}
            </button>
          </div>
        </div>
        {notice && <div className="banner ok" style={{ marginTop: 10 }}>{notice}</div>}
        {view.register?.stale_reasons?.length ? <div className="banner warn" style={{ marginTop: 10 }}>Stale: {view.register.stale_reasons.join("; ")}</div> : null}
        {view.runs[0] && <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>
          Last run {view.runs[0].run_id}: {view.runs[0].status.toLowerCase()} · {String(view.runs[0].summary.proposed ?? 0)} proposed,
          {" "}{String(view.runs[0].summary.rejected ?? 0)} rejected by the citation check</p>}
      </Card>

      <div className="brief-layout">
        <div>
          {view.coverage.map((row) => (
            <Card key={row.req_id}>
              <div className="spread">
                <div>
                  <strong>{row.label}</strong> <code className="muted">{row.target}</code>
                  <div className="row" style={{ gap: 6, marginTop: 4 }}>
                    <span className={`chip ${STATUS_CHIP[row.status] ?? "neutral"}`} data-testid={`coverage-${row.req_id}`}>{row.status.toLowerCase().replace("_", " ")}</span>
                    <span className="chip neutral">{row.criticality.toLowerCase()}</span>
                    {row.provider === "CLIENT" && <span className="chip neutral">client item · cross-check</span>}
                  </div>
                </div>
                <div className="row">
                  <button className="btn" onClick={() => setAdding(adding === row.req_id ? null : row.req_id)}>Add a value</button>
                  {row.status !== "NOT_AVAILABLE" && row.status !== "ACCEPTED" &&
                    <button className="btn" onClick={() => notAvailable(row)}>Not available</button>}
                </div>
              </div>
              {adding === row.req_id && <ManualForm row={row} onAdd={async (b) => { const r = await add(b); if (!r) setAdding(null); return r; }} />}
              {[...row.accepted, ...row.proposed].map((id) => byId[id] && (
                <EvidenceCard key={id} e={byId[id]} onOpen={open} onDecide={decide} />
              ))}
            </Card>
          ))}
          {unlinked.length > 0 && (
            <Card title="Other proposals">
              {unlinked.map((e) => <EvidenceCard key={e.id} e={e} onOpen={open} onDecide={decide} />)}
            </Card>
          )}
          {view.access_requests.length > 0 && (
            <Card title="Papers the agent could not read (access requests)">
              <table>
                <tbody>
                  {view.access_requests.map((r) => (
                    <tr key={r.id}>
                      <td>{r.title}<div className="muted" style={{ fontSize: 12 }}>{r.authors}{r.doi ? ` · doi ${r.doi}` : ""} · for {r.needed_for}</div></td>
                      <td><span className={`chip ${r.status === "OPEN" ? "medium" : "low"}`}>{r.status.toLowerCase()}</span></td>
                      <td>
                        {r.status === "OPEN" && (
                          <input type="file" accept=".pdf,.docx,.md,.txt" onChange={async (ev) => {
                            const file = ev.target.files?.[0];
                            if (!file) return;
                            const form = new FormData();
                            form.set("file", file);
                            setNotice(await act(() => apiUpload(`/api/v1/projects/${projectId}/access-requests/${r.id}:fulfil`, form)) ?? "Paper stored; the agent can cite it now.");
                          }} />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </div>
        <div className="brief-side">
          {docs.length > 0 ? <DocumentViewer projectId={projectId} documents={docs} focus={focus} />
            : <Card><p className="muted" style={{ margin: 0 }}>No documents yet.</p></Card>}
        </div>
      </div>
    </>
  );
}
