"use client";

import { useCallback, useEffect, useState } from "react";

import { Card } from "@/components/ui";
import { WEB_TOKEN, apiGet, apiSend, apiUpload } from "@/lib/writes";

type Triage = { sheet: string; category: string; evidence_cell: string; evidence_quote: string; by: string; note: string };
type IssueRow = { code: string; location: string; message: string };
type KeptRow = { row: number; values: Record<string, unknown>; cells: Record<string, string> };
type ClientFile = {
  id: string; file: string; sha256: string; kind: string; template: boolean; triage: Triage[]; datasets: string[];
  evidence: string[]; dissolution: KeptRow[]; products: KeptRow[]; urine_feces: KeptRow[]; issues: IssueRow[];
  brief_mismatches: string[]; other_sheets: string[]; mappings: { recipe: { recipe_id: string }; datasets: string[] }[];
};
type Reconciled = { req_id: string; label: string; criticality: string; applies: string; status: string;
                    delivered: string[]; detail: string; cross_check: boolean; literature_accepted: string[] };
type View = {
  template: string;
  files: ClientFile[];
  reconciliation: { rows: Reconciled[]; unpromised: string[]; blocking: string[] };
  register: { status: string; approvals: { printed_name: string; at: string }[] } | null;
  agents: { enabled: boolean };
  running: boolean;
};

const CATEGORIES = ["PK_INDIVIDUAL", "PK_SUMMARY", "PK_PARAMETERS", "DISSOLUTION", "PRODUCT_INFO", "STUDIES", "DEMOGRAPHICS",
                    "BIOANALYTICAL", "PHYSCHEM_INVITRO", "URINE_FECES", "OTHER"];
const STATUS_CHIP: Record<string, string> = { DELIVERED: "low", PARTIAL: "medium", MISSING: "high", NOT_AVAILABLE: "neutral",
                                              WAIVED: "neutral" };

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function recipeSkeleton(sheet: string) {
  return JSON.stringify({ tables: [{
    record_type: "concentration_time", sheet, header_rows: 1, first_data_row: 2,
    columns: [{ column: "A", role: "subject_id" }, { column: "B", role: "time" }, { column: "C", role: "value" }],
    time_unit: "h", value_unit: "ng/ml", statistic: "individual",
    constants: [{ key: "study_id", value: "" }, { key: "analyte", value: "parent" }, { key: "matrix", value: "plasma" },
                { key: "dose", value: "" }, { key: "dose_unit", value: "mg" }, { key: "route", value: "oral" },
                { key: "formulation", value: "ir_tablet" }, { key: "food_state", value: "fasted" }],
    evidence: [{ cell: `${sheet}!C1`, quote: "", supports: "value unit" }],
  }], questions_for_reviewer: [] }, null, 2);
}

function SheetRow({ t, onClassify }: { t: Triage; onClassify: (category: string, reason: string) => Promise<string | null> }) {
  const [category, setCategory] = useState(t.category);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <tr data-testid={`sheet-${t.sheet}`}>
      <td><code>{t.sheet}</code></td>
      <td><span className={`chip ${t.category === "OTHER" ? "medium" : "low"}`}>{t.category.toLowerCase().replace(/_/g, " ")}</span></td>
      <td className="muted">{t.evidence_quote ? <>“{t.evidence_quote}” <code>{t.evidence_cell}</code></> : t.note}</td>
      <td className="muted">{t.by === "code" ? "by its headers" : t.by}</td>
      <td>
        <div className="row" style={{ gap: 4 }}>
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label={`category of ${t.sheet}`}>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c.toLowerCase().replace(/_/g, " ")}</option>)}
          </select>
          <input placeholder="why" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 140 }} />
          <button className="btn" disabled={!reason.trim() || category === t.category}
                  onClick={async () => setError(await onClassify(category, reason))}>Set</button>
        </div>
        {error && <div className="banner err">{error}</div>}
      </td>
    </tr>
  );
}

