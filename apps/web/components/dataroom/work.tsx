"use client";

// What the modeler settles in the Data room (plan 2026-11-21 v2 §5 steps 6, 7, 9; §7): the decisions with their options
// and evidence, the data requests coded A-D with their wording to the client, the simulation plan, the PK-Sim inputs by
// building block (the one place PK-Sim's own names are shown), and "Send to the model", signed.

import { createContext, useContext, useState } from "react";

import { send } from "@/lib/api";
import {
  AREA, BLOCK, METRIC, REQUEST_STATUS, valueText, when,
  type DataRequest, type Decision, type InputRow, type Publication, type Room,
} from "@/lib/dataroom";
import { useMutation, useResource } from "@/lib/hooks";

import { PUBLICATION, ROOM, useRoomActs } from "./acts";
import { Card, Nothing, Row, Sources, StatusTag, Table, usePaper } from "./kit";

// --- decisions ---------------------------------------------------------------------------------------------------------

function DecisionCard({ d }: { d: Decision }) {
  const acts = useRoomActs();
  const paper = usePaper();
  const [choice, setChoice] = useState(d.chosen ?? d.suggested);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const option = (id: string) => d.options.find((o) => o.id === id);
  const label = (id: string) => option(id)?.label ?? id;
  const name = `decision-${d.id}`;
  const choose = async (id: string, why: string) => {
    const got = await acts!.decide(d.id, id, why.trim());
    setProblem(got.problem);
    if (!got.problem) { setReason(""); setOpen(false); }
  };
  const suggested = option(d.suggested);
  const others = d.options.length - 1;
  return (
    <Card title={d.title} testId={`decision-${d.id}`}
          aside={d.chosen ? <span className="dr-tag ok" data-testid="decision-chosen">Chosen</span> : <span className="dr-tag warn">Waiting</span>}>
      <p className="dr-lede">{d.question}</p>
      {paper ? (
        <dl className="dr-facts">
          <div className="wide"><dt>Suggested</dt><dd>{label(d.suggested)}{d.why && ` · ${d.why}`}</dd></div>
          <div className="wide"><dt>Chosen</dt><dd>{d.chosen ? `${label(d.chosen)} · by ${d.by} · ${when(d.at)}${d.reason ? ` · ${d.reason}` : ""}` : "not yet"}</dd></div>
          <div className="wide"><dt>Other options</dt><dd>{d.options.filter((o) => o.id !== d.suggested).map((o) => o.label).join(" · ") || "none"}</dd></div>
          {d.evidence.length > 0 && <div className="wide"><dt>Evidence</dt><dd><Sources chips={d.evidence} /></dd></div>}
        </dl>
      ) : (
        <>
          {d.chosen ? (
            <div className="dr-made" data-testid="decision-made">
              <span className="dr-suggest-label">Chosen</span><strong>{label(d.chosen)}</strong>
              <span className="muted">by {d.by}, {when(d.at)}{d.reason ? ` · ${d.reason}` : ""}</span>
            </div>
          ) : (
            <div className="dr-suggest" data-testid="decision-suggestion">
              <span className="dr-suggest-label">Suggested</span>
              <span className="dr-suggest-choice">{suggested?.label ?? d.suggested}</span>
              {suggested?.detail && <span className="dr-option-detail">{suggested.detail}</span>}
              {d.why && <span className="dr-suggest-why">{d.why}</span>}
              {d.evidence.length > 0 && <span className="dr-sources">Evidence: <Sources chips={d.evidence} max={3} /></span>}
            </div>
          )}
          {!d.chosen && (
            <form className="dr-form-row" onSubmit={(e) => { e.preventDefault(); void choose(d.suggested, reason); }}>
              <label className="dr-field grow"><span>Reason (optional)</span>
                <input value={open ? "" : reason} onChange={(e) => setReason(e.target.value)} disabled={open} data-testid="decision-accept-reason" /></label>
              <button type="submit" className="btn primary" disabled={acts?.busy || open} data-testid="decision-accept">Choose the suggestion</button>
            </form>
          )}
          {(others > 0 || d.chosen) && (
            <details className="dr-fold" open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
              <summary data-testid="decision-others">{d.chosen ? "Change the choice" : `${others === 1 ? "The other option" : `The other ${others} options`}`}</summary>
              <form className="dr-form" onSubmit={(e) => { e.preventDefault(); void choose(choice, reason); }}>
                <fieldset className="dr-options">
                  <legend className="sr-only">{d.question}</legend>
                  {d.options.map((o) => (
                    <label key={o.id} className={`dr-option${choice === o.id ? " on" : ""}`} data-testid={`option-${o.id}`}>
                      <input type="radio" name={name} value={o.id} checked={choice === o.id} onChange={() => setChoice(o.id)} />
                      <span className="dr-option-text">
                        <span>{o.label}{o.id === d.suggested && <span className="dr-tag info small">Suggested</span>}
                          {o.id === d.chosen && <span className="dr-tag ok small">Chosen</span>}</span>
                        {o.detail && <span className="dr-option-detail">{o.detail}</span>}
                      </span>
                    </label>
                  ))}
                </fieldset>
                <div className="dr-form-row">
                  <label className="dr-field grow"><span>Reason{choice !== d.suggested ? " (needed for another option than the suggestion)" : ""}</span>
                    <input value={reason} onChange={(e) => setReason(e.target.value)} data-testid="decision-reason"
                           required={choice !== d.suggested} placeholder={choice === d.suggested ? "optional" : "why this option"} />
                  </label>
                  <button type="submit" className="btn primary" disabled={acts?.busy || (choice === d.chosen && !reason.trim())}
                          data-testid="decision-choose">Choose</button>
                </div>
              </form>
            </details>
          )}
          {problem && <div className="banner err" role="alert">{problem}</div>}
        </>
      )}
    </Card>
  );
}

