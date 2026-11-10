"use client";

import { useState } from "react";

import { PeekButton } from "@/components/kit/SourcePeek";
import { Card } from "@/components/ui";
import { send, type Envelope, type Schema } from "@/lib/api";
import { TAG_KINDS, TAG_LABELS, type TagKind } from "@/lib/fileTags";

import { CleaningRecord } from "./CleaningRecord";
import { SheetReader, type Study } from "./SheetReader";
import {
  CATEGORY_LABEL, type ClientFile, DATA_SHEETS, type Profile, READABLE, READABLE_DOCUMENTS, type SheetForm, type Triage,
  type View, readSheets,
} from "./types";

export type Act = <T>(fn: () => Promise<Envelope<T>>) => Promise<string | null>;
/** Say what a file is (its tag), which moves it to the area of Inputs that holds that data (plan 2026-11-05 §3.1). */
export type Retag = (file: ClientFile, kind: TagKind) => Promise<string | null>;

/** The call that sets a client file's tag (`documents/{sha256}:tag`); a clinical file keeps the study it names. */
export const retagCall = (projectId: string, file: ClientFile, kind: TagKind) => () =>
  send("post", "/api/v1/projects/{project_id}/documents/{sha256}:tag", { project_id: projectId, sha256: file.sha256 },
       { kind, study: kind === "clinical" ? file.tag?.study ?? "" : "" });