function Mapper({ projectId, file, onDone }: { projectId: string; file: ClientFile; onDone: () => Promise<void> }) {
  const sheets = file.triage.map((t) => t.sheet);
  const [sheet, setSheet] = useState(sheets[0] ?? "");
  const [recipe, setRecipe] = useState(recipeSkeleton(sheets[0] ?? "Sheet1"));
  const [study, setStudy] = useState('{"n": 12, "design": "SD", "population_type": "healthy"}');
  const [result, setResult] = useState<{ ready: boolean; issues: IssueRow[]; questions: string[]; concentrations: number;
                                          studies: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function run(confirm: boolean) {
    let proposal: unknown;
    let facts: unknown;
    try { proposal = JSON.parse(recipe); facts = JSON.parse(study); } catch { setError("The recipe or the study facts are not valid JSON."); return; }
    const env = await apiSend<NonNullable<typeof result>>(`/api/v1/projects/${projectId}/client-data/${file.id}:map`, "POST",
                                                         { proposal, study: facts, confirm });
    if (env.errors?.length || !env.data) { setError(env.errors?.[0]?.message ?? "not applied"); return; }
    setError(null);
    setResult(env.data);
    if (confirm) await onDone();
  }
  return (
    <div className="mapper" data-testid={`mapper-${file.id}`}>
      <p className="muted" style={{ margin: "4px 0" }}>
        Describe where the data are (columns, units, constants) and cite the cells that state each unit, dose and study id.
        Code applies it exactly and shows every problem; nothing is kept until you confirm a recipe with none.
      </p>
      <div className="row" style={{ gap: 6 }}>
        <select value={sheet} onChange={(e) => { setSheet(e.target.value); setRecipe(recipeSkeleton(e.target.value)); }}>
          {sheets.map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>
      <textarea value={recipe} onChange={(e) => setRecipe(e.target.value)} rows={14} style={{ width: "100%", fontFamily: "var(--font-mono), monospace" }}
                aria-label="mapping recipe" />
      <label className="muted" style={{ fontSize: 12 }}>Study facts the sheet does not state (n, design, population …)</label>
      <textarea value={study} onChange={(e) => setStudy(e.target.value)} rows={2} style={{ width: "100%", fontFamily: "var(--font-mono), monospace" }}
                aria-label="study facts" />
      <div className="row" style={{ gap: 6 }}>
        <button className="btn" onClick={() => run(false)}>Preview</button>
        <button className="btn primary" disabled={!result?.ready} onClick={() => run(true)}>Confirm and read</button>
      </div>
      {error && <div className="banner err">{error}</div>}
      {result && (
        <div className="muted" style={{ fontSize: 13 }}>
          {result.concentrations} values for {result.studies.join(", ") || "no study"}{result.ready ? " · ready to confirm" : ""}
          {result.issues.length > 0 && <ul className="flags">{result.issues.map((i, k) => <li key={k}><code>{i.location}</code> {i.message}</li>)}</ul>}
          {result.questions.length > 0 && <ul className="flags">{result.questions.map((q) => <li key={q}>{q}</li>)}</ul>}
        </div>
      )}
    </div>
  );
}

function FileCard({ projectId, file, agents, running, act, reload }: {
  projectId: string; file: ClientFile; agents: boolean; running: boolean;
  act: (fn: () => Promise<{ errors: { message: string }[] }>) => Promise<string | null>; reload: () => Promise<void>;
}) {
  const [mapping, setMapping] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const spreadsheet = file.triage.length > 0;
  const undecided = file.triage.some((t) => t.category === "OTHER" && t.by === "code");
  return (
    <div className="evidence" data-testid={`client-file-${file.file}`}>
      <div className="spread">
        <div className="row">
          <strong>{file.file}</strong>
          <span className={`chip ${file.template ? "low" : "neutral"}`}>{file.template ? "client-data template" : file.kind}</span>
          {file.datasets.length > 0 && <span className="chip neutral">{plural(file.datasets.length, "dataset")}</span>}
          {file.evidence.length > 0 && <span className="chip neutral">{plural(file.evidence.length, "value")}</span>}
          {file.dissolution.length > 0 && <span className="chip neutral">{plural(file.dissolution.length, "dissolution row")}</span>}
        </div>
        <code className="muted">{file.sha256.slice(0, 12)}</code>
      </div>
      {!spreadsheet && <p className="muted" style={{ margin: "4px 0" }}>Stored as a citable document (the literature agents and you can quote it).</p>}
      {spreadsheet && (
        <table style={{ marginTop: 6 }}>
          <thead><tr><th>Sheet</th><th>Holds</th><th>Because</th><th>Decided</th><th>Change</th></tr></thead>
          <tbody>
            {file.triage.map((t) => (
              <SheetRow key={t.sheet} t={t} onClassify={(category, reason) =>
                act(() => apiSend(`/api/v1/projects/${projectId}/client-data/${file.id}/sheets/${encodeURIComponent(t.sheet)}:classify`,
                                  "POST", { category, reason }))} />
            ))}
          </tbody>
        </table>
      )}
      {file.issues.length > 0 && (
        <ul className="flags" aria-label="Problems found">{file.issues.map((i, k) => <li key={k}><code>{i.location}</code> {i.message}</li>)}</ul>
      )}
      {file.brief_mismatches.length > 0 && (
        <div className="banner warn" style={{ marginTop: 6 }}>
          Not in the brief: {file.brief_mismatches.join(" · ")}. Check with the client or update the brief.
        </div>
      )}
      {spreadsheet && !file.template && (
        <div className="row" style={{ marginTop: 6 }}>
          {undecided && (
            <button className="btn" disabled={!agents || running}
                    onClick={async () => setNotice(await act(() => apiSend(`/api/v1/projects/${projectId}/client-data/${file.id}:triage`, "POST"))
                      ?? "Agent A4 is sorting the undecided sheets.")}>Sort undecided sheets (agent)</button>
          )}
          <button className="btn" onClick={() => setMapping(!mapping)}>{mapping ? "Close the mapping" : "Map a sheet"}</button>
        </div>
      )}
      {notice && <div className="banner ok">{notice}</div>}
      {mapping && <Mapper projectId={projectId} file={file} onDone={async () => { setMapping(false); await reload(); }} />}
    </div>
  );
}

function ReconRow({ r, onDecide }: { r: Reconciled; onDecide: (body: Record<string, unknown>) => Promise<string | null> }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <tr data-testid={`recon-${r.req_id}`}>
      <td>{r.label}<div className="muted" style={{ fontSize: 12 }}>{r.criticality.toLowerCase()}{r.applies === "undetermined" ? " · if applicable" : ""}</div></td>
      <td><span className={`chip ${STATUS_CHIP[r.status] ?? "neutral"}`}>{r.status.toLowerCase().replace("_", " ")}</span>
        {r.cross_check && <span className="chip neutral">cross-check{r.literature_accepted.length ? " ✓" : ""}</span>}</td>
      <td className="muted" style={{ fontSize: 13 }}>{r.detail || r.delivered.join(", ") || "—"}</td>
      <td>
        {(r.status === "MISSING" || r.status === "PARTIAL") && (
          <div className="row" style={{ gap: 4 }}>
            <input placeholder="reason" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 150 }} />
            <button className="btn" disabled={!reason.trim()} onClick={async () => setError(await onDecide({ status: "NOT_AVAILABLE", reason }))}>Skip</button>
            {!r.cross_check && <button className="btn" disabled={!reason.trim()} onClick={async () => setError(await onDecide({ cross_check: true, reason }))}>Cross-check in literature</button>}
          </div>
        )}
        {error && <div className="banner err">{error}</div>}
      </td>
    </tr>
  );
}

