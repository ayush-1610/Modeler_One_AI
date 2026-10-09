"use client";

import Link from "next/link";
import { type ReactNode, useState } from "react";

import { Card } from "@/components/ui";
import { apiFile, narrow, send, upload as uploadTo, type Envelope, type Schema } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";

import { SheetReader, type Study } from "./SheetReader";
import {
  CATEGORY_LABEL, type ClientFile, DATA_SHEETS, type Profile, type Reconciled, type SheetForm, type Triage, type View, readSheets,
} from "./types";

type Act = <T>(fn: () => Promise<Envelope<T>>) => Promise<string | null>;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const STATUS: Record<string, [string, string]> = {
  DELIVERED: ["low", "delivered"], PARTIAL: ["medium", "partly delivered"], MISSING: ["high", "missing"],
  NOT_AVAILABLE: ["neutral", "not from the client"], WAIVED: ["neutral", "waived"],
};

/** What delivers a data-plan item, in the words of the page (requirement templates, client_data.reconcile). */
function howTo(r: Reconciled): string {
  if (r.kind === "formulation") {
    return `Read the test product's dissolution sheet with the product named “${r.product ?? "as in the brief"}” (role TEST), then propose its release model under Dissolution.`;
  }
  if (r.kind === "dataset") {
    if (r.target === "dissolution") return "Read a TEST and an RLD dissolution sheet measured in the same medium and pH.";
    if (r.target === "BE study") return "Read the BE study sheets (each arm its own study id) and set “The study is for” to external validation.";
    if (r.target === "EXTERNAL") return "Read at least one clinical study and set “The study is for” to external validation.";
    if (r.target === "urine") return "Send urine excretion data (the template's Urine_Feces sheet).";
    if (r.target === "lloq") return "Read a study with its LLOQ filled in.";
    return `Read a ${r.target} study (model building).`;
  }
  if (r.target === "variability") {
    return "Usually the BE study's statistical report (intra-subject CV of AUC and Cmax); upload it as a document, or take it from the literature.";
  }
  return "Upload the client's report and enter the value in the template's Physchem_InVitro sheet, or take it from the literature.";
}

/** Today's state of P3 as five steps, each with what is left. */
function Progress({ view, projectId, sheetsTodo, sheetsDone, onApprove, note, setNote }: {
  view: View; projectId: string; sheetsTodo: number; sheetsDone: number; onApprove: () => void; note: string;
  setNote: (v: string) => void;
}) {
  const recon = view.reconciliation;
  const required = recon.rows.filter((r) => r.criticality === "REQUIRED" && r.applies === "yes");
  const covered = required.filter((r) => !recon.blocking.includes(r.req_id)).length;
  const planOk = view.data_plan.status === "APPROVED";
  const approved = view.register?.status === "APPROVED";
  const steps: [string, string, boolean, ReactNode?][] = [
    ["Data plan", planOk ? "approved" : `version ${view.data_plan.version} not approved`, planOk,
     planOk ? undefined : <>your decisions below change it; <Link href={`/projects/${projectId}/brief`}>approve it on the Brief page</Link></>],
    ["Files", plural(view.files.length, "file"), view.files.length > 0],
    ["Sheets read", sheetsTodo + sheetsDone ? `${sheetsDone} of ${sheetsTodo + sheetsDone} data sheets` : "none to read", sheetsTodo === 0],
    ["Plan items", `${covered} of ${required.length} required items settled`, recon.blocking.length === 0],
    ["Approval", approved ? `approved${view.register?.approvals[0] ? ` by ${view.register.approvals[0].printed_name}` : ""}` : "not yet", approved],
  ];
  return (
    <section className="card p3-progress" aria-label="Client data progress">
      <ol className="steps">
        {steps.map(([name, state, ok, extra], i) => (
          <li key={name} className={ok ? "done" : ""}>
            <span className="step-n">{ok ? "✓" : i + 1}</span>
            <span><strong>{name}</strong><span className="muted"> · {state}</span>{extra && <> · {extra}</>}</span>
          </li>
        ))}
      </ol>
      <div className="row" style={{ marginTop: 12 }}>
        <input placeholder="approval note (optional)" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1, minWidth: 180 }} />
        <button className="btn primary" data-testid="approve-client-data" disabled={recon.blocking.length > 0} onClick={onApprove}
                title={recon.blocking.length ? "Settle the items listed under “What stops approval” first" : undefined}>
          {approved ? "Approve again" : "Approve the client data"}
        </button>
      </div>
      {recon.blocking.length > 0 && (
        <p className="muted" style={{ margin: "6px 0 0", fontSize: 13 }}>
          Approval opens when every required item is delivered, marked “not from the client”, or moved to the literature:{" "}
          <a href="#blocking">{plural(recon.blocking.length, "item")} left</a>.
        </p>
      )}
    </section>
  );
}