/** The decisions, the waiting ones first; `ids`: only these (each section of the page in its groups holds its own). */
export function Decisions({ room, ids }: { room: Room; ids?: readonly string[] }) {
  const mine = ids ? room.decisions.filter((d) => ids.includes(d.id)) : room.decisions;
  if (!mine.length) return ids ? null : <Nothing>No decision is waiting: they come with the clinical and in vitro data.</Nothing>;
  const ordered = [...mine.filter((d) => !d.chosen), ...mine.filter((d) => d.chosen)];
  return <>{ordered.map((d) => <DecisionCard key={d.id} d={d} />)}</>;
}

// --- entering a value ------------------------------------------------------------------------------------------------

function EnterValue({ input, label, unit, onDone }: { input: string; label: string; unit: string; onDone: () => void }) {
  const acts = useRoomActs();
  const [value, setValue] = useState("");
  const [u, setU] = useState(unit);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <form className="dr-form dr-enter" data-testid={`enter-${input}`} onSubmit={async (e) => {
      e.preventDefault();
      const n = Number(value);
      const got = await acts!.enter(input, label, value.trim() !== "" && Number.isFinite(n) ? n : value.trim(), u.trim(), reason.trim());
      setProblem(got.problem);
      if (!got.problem) onDone();
    }}>
      <div className="dr-form-row">
        <label className="dr-field"><span>Value</span><input value={value} onChange={(e) => setValue(e.target.value)} required data-testid="enter-value" /></label>
        <label className="dr-field"><span>Unit</span><input value={u} onChange={(e) => setU(e.target.value)} /></label>
        <label className="dr-field grow"><span>Reason (where it comes from)</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} required data-testid="enter-reason" /></label>
      </div>
      {problem && <div className="banner err" role="alert">{problem}</div>}
      <div className="dr-actions">
        <button type="submit" className="btn primary" disabled={acts?.busy}>Enter</button>
        <button type="button" className="btn ghost" onClick={onDone}>Cancel</button>
      </div>
    </form>
  );
}

// --- data requests -----------------------------------------------------------------------------------------------------