/** What a file is, changeable at any time, and the other kind code read from its content, to use or keep. */
export function FileTagLine({ file, onRetag }: { file: ClientFile; onRetag: Retag }) {
  const [error, setError] = useState<string | null>(null);
  const proposal = file.tag_proposal?.decided === "open" ? file.tag_proposal : null;
  const retag = async (kind: TagKind) => setError(await onRetag(file, kind));
  return (
    <div className="file-tag" data-testid={`file-tag-${file.file}`}>
      <label className="row" style={{ gap: 6 }}>
        <span className="muted">This file is</span>
        <select value={file.tag?.kind ?? ""} aria-label={`what ${file.file} is`} onChange={(e) => void retag(e.target.value as TagKind)}>
          {!file.tag && <option value="" disabled>not said yet</option>}
          {TAG_KINDS.map((k) => <option key={k} value={k}>{TAG_LABELS[k]}</option>)}
        </select>
      </label>
      {proposal && (
        <div className="tag-proposal" data-testid={`tag-proposal-${file.file}`}>
          <span>Its content reads as <strong>{TAG_LABELS[proposal.kind].toLowerCase()}</strong>: {proposal.why}.</span>
          <span className="row" style={{ gap: 8 }}>
            <button type="button" className="btn" onClick={() => void retag(proposal.kind)}>Use it</button>
            {file.tag && <button type="button" className="linkish" onClick={() => void retag(file.tag!.kind)}>
              Keep {TAG_LABELS[file.tag.kind].toLowerCase()}</button>}
          </span>
        </div>
      )}
      {error && <div className="banner err">{error}</div>}
    </div>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
type Category = Schema<"Classification">["category"];

/** A sheet's line: what it holds, whether it was read, and the button that reads it. */
function SheetLine({ t, read, proposed, byCode, reading, onRead, onClassify }: {
  t: Triage; read: number | undefined; proposed: boolean; byCode: string[] | null; onRead: () => void;
  reading: NonNullable<ClientFile["readings"]>[string] | undefined;
  onClassify: (category: Category, reason: string) => Promise<string | null>;
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
        <CleaningRecord lines={reading?.cleaning} testId={`sheet-cleaning-${t.sheet}`} />
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
               : byCode ? <span className="chip medium" title="read on arrival; what the sheet does not say is asked on its study's or product's card">
                   read by {reading?.by === "code" ? "code" : "the reading agent"} · {byCode.length} to give on its card</span>
               : proposed ? <span className="chip brand" title="checked by code; open it, check it and save">reading proposed</span>
               : data ? <span className="chip medium">not read yet</span> : <span className="muted" style={{ fontSize: 12 }}>no data to read</span>}</td>
      <td className="num"><button className={`btn${!read && data ? " primary" : ""}`} onClick={onRead}>{read ? "Read again" : "Read this sheet"}</button></td>
    </tr>
  );
}

/** A client PDF or Word file (I4): the pages code found holding project data, each opening in the centre peek with its
 * line highlighted; the reading agent's button; and what its last reading proposed and what code refused. What it
 * proposed waits on Inputs, in its study or product, until a person confirms it. */
function DocumentReading({ projectId, file, agents, running, agentReading, act }: {
  projectId: string; file: ClientFile; agents: boolean; running: boolean; agentReading: boolean; act: Act;
}) {
  const [notice, setNotice] = useState<string | null>(null);
  const items = file.inventory ?? [];
  const last = (file.document_reads ?? []).at(-1);
  return (
    <div className="doc-reading" data-testid={`document-${file.file}`}>
      <div className="spread">
        <span className="muted">
          {items.length > 0 ? `Code found project data on ${new Set(items.map((i) => i.page)).size} page${new Set(items.map((i) => i.page)).size === 1 ? "" : "s"}:`
                            : "Code found no page that clearly holds project data; the agent can still look through the file."}
        </span>
        <button className={`btn${last ? "" : " primary"}`} disabled={!agents || running} data-testid={`read-doc-${file.file}`}
                title={agents ? "Agent A4 reads the file; code checks every value against its page" : "agents are off"}
                onClick={async () => setNotice(await act(() => send("post", "/api/v1/projects/{project_id}/client-data/{sid}:read",
                                                                    { project_id: projectId, sid: file.id }, {}))
                  ?? "Agent A4 reads the file, after any file queued before it. What code accepts appears in its study or product, to confirm.")}>
          {agentReading ? "Reading…" : last ? "Read again (agent)" : "Read the data in this file (agent)"}
        </button>
      </div>
      {items.length > 0 && (
        <ul className="doc-inventory">
          {items.map((i) => (
            <li key={`${i.page}-${i.holds}`} data-testid={`inventory-${i.page}-${i.holds}`}>
              <span className="chip neutral">p. {i.page}</span> {i.label} <span className="muted">“{i.line}”</span>
              <PeekButton projectId={projectId} label={`${file.file}, p. ${i.page}`}
                          source={{ doc_sha256: file.sha256, page: i.page, quote: i.line, title: file.file, locator: `p. ${i.page}` }} />
            </li>
          ))}
        </ul>
      )}
      {last && (
        <div className="doc-read" data-testid={`document-read-${file.file}`}>
          <strong>Read by the agent:</strong>{" "}
          {[[last.datasets.length, "dataset"], [last.facts, "study fact"], [last.dissolution_rows, "dissolution row"],
            [last.links, "name link"], [last.compositions ?? 0, "composition"],
            [last.digitization.length, "figure for a person to digitize"]]
            .filter(([n]) => Number(n) > 0).map(([n, w]) => plural(Number(n), String(w))).join(" · ") || "nothing code accepted"}.
          {" "}Each is shown in its study or product and loads only once a person confirms it there.
          {last.refused.length > 0 && (
            <details>
              <summary>{plural(last.refused.length, "proposal")} refused by code</summary>
              <ul className="flags">{last.refused.map((r, k) => <li key={k}>{r}</li>)}</ul>
            </details>
          )}
          {last.summary && <p className="muted" style={{ margin: "4px 0 0" }}>{last.summary}</p>}
        </div>
      )}
      {notice && <div className="banner ok">{notice}</div>}
    </div>
  );
}

function FileCard({ projectId, file, agents, running, agentReading, act, onRetag, reading, setReading, onSaved, last, remember }: {
  projectId: string; file: ClientFile; agents: boolean; running: boolean; agentReading: boolean; act: Act; onRetag?: Retag;
  reading: string | null;
  setReading: (sheet: string | null) => void; onSaved: (message: string) => Promise<void>;
  last: { form: SheetForm; study: Study } | null; remember: (s: { form: SheetForm; study: Study }) => void;
}) {
  const [notice, setNotice] = useState<string | null>(null);
  const spreadsheet = file.triage.length > 0;
  const read = readSheets(file);
  const undecided = file.triage.some((t) => t.category === "OTHER" && t.by === "code");
  const unread = file.triage.filter((t) => READABLE.has(t.category) && !read.has(t.sheet)).length;
  return (
    <div className="file-card" data-testid={`client-file-${file.file}`} id={`client-file-${file.id}`}>
      <div className="spread">
        <div className="row">
          <strong>{file.file}</strong>
          <span className={`chip ${file.template ? "low" : "neutral"}`}>{file.template ? "client-data template" : file.kind}</span>
          {file.datasets.length > 0 && <span className="chip neutral">{plural(file.datasets.length, "dataset")}</span>}
          {file.evidence.length > 0 && <span className="chip neutral">{plural(file.evidence.length, "value")}</span>}
          {file.dissolution.length > 0 && <span className="chip neutral">{plural(file.dissolution.length, "dissolution row")}</span>}
        </div>
        <div className="row">
          {spreadsheet && !file.template && undecided && (
            <button className="btn" disabled={!agents || running} title={agents ? undefined : "agents are off"}
                    onClick={async () => setNotice(await act(() => send("post", "/api/v1/projects/{project_id}/client-data/{sid}:triage", { project_id: projectId, sid: file.id }))
                      ?? "Agent A4 is sorting the unsorted sheets.")}>Sort the unsorted sheets (agent)</button>
          )}
          {spreadsheet && !file.template && unread > 0 && (
            <button className="btn" disabled={!agents || running} title={agents ? undefined : "agents are off: read each sheet with the form"}
                    data-testid={`read-agent-${file.file}`}
                    onClick={async () => setNotice(await act(() => send("post", "/api/v1/projects/{project_id}/client-data/{sid}:read", { project_id: projectId, sid: file.id }, {}))
                      ?? "Agent A4 reads the data sheets, after any file queued before them. Each reading opens on its sheet once code has checked it.")}>
              {agentReading ? "Reading the sheets…" : `Read the data sheets (agent, ${unread})`}
            </button>
          )}
        </div>
      </div>
      {onRetag && <FileTagLine file={file} onRetag={onRetag} />}
      {!spreadsheet && READABLE_DOCUMENTS.has(file.kind) && (
        <DocumentReading projectId={projectId} file={file} agents={agents} running={running} agentReading={agentReading} act={act} />
      )}
      {!spreadsheet && !READABLE_DOCUMENTS.has(file.kind) && (
        <p className="muted" style={{ margin: "4px 0" }}>Kept as a citable document: the literature agents and you can quote it.</p>
      )}
      {file.template && <p className="muted" style={{ margin: "4px 0" }}>The client-data template is read automatically, cell by cell.</p>}
      {spreadsheet && !file.template && (
        <table style={{ marginTop: 6 }}>
          <thead><tr><th>Sheet</th><th>Holds</th><th>Read</th><th /></tr></thead>
          <tbody>
            {file.triage.map((t) => (
              <SheetLine key={t.sheet} t={t} read={read.get(t.sheet)} proposed={Boolean(file.readings?.[t.sheet])}
                         byCode={file.readings?.[t.sheet]?.needs?.length ? file.readings[t.sheet].needs ?? null : null}
                         reading={file.readings?.[t.sheet]}
                         onRead={() => setReading(reading === t.sheet ? null : t.sheet)}
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

/** The dissolution profiles, their Weibull fits and f2 (also on the Inputs step's Formulations tab). */
export function Dissolution({ projectId, d, act }: {
  projectId: string; d: View["dissolution"];
  act: Act;
}) {
  const label = (id: string) => d.profiles.find((p) => p.id === id)?.label ?? id;
  return (
    <Card title={`Dissolution (${d.profiles.length} profiles)`}>
      <p className="muted" style={{ margin: "0 0 6px", fontSize: 13 }}>
        Each profile is fitted with PK-Sim&apos;s Weibull release (t50, shape, lag 0). Which profile stands for release in
        the body is a planning decision; proposing one makes its values flow into the formulation, for the review.
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


/** The client's files: each sheet with what it holds and whether it is read, the agent's proposed readings, and the reader
 *  opened on one sheet. Shown on the area of Inputs each file's tag names (plan 2026-11-05 §3.1): `files`, the area's. */
export function ClientFiles({ projectId, view, files, act, onRetag, onSaved }: {
  projectId: string; view: View; files?: ClientFile[]; act: Act; onRetag?: Retag; onSaved: (message: string) => Promise<void>;
}) {
  const [reading, setReading] = useState<{ file: string; sheet: string } | null>(null);
  const [last, setLast] = useState<{ form: SheetForm; study: Study } | null>(null);
  return (
    <>
      {(files ?? view.files).map((f) => (
        <FileCard key={f.id} projectId={projectId} file={f} agents={view.agents.enabled} running={view.running}
                  agentReading={view.reading} act={act} onRetag={onRetag} reading={reading?.file === f.id ? reading.sheet : null}
                  setReading={(sheet) => setReading(sheet ? { file: f.id, sheet } : null)}
                  onSaved={onSaved} last={last} remember={setLast} />
      ))}
    </>
  );
}