/** P3 client data (plan §10): the files, how they were read, and the reconciliation with the data plan. */
export function ClientData({ projectId }: { projectId: string }) {
  const [view, setView] = useState<View | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    const v = await apiGet<View>(`/api/v1/projects/${projectId}/client-data`);
    if (v.data) { setView(v.data); setProblem(null); } else setProblem(v.errors?.[0]?.message ?? "not readable");
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);

  if (problem) return <div className="banner err">{problem}</div>;
  if (!view) return <p className="muted">Loading…</p>;

  const act = async (fn: () => Promise<{ errors: { message: string }[] }>) => {
    const env = await fn();
    if (env.errors?.length) return env.errors[0].message;
    await load();
    return null;
  };
  async function upload(files: FileList | null) {
    if (!files?.length) return;
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    setMessage(await act(() => apiUpload(`/api/v1/projects/${projectId}/client-data`, form)) ?? `${files.length} file(s) read.`);
  }
  async function downloadTemplate() {
    const res = await fetch("/api/v1/client-data/template.xlsx", { headers: { Authorization: `Bearer ${WEB_TOKEN}` } });
    if (!res.ok) { setMessage(`The template could not be downloaded (HTTP ${res.status}).`); return; }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `${view?.template ?? "ModelerOne_ClientData"}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const recon = view.reconciliation;
  return (
    <>
      <Card title="Send files">
        <div className="row">
          <button className="btn" onClick={downloadTemplate} data-testid="download-template">Download the client-data template</button>
          <label className="btn primary">
            Upload client files
            <input type="file" multiple hidden data-testid="client-upload" accept=".xlsx,.xlsm,.csv,.pdf,.docx,.md,.txt"
                   onChange={(e) => void upload(e.target.files)} />
          </label>
        </div>
        <p className="muted" style={{ margin: "6px 0 0", fontSize: 13 }}>
          The template ({view.template}) is read with no AI. Other workbooks, PDFs, Word files, CSV and Markdown are accepted too.
        </p>
        {message && <div className="banner ok" style={{ marginTop: 8 }}>{message}</div>}
      </Card>
      <Card title={`Files (${view.files.length})`}>
        {view.files.length === 0 ? <p className="muted" style={{ margin: 0 }}>No client files yet.</p> : view.files.map((f) => (
          <FileCard key={f.id} projectId={projectId} file={f} agents={view.agents.enabled} running={view.running} act={act} reload={load} />
        ))}
      </Card>
      <Card title="Reconciliation with the data plan">
        {recon.rows.length === 0 ? <p className="muted" style={{ margin: 0 }}>The data plan expects nothing from the client.</p> : (
          <table>
            <thead><tr><th>Expected from the client</th><th>Status</th><th>What arrived</th><th>Decision</th></tr></thead>
            <tbody>
              {recon.rows.map((r) => (
                <ReconRow key={r.req_id} r={r} onDecide={(body) =>
                  act(() => apiSend(`/api/v1/projects/${projectId}/requirements/${encodeURIComponent(r.req_id)}`, "PUT", body))} />
              ))}
            </tbody>
          </table>
        )}
        {recon.unpromised.length > 0 && (
          <>
            <h3 style={{ fontSize: 14, marginBottom: 4 }}>Delivered, not promised</h3>
            <ul className="flags">{recon.unpromised.map((u) => <li key={u}>{u}</li>)}</ul>
          </>
        )}
        <div className="row" style={{ marginTop: 10 }}>
          <input placeholder="approval note" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1 }} />
          <button className="btn primary" data-testid="approve-client-data" disabled={recon.blocking.length > 0}
                  onClick={async () => setMessage(await act(() => apiSend(`/api/v1/projects/${projectId}/client-data:approve`, "POST", { note }))
                    ?? "Client data approved (P3).")}>
            Approve the client data
          </button>
        </div>
        {recon.blocking.length > 0 && <p className="muted" style={{ fontSize: 13 }}>Still missing: {recon.blocking.join(", ")}.</p>}
        {view.register && <p className="muted" style={{ fontSize: 13 }}>Register {view.register.status.toLowerCase()}
          {view.register.approvals[0] ? ` by ${view.register.approvals[0].printed_name}` : ""}.</p>}
      </Card>
    </>
  );
}