function RequestItem({ r }: { r: DataRequest }) {
  const acts = useRoomActs();
  const paper = usePaper();
  const [wording, setWording] = useState(r.wording);
  const [entering, setEntering] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (paper) {
    return (
      <li className="dr-request" data-testid={`request-${r.id}`}>
        <span className="dr-code">{r.id}</span>
        <div><strong>{r.title}</strong> <span className="muted">· {REQUEST_STATUS[r.status]}</span>
          <p className="dr-request-wording">{r.wording || r.why}</p></div>
      </li>
    );
  }
  return (
    <li className={`dr-request ${r.status}`} data-testid={`request-${r.id}`}>
      <span className="dr-code">{r.id}</span>
      <div className="dr-request-body">
        <div className="spread"><strong>{r.title}</strong>
          <div className="dr-seg" role="group" aria-label={`Status of ${r.id}`}>
            {(["open", "not_needed", "answered"] as const).map((s) => (
              <button key={s} type="button" aria-pressed={r.status === s} className={r.status === s ? "on" : ""} disabled={acts?.busy}
                      data-testid={`request-${r.id}-${s}`}
                      onClick={async () => setProblem((await acts!.request(r.id, { status: s })).problem)}>{REQUEST_STATUS[s]}</button>
            ))}
          </div>
        </div>
        <p className="muted dr-request-why">{r.why}</p>
        <label className="dr-field"><span className="sr-only">Wording to the client</span>
          <textarea rows={2} value={wording} placeholder="The request as the client will read it" onChange={(e) => setWording(e.target.value)}
                    data-testid={`request-${r.id}-wording`} /></label>
        <div className="dr-actions">
          <button type="button" className="btn small" disabled={acts?.busy || wording === r.wording}
                  onClick={async () => setProblem((await acts!.request(r.id, { wording })).problem)}>Save the wording</button>
          {r.input && !entering && <button type="button" className="btn small" onClick={() => setEntering(true)}>Enter the value yourself</button>}
        </div>
        {entering && r.input && <EnterValue input={r.input} label={r.title} unit="" onDone={() => setEntering(false)} />}
        {problem && <div className="banner err" role="alert">{problem}</div>}
      </div>
    </li>
  );
}

function requestsText(room: Room): string {
  const lines: string[] = [];
  for (const area of ["A", "B", "C", "D"] as const) {
    const list = room.requests.filter((r) => r.area === area && r.status === "open");
    if (!list.length) continue;
    lines.push(`${area}. ${AREA[area]}`);
    for (const r of list) lines.push(`${r.id}  ${r.title}\n    ${r.wording || r.why}`);
    lines.push("");
  }
  return lines.join("\n").trim();
}

export function Requests({ room, area }: { room: Room; area?: DataRequest["area"] }) {
  const paper = usePaper();
  const [copied, setCopied] = useState(false);
  const list = area ? room.requests.filter((r) => r.area === area) : room.requests;
  if (!list.length) return area ? null : <Nothing>No data request: nothing is missing or contradictory.</Nothing>;
  const groups = (["A", "B", "C", "D"] as const).filter((a) => list.some((r) => r.area === a));
  if (area) {
    return (
      <Card title="Data requests from this section">
        <ul className="dr-requests">{list.map((r) => <RequestItem key={r.id} r={r} />)}</ul>
      </Card>
    );
  }
  return (
    <>
      {!paper && (
        <div className="dr-actions dr-export">
          <button type="button" className="btn" data-testid="requests-copy" onClick={async () => {
            try { await navigator.clipboard.writeText(requestsText(room)); setCopied(true); } catch { setCopied(false); }
          }}>{copied ? "Copied" : "Copy as text"}</button>
          <button type="button" className="btn" data-testid="requests-print" onClick={() => {
            document.documentElement.dataset.print = "requests";
            window.addEventListener("afterprint", () => { delete document.documentElement.dataset.print; }, { once: true });
            window.print();
          }}>Print or save as PDF</button>
        </div>
      )}
      {groups.map((a) => (
        <Card key={a} title={`${a} · ${AREA[a]}`} testId={`requests-${a}`}>
          <ul className="dr-requests">{list.filter((r) => r.area === a).map((r) => <RequestItem key={r.id} r={r} />)}</ul>
        </Card>
      ))}
      {!paper && (
        // what "Print" sends to paper: the open requests alone, worded for the client
        <div className="dr-print-requests" aria-hidden>
          <h1>Data requests</h1>
          <pre>{requestsText(room)}</pre>
        </div>
      )}
    </>
  );
}