/** One data-plan item: what it needs, what arrived, and the decisions a person can take on it. */
type Override = Omit<Schema<"OverrideRequest">, "reason">;
type Category = Schema<"Classification">["category"];

function PlanItem({ r, onDecide, blocking }: { r: Reconciled; onDecide: (body: Schema<"OverrideRequest">) => Promise<string | null>; blocking: boolean }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const optional = r.criticality !== "REQUIRED" || r.applies !== "yes";
  const [chip, word] = optional && r.status === "MISSING" ? ["neutral", "not sent (optional)"]
                                                         : STATUS[r.status] ?? ["neutral", r.status.toLowerCase()];
  const open = r.status === "MISSING" || r.status === "PARTIAL";
  const decide = async (body: Override) => setError(await onDecide({ ...body, reason }));
  return (
    <div className={`plan-item${blocking ? " blocking" : ""}`} data-testid={`recon-${r.req_id}`}>
      <div className="spread" style={{ alignItems: "flex-start" }}>
        <div>
          <strong>{r.label}</strong>
          <div className="muted" style={{ fontSize: 12 }}>{r.req_id} · {r.criticality.toLowerCase()}{r.applies === "undetermined" ? " · if applicable" : ""}</div>
        </div>
        <span className={`chip ${chip}`}>{word}</span>
      </div>
      {r.delivered.length > 0 && <div className="muted" style={{ fontSize: 13 }}>Arrived: {r.delivered.join(", ")}</div>}
      {r.detail && <div className="flags" style={{ paddingLeft: 0 }}>{r.detail}</div>}
      {open && <div style={{ fontSize: 13 }}>How: {howTo(r)}</div>}
      {r.cross_check && open && (
        <div className="muted" style={{ fontSize: 13 }}>
          Literature cross-check is on: this counts once a literature value is accepted on the Literature page
          {r.literature_accepted.length ? " (accepted ✓)" : " (none accepted yet)"}.
        </div>
      )}
      {open && (
        <div className="row" style={{ gap: 6, marginTop: 6 }}>
          <input placeholder="reason (kept in the audit trail)" value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1, minWidth: 200 }}
                 aria-label={`reason for ${r.req_id}`} />
          <button className="btn" disabled={!reason.trim()} onClick={() => void decide({ status: "NOT_AVAILABLE" })}>Not from the client</button>
          <button className="btn" disabled={!reason.trim()} onClick={() => void decide({ provider: "LITERATURE" })}>Get it from the literature instead</button>
        </div>
      )}
      {r.status === "NOT_AVAILABLE" && (
        <div className="row" style={{ gap: 6, marginTop: 6 }}>
          <input placeholder="reason to reopen" value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
          <button className="btn" disabled={!reason.trim()} onClick={() => void decide({ status: "OPEN" })}>Reopen</button>
        </div>
      )}
      {error && <div className="banner err">{error}</div>}
    </div>
  );
}