// --- simulation plan ---------------------------------------------------------------------------------------------------

const ROLE: Record<string, string> = { development: "Development", calibration: "Calibration", verification: "Verification", prediction: "Prediction" };

export function Plan({ room }: { room: Room }) {
  if (!room.plan.length) return <Nothing>No simulation is planned yet: the plan follows the studies and products read.</Nothing>;
  return (
    <Card title="What each simulation is compared with" testId="plan">
      <Table head={["Formulation and condition", "Observed data", "Role"]} label="The simulation plan">
        {room.plan.map((r, i) => (
          <Row key={i} cells={[
            <span key="f"><strong>{r.formulation}</strong><span className="dr-file-kind">{r.condition}</span></span>,
            <span key="o">{r.observed}</span>,
            <span key="r" className={`dr-tag role-${r.role}`}>{ROLE[r.role] ?? r.role}</span>,
          ]} details={r.why ? <p className="dr-note">{r.why}</p> : undefined} />
        ))}
      </Table>
      <p className="dr-note">The plan is signed with the Modeling Analysis Plan before any calibration starts.</p>
    </Card>
  );
}

// --- PK-Sim inputs -----------------------------------------------------------------------------------------------------

// the inputs a person may enter: those a data request names (the room takes an entered value for them)
const EnterableContext = createContext<ReadonlySet<string>>(new Set());

function InputLine({ r }: { r: InputRow }) {
  const acts = useRoomActs();
  const paper = usePaper();
  const [entering, setEntering] = useState(false);
  const enterable = useContext(EnterableContext).has(r.name) && !paper && acts !== null;
  return (
    <>
      <Row testId={`input-${r.name}`} highlight={r.status === "missing"} cells={[
        <span key="n" className="dr-file"><code className="dr-pk">{r.block === "target" ? METRIC[r.name] ?? r.name : r.name}</code>
          <span className="dr-file-kind">{r.block === "target" ? targetLabel(r) : r.label}</span></span>,
        <span key="v" className="dr-value">{valueText(r.value, r.unit)}</span>,
        <StatusTag key="s" status={r.status} />,
        <span key="o" className="dr-sources">
          <Sources chips={r.sources} />
          {enterable && r.status === "missing" && !entering && (
            <button type="button" className="btn small" onClick={() => setEntering(true)} data-testid={`enter-open-${r.name}`}>Enter</button>)}
        </span>,
      ]} details={(r.note || r.decision) ? (
        <dl className="dr-facts">
          {r.note && <div className="wide"><dt>Note</dt><dd>{r.note}</dd></div>}
          {r.decision && <div className="wide"><dt>Follows</dt><dd>a decision in Decisions</dd></div>}
        </dl>
      ) : undefined} />
      {entering && (
        <tr className="dr-detail"><td colSpan={4}><EnterValue input={r.name} label={r.label} unit={r.unit} onDone={() => setEntering(false)} /></td></tr>
      )}
    </>
  );
}

function Publish({ projectId }: { projectId: string }) {
  const paper = usePaper();
  const plan = useResource(PUBLICATION, { project_id: projectId });
  const { run, busy } = useMutation();
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<{ text: string; ok: boolean } | null>(null);
  if (paper) return null;
  const p: Publication | null = plan.data;
  return (
    <Card title="Send to the model" testId="publish">
      {plan.problem && <div className="banner err">{plan.problem}</div>}
      {p && (
        <>
          <p className="dr-lede" data-testid="publish-counts">
            {p.evidence.length} {p.evidence.length === 1 ? "input" : "inputs"} and {p.datasets.length} observed{" "}
            {p.datasets.length === 1 ? "dataset" : "datasets"} will be sent, each with its source. Review &amp; sign then starts from them.
          </p>
          {p.blocked.length > 0 ? (
            <div className="dr-blocked" data-testid="publish-blocked">
              <h4>What still keeps it from being sent</h4>
              <ul>{p.blocked.map((b) => <li key={b}>{b}</li>)}</ul>
            </div>
          ) : <p className="dr-note">Nothing blocks it. Sending asks you to confirm your identity: it is signed.</p>}
          {p.notes.length > 0 && (
            <div className="dr-note" data-testid="publish-notes">
              <h4>Sent otherwise than the files might suggest</h4>
              <ul>{p.notes.map((n) => <li key={n}>{n}</li>)}</ul>
            </div>
          )}
          <form className="dr-form-row" onSubmit={async (e) => {
            e.preventDefault();
            const got = await run(() => send("post", "/api/v1/projects/{project_id}/dataroom/publish", { project_id: projectId }, { reason: reason.trim() }),
                                  { reads: [PUBLICATION, ROOM] });
            setResult(got.problem ? { text: got.problem, ok: false }
              : { ok: true, text: `Sent as ${got.data?.publication}: ${got.data?.evidence} inputs and ${got.data?.datasets} datasets (${got.data?.skipped} already there, ${got.data?.superseded} earlier ones replaced). Signed ${got.data?.manifestation}.` });
          }}>
            <label className="dr-field grow"><span>Why now</span>
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. inputs confirmed with the client" required
                     data-testid="publish-reason" /></label>
            <button type="submit" className="btn primary" disabled={busy || p.blocked.length > 0 || !reason.trim()} data-testid="publish-send">
              Send to the model</button>
          </form>
          {result && <div className={`banner ${result.ok ? "ok" : "err"}`} role={result.ok ? "status" : "alert"}>{result.text}</div>}
        </>
      )}
    </Card>
  );
}

/** An evaluation target's label in words: "Cmax (geometric mean, modeling set, N = 6)". */
function targetLabel(r: InputRow): string {
  const rest = r.label.startsWith(r.name) ? r.label.slice(r.name.length) : ` ${r.label}`;
  return `${METRIC[r.name] ?? r.name}${rest.replace(/\bauc set\b/, "AUC set")}`;
}

function InputBlock({ block, rows }: { block: InputRow["block"]; rows: InputRow[] }) {
  const paper = usePaper();
  const missing = rows.filter((r) => r.status === "missing").length;
  // the compound and any block with a missing input are open; the others fold to their count
  const [open, setOpen] = useState(block === "compound" || missing > 0);
  const owners = [...new Set(rows.map((r) => r.owner))];
  return (
    <Card title={BLOCK[block]} testId={`inputs-${block}`}
          aside={(
            <>
              <span className="muted dr-small">{rows.length - missing} of {rows.length} filled</span>
              {!paper && <button type="button" className="dr-link" aria-expanded={open} onClick={() => setOpen(!open)}
                                 data-testid={`inputs-${block}-toggle`}>{open ? "Fold" : "Show"}</button>}
            </>
          )}>
      {(open || paper) && (
        <Table head={["PK-Sim name", "Value", "Status", "Source"]} label={`PK-Sim inputs: ${BLOCK[block]}`}>
          {owners.map((o) => (
            <OwnerRows key={o || "-"} owner={o} rows={rows.filter((r) => r.owner === o)} many={owners.length > 1 || Boolean(o)} />
          ))}
        </Table>
      )}
    </Card>
  );
}

export function Inputs({ room, projectId }: { room: Room; projectId: string }) {
  if (!room.inputs.length) return <Nothing>No PK-Sim input yet.</Nothing>;
  const blocks = (Object.keys(BLOCK) as InputRow["block"][]).filter((b) => room.inputs.some((r) => r.block === b));
  return (
    <>
      <EnterableContext.Provider value={new Set(room.requests.map((q) => q.input).filter(Boolean))}>
        {blocks.map((b) => <InputBlock key={b} block={b} rows={room.inputs.filter((r) => r.block === b)} />)}
      </EnterableContext.Provider>
      <Publish projectId={projectId} />
    </>
  );
}

function OwnerRows({ owner, rows, many }: { owner: string; rows: InputRow[]; many: boolean }) {
  return (
    <>
      {many && owner && <tr className="dr-group"><th colSpan={4} scope="rowgroup">{owner}</th></tr>}
      {rows.map((r, i) => <InputLine key={`${r.name}-${i}`} r={r} />)}
    </>
  );
}