/** A sheet's line: what it holds, whether it was read, and the button that reads it. */
function SheetLine({ t, read, onRead, onClassify }: {
  t: Triage; read: number | undefined; onRead: () => void; onClassify: (category: Category, reason: string) => Promise<string | null>;
}) {
  const [changing, setChanging] = useState(false);
  const [category, setCategory] = useState(t.category as Category);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const data = DATA_SHEETS.has(t.category);
  return (
    <tr data-testid={`sheet-${t.sheet}`}>
      <td><code>{t.sheet}</code></td>
      <td>
        <span className={`chip ${t.category === "OTHER" ? "medium" : data ? "brand" : "neutral"}`}>{CATEGORY_LABEL[t.category] ?? t.category.toLowerCase()}</span>
        {t.evidence_quote && <div className="muted" style={{ fontSize: 12 }}>“{t.evidence_quote}” {t.evidence_cell.split("!")[1]}</div>}
        {!changing && <button className="linkish" onClick={() => setChanging(true)}>change</button>}
        {changing && (
          <div className="row" style={{ gap: 4, marginTop: 4 }}>
            <select value={category} onChange={(e) => setCategory(e.target.value as Category)} aria-label={`category of ${t.sheet}`}>
              {Object.keys(CATEGORY_LABEL).map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
            </select>
            <input placeholder="why" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 140 }} />
            <button className="btn" disabled={!reason.trim() || category === t.category}
                    onClick={async () => { const e = await onClassify(category, reason); setError(e); if (!e) setChanging(false); }}>Set</button>
          </div>
        )}
        {error && <div className="banner err">{error}</div>}
      </td>
      <td>{read ? <span className="chip low">read ✓{read > 1 ? ` (${read})` : ""}</span>
               : data ? <span className="chip medium">not read yet</span> : <span className="muted" style={{ fontSize: 12 }}>no data to read</span>}</td>
      <td className="num"><button className={`btn${!read && data ? " primary" : ""}`} onClick={onRead}>{read ? "Read again" : "Read this sheet"}</button></td>
    </tr>
  );
}

function FileCard({ projectId, file, agents, running, act, reading, setReading, onSaved, last, remember }: {
  projectId: string; file: ClientFile; agents: boolean; running: boolean; act: Act; reading: string | null;
  setReading: (sheet: string | null) => void; onSaved: (message: string) => Promise<void>;
  last: { form: SheetForm; study: Study } | null; remember: (s: { form: SheetForm; study: Study }) => void;
}) {
  const [notice, setNotice] = useState<string | null>(null);
  const spreadsheet = file.triage.length > 0;
  const read = readSheets(file);
  const undecided = file.triage.some((t) => t.category === "OTHER" && t.by === "code");
  return (
    <div className="file-card" data-testid={`client-file-${file.file}`}>
      <div className="spread">
        <div className="row">
          <strong>{file.file}</strong>
          <span className={`chip ${file.template ? "low" : "neutral"}`}>{file.template ? "client-data template" : file.kind}</span>
          {file.datasets.length > 0 && <span className="chip neutral">{plural(file.datasets.length, "dataset")}</span>}
          {file.evidence.length > 0 && <span className="chip neutral">{plural(file.evidence.length, "value")}</span>}
          {file.dissolution.length > 0 && <span className="chip neutral">{plural(file.dissolution.length, "dissolution row")}</span>}
        </div>
        {spreadsheet && !file.template && undecided && (
          <button className="btn" disabled={!agents || running} title={agents ? undefined : "agents are off"}
                  onClick={async () => setNotice(await act(() => send("post", "/api/v1/projects/{project_id}/client-data/{sid}:triage", { project_id: projectId, sid: file.id }))
                    ?? "Agent A4 is sorting the unsorted sheets.")}>Sort the unsorted sheets (agent)</button>
        )}
      </div>
      {!spreadsheet && <p className="muted" style={{ margin: "4px 0" }}>Kept as a citable document: the literature agents and you can quote it.</p>}
      {file.template && <p className="muted" style={{ margin: "4px 0" }}>The client-data template is read automatically, cell by cell.</p>}
      {spreadsheet && !file.template && (
        <table style={{ marginTop: 6 }}>
          <thead><tr><th>Sheet</th><th>Holds</th><th>Read</th><th /></tr></thead>
          <tbody>
            {file.triage.map((t) => (
              <SheetLine key={t.sheet} t={t} read={read.get(t.sheet)} onRead={() => setReading(reading === t.sheet ? null : t.sheet)}
                         onClassify={(category, reason) => act(() => send(
                           "post", "/api/v1/projects/{project_id}/client-data/{sid}/sheets/{sheet}:classify",
                           { project_id: projectId, sid: file.id, sheet: t.sheet }, { category, reason }))} />
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
      {notice && <div className="banner ok">{notice}</div>}
      {reading && (
        <SheetReader key={reading} projectId={projectId} file={file} sheet={reading} last={last} remember={remember}
                     onClose={() => setReading(null)} onSaved={async (m) => { setReading(null); await onSaved(m); }} />
      )}
    </div>
  );
}

/** Mean % dissolved (points) and the fitted PK-Sim Weibull curve, on a fixed 0–100 % scale. */
function ReleasePlot({ p }: { p: Profile }) {
  const W = 220, H = 90, tMax = Math.max(...p.times_min, 1);
  const x = (t: number) => 6 + (t / tMax) * (W - 12);
  const y = (v: number) => H - 6 - (Math.min(Math.max(v, 0), 110) / 110) * (H - 12);
  const fit = p.fit && p.fit.t50_min && p.fit.shape ? p.fit : null;
  const curve = fit ? Array.from({ length: 41 }, (_, i) => {
    const t = (tMax * i) / 40, s = Math.max(t - fit.lag_min, 0);
    return `${x(t).toFixed(1)},${y(100 * (1 - Math.exp(-Math.LN2 * (s / (fit.t50_min as number)) ** (fit.shape as number)))).toFixed(1)}`;
  }).join(" ") : "";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="release-plot" role="img" aria-label={`release of ${p.label}`}>
      <line x1={6} x2={W - 6} y1={y(100)} y2={y(100)} className="ref" />
      {curve && <polyline points={curve} className="fit" />}
      {p.times_min.map((t, i) => <circle key={t} cx={x(t)} cy={y(p.mean[i])} r={2.5} className="pt" />)}
    </svg>
  );
}

function ProfileRow({ p, onPropose }: { p: Profile; onPropose: (formulation: string) => Promise<string | null> }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fit = p.fit;
  return (
    <tr data-testid={`profile-${p.id}`}>
      <td>{p.label}<div className="muted" style={{ fontSize: 12 }}>n {p.n} · {p.files.join(", ")}</div>
        {p.flags.length > 0 && <ul className="flags">{p.flags.map((f) => <li key={f}>{f}</li>)}</ul>}</td>
      <td><ReleasePlot p={p} /></td>
      <td>
        <span className={`chip ${p.release_model === "Table" ? "high" : "low"}`}>{p.release_model.toLowerCase()}</span>
        {fit && fit.t50_min !== null && (
          <div className="series">t50 {+fit.t50_min.toPrecision(4)} min{fit.se_t50 !== null ? ` ± ${fit.se_t50.toPrecision(2)}` : ""} ·
            shape {fit.shape === null ? "—" : +fit.shape.toPrecision(4)}{fit.se_shape !== null ? ` ± ${fit.se_shape.toPrecision(2)}` : ""} ·
            RMSE {fit.rmse_percent} %</div>
        )}
        {fit && !fit.engine_confirmed && <div className="muted" style={{ fontSize: 12 }}>equation not yet compared with PK-Sim&apos;s own curve</div>}
      </td>
      <td>
        {p.release_model !== "Table" && (
          <div className="row" style={{ gap: 4 }}>
            <input placeholder="formulation name" value={name} onChange={(e) => setName(e.target.value)} style={{ width: 130 }} />
            <button className="btn" disabled={!name.trim()} onClick={async () => setError(await onPropose(name))}>Propose as release model</button>
          </div>
        )}
        {error && <div className="banner err">{error}</div>}
      </td>
    </tr>
  );
}

function Dissolution({ projectId, d, act }: {
  projectId: string; d: View["dissolution"];
  act: Act;
}) {
  const label = (id: string) => d.profiles.find((p) => p.id === id)?.label ?? id;
  return (
    <Card title={`Dissolution (${d.profiles.length} profiles)`}>
      <p className="muted" style={{ margin: "0 0 6px", fontSize: 13 }}>
        Each profile is fitted with PK-Sim&apos;s Weibull release (t50, shape, lag 0). Which profile stands for release in
        the body is a planning decision; proposing one makes its values evidence to accept on the Literature page.
      </p>
      <table>
        <thead><tr><th>Profile</th><th>Mean and fit</th><th>Release model</th><th>Use</th></tr></thead>
        <tbody>
          {d.profiles.map((p) => (
            <ProfileRow key={p.id} p={p} onPropose={(formulation) =>
              act(() => send("post", "/api/v1/projects/{project_id}/dissolution/{profile_id}:propose", { project_id: projectId, profile_id: p.id }, { formulation }))} />
          ))}
        </tbody>
      </table>
      {d.comparisons.length > 0 && (
        <table style={{ marginTop: 10 }}>
          <thead><tr><th>Test vs reference</th><th>Condition</th><th className="num">f2</th><th>Verdict</th></tr></thead>
          <tbody>
            {d.comparisons.map((c) => (
              <tr key={`${c.test}-${c.reference}`} data-testid="f2-row">
                <td>{label(c.test)}<div className="muted" style={{ fontSize: 12 }}>vs {label(c.reference)}</div></td>
                <td>{c.condition}</td>
                <td className="num">{c.f2 ?? "—"}</td>
                <td>{c.applicable ? <span className={`chip ${c.similar ? "low" : "high"}`}>{c.similar ? "similar" : "not similar"}</span>
                     : <span className="muted" style={{ fontSize: 13 }}>{c.reasons.join("; ")}</span>}
                  <div className="muted" style={{ fontSize: 11 }}>{c.ruleset}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {d.problems.length > 0 && <ul className="flags">{d.problems.map((x) => <li key={x}>{x}</li>)}</ul>}
    </Card>
  );
}


/** P3 client data (plan §10): what arrived, reading it sheet by sheet, and what the data plan still waits for. */
export function ClientData({ projectId }: { projectId: string }) {
  const page = useResource("/api/v1/projects/{project_id}/client-data", { project_id: projectId },
    { select: (d) => narrow<View>(d), poll: (d) => d.running });
  const { run } = useMutation();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [note, setNote] = useState("");
  const [reading, setReading] = useState<{ file: string; sheet: string } | null>(null);
  const [last, setLast] = useState<{ form: SheetForm; study: Study } | null>(null);
  const [dragging, setDragging] = useState(false);

  const view = page.data;

  if (page.problem) return <div className="banner err">{page.problem}</div>;
  if (!view) return <p className="muted">Loading…</p>;

  // a change, then the client data and the phase rail read again; answers the API's reason when it refused
  const act: Act = async (fn) => (await run(fn)).problem;
  const say = (error: string | null, ok: string) => setMessage(error ? { ok: false, text: error } : { ok: true, text: ok });
  async function upload(files: FileList | null) {
    if (!files?.length) return;
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    say(await act(() => uploadTo("/api/v1/projects/{project_id}/client-data", { project_id: projectId }, form)),
        `${plural(files.length, "file")} stored. Read each data sheet below (“Read this sheet”).`);
  }
  async function downloadTemplate() {
    const { file, problem } = await apiFile("/api/v1/client-data/template.xlsx");
    if (!file) { say(`The template could not be downloaded: ${problem}`, ""); return; }
    const url = URL.createObjectURL(file);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${view?.template ?? "ModelerOne_ClientData"}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  }
  const decide = (r: Reconciled) => (body: Schema<"OverrideRequest">) =>
    act(() => send("put", "/api/v1/projects/{project_id}/requirements/{req_id}", { project_id: projectId, req_id: r.req_id }, body));
  async function approve() {
    say(await act(() => send("post", "/api/v1/projects/{project_id}/client-data:approve", { project_id: projectId }, { note })),
        "Client data approved (P3).");
  }

  const recon = view.reconciliation;
  const blocking = recon.rows.filter((r) => recon.blocking.includes(r.req_id));
  const others = recon.rows.filter((r) => !recon.blocking.includes(r.req_id));
  let sheetsTodo = 0, sheetsDone = 0;
  for (const f of view.files.filter((x) => !x.template)) {
    const read = readSheets(f);
    for (const t of f.triage) {
      if (read.has(t.sheet)) sheetsDone += 1;
      else if (DATA_SHEETS.has(t.category)) sheetsTodo += 1;
    }
  }
  return (
    <>
      <Progress view={view} projectId={projectId} sheetsTodo={sheetsTodo} sheetsDone={sheetsDone} onApprove={() => void approve()}
                note={note} setNote={setNote} />
      {message && <div className={`banner ${message.ok ? "ok" : "err"}`} style={{ marginTop: 12 }} role="status">{message.text}</div>}

      {blocking.length > 0 && (
        <Card title={`What stops approval (${blocking.length})`}>
          <div id="blocking" className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
            Each item below is required by the data plan and has not arrived from the client. Deliver it (read the sheet that
            holds it), or decide, with a reason: <strong>not from the client</strong> (the model goes ahead without it and the
            gap is recorded) or <strong>get it from the literature instead</strong> (the literature step takes it over).
          </div>
          {blocking.map((r) => <PlanItem key={r.req_id} r={r} onDecide={decide(r)} blocking />)}
        </Card>
      )}

      <Card title="Add files" action={<button className="btn" onClick={() => void downloadTemplate()} data-testid="download-template">Download the client-data template</button>}>
        <label className={`dropzone${dragging ? " over" : ""}`}
               onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
               onDrop={(e) => { e.preventDefault(); setDragging(false); void upload(e.dataTransfer.files); }}>
          <input type="file" multiple hidden data-testid="client-upload" accept=".xlsx,.xlsm,.xls,.csv,.pdf,.docx,.md,.txt"
                 onChange={(e) => void upload(e.target.files)} />
          <strong>Drop the client&apos;s files here</strong> or click to choose
          <span className="muted">Excel (.xlsx, or .xls from Excel 97–2003), CSV, PDF, Word, Markdown. Workbooks are sorted sheet by sheet; reports are kept as citable documents.</span>
        </label>
      </Card>

      <Card title={`Files (${view.files.length})`}>
        {view.files.length === 0 ? <p className="muted" style={{ margin: 0 }}>No client files yet.</p> : (
          <>
            <p className="muted" style={{ margin: "0 0 8px", fontSize: 13 }}>
              For each sheet with data, press <strong>Read this sheet</strong>: the sheet is shown next to a form already filled in from
              what the sheet states. Check it, press <strong>Check what will be read</strong>, then <strong>Save</strong>.
            </p>
            {view.files.map((f) => (
              <FileCard key={f.id} projectId={projectId} file={f} agents={view.agents.enabled} running={view.running} act={act}
                        reading={reading?.file === f.id ? reading.sheet : null}
                        setReading={(sheet) => setReading(sheet ? { file: f.id, sheet } : null)}
                        onSaved={async (m) => say(null, m)} last={last} remember={setLast} />
            ))}
          </>
        )}
      </Card>

      {view.dissolution.profiles.length > 0 && <Dissolution projectId={projectId} d={view.dissolution} act={act} />}

      <Card title="Everything the data plan expects from the client">
        {recon.rows.length === 0 ? <p className="muted" style={{ margin: 0 }}>The data plan expects nothing from the client.</p>
          : others.length === 0 ? <p className="muted" style={{ margin: 0 }}>All items are listed under “What stops approval”.</p>
          : others.map((r) => <PlanItem key={r.req_id} r={r} onDecide={decide(r)} blocking={false} />)}
        {recon.unpromised.length > 0 && (
          <>
            <h3 style={{ fontSize: 14, margin: "14px 0 4px" }}>Delivered, not in the data plan</h3>
            <ul className="flags">{recon.unpromised.map((u) => <li key={u}>{u}</li>)}</ul>
          </>
        )}
      </Card>
    </>
  );
}
