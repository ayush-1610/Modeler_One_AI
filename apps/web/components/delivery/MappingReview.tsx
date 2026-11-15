"use client";

// A mapping, reviewed (contracts 2026-11-12 §8.10): how a table's layout is read (each header to its role, field and
// unit; the tokens that mean "below the LLOQ" or "missing"; the rules and constants), the table as the mapper was shown
// it (no digit of its body), the versions with the decisions made on them, and the three decisions: approve, reject
// with the reason, or store a corrected version. A correction is made in the layout form (`LayoutEditor`, built from
// the mapping's own `vocabulary`; the layout as text for experts) and checked by code on its table: what code finds
// wrong is shown beside the column it names, and nothing is stored. Each decision reads the files of that layout again.

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Dialog } from "@/components/kit/Dialog";
import { announce } from "@/components/kit/LiveRegion";
import { send, type Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { tableKindText, whereIs } from "@/lib/words";

import { LayoutEditor, columnsSent } from "./LayoutEditor";
import { ChipFor, MAPPING_STATE, Problem, WITHHELD, Why, fieldText, plural, useDecide, when } from "./shared";
import { writeMapping } from "./writes";

type Mapping = Schema<"DeliveryMapping">;
type Finding = Schema<"DeliveryMappingFinding">;

/** Each column's header text in the table the mapping is shown on (its header rows joined), by column number. */
function headersOf(sample: Mapping["sample"]): Record<number, string> {
  const out: Record<number, string> = {};
  for (const row of sample?.header ?? []) {
    row.forEach((text, i) => { if (text.trim()) out[i + 1] = out[i + 1] && out[i + 1] !== text ? `${out[i + 1]} / ${text}` : text; });
  }
  return out;
}

const ROUTE = "/api/v1/projects/{project_id}/delivery/mappings/{mapping_id}" as const;
const APPROVE = `${ROUTE}:approve` as const, REJECT = `${ROUTE}:reject` as const, EDIT = `${ROUTE}:edit` as const;

/** Where a constant of the table is read: a line beside the table (its caption, the lines above or below), or a cell. */
function citeText(cite: Record<string, unknown>): string {
  if ("near" in cite) return `the ${String(cite.near)}, line ${String(cite.line)}`;
  if ("row" in cite) return `the cell in row ${String(cite.row)}, column ${String(cite.column)}`;
  return Object.entries(cite).map(([k, v]) => `${k} ${String(v)}`).join(", ");
}

function Findings({ findings, testId }: { findings: Finding[]; testId: string }) {
  if (!findings.length) return null;
  return (
    <ul className="delivery-findings" data-testid={testId}>
      {findings.map((f, i) => (
        <li key={`${f.code}-${f.location}-${i}`}>
          <span className={`chip ${f.severity === "error" ? "high" : "medium"}`}>{f.severity}</span>{" "}
          <code>{f.code}</code> {f.location && <span className="muted">{f.location}: </span>}{f.message}
        </li>
      ))}
    </ul>
  );
}

function Sample({ sample }: { sample: NonNullable<Mapping["sample"]> }) {
  return (
    <section data-testid="mapping-sample">
      <h3>The table, as the mapper is shown it <span className="muted">{whereIs(sample.where).place} of {sample.file}</span></h3>
      {sample.blinded ? <p className="delivery-withheld">{WITHHELD}: the table holds a blinded study&apos;s values, so its body is not shown.</p> : (
        <>
          {sample.context.map((c) => <p key={`${c.near}-${c.line}`} className="delivery-source-line muted">{c.text}</p>)}
          <div className="delivery-source-grid" role="region" aria-label="The table with its numbers masked" tabIndex={0}>
            <table>
              <thead>{sample.header.map((row, i) => <tr key={i}><th scope="row">{i + 1}</th>{row.map((h, k) => <th key={k}>{h}</th>)}</tr>)}</thead>
              <tbody>{sample.body.map((row, i) => <tr key={i}><th scope="row">{sample.body_rows[i] ?? ""}</th>{row.map((c, k) => <td key={k}>{c}</td>)}</tr>)}</tbody>
            </table>
          </div>
          <p className="muted fs-12 m-4-0-0">Every number of the body is masked (#): the layout is reviewed, not the values.
            {" "}{sample.n_rows} rows × {sample.n_cols} columns, {plural(sample.header_rows, "header row")}.</p>
        </>
      )}
    </section>
  );
}

/** Walking through the layouts to check, one after the other (To do's queue, plan 2026-11-14 slice 4): where this one
 *  is in the queue, and moving on. `stored`: a corrected version was stored for this one (the queue shows it next). */
export type Queue = { at: number; total: number; go: (delta: number) => void; stored: (version: number) => void };

/** The mapping `mappingId` (at `version`, else its latest), in a dialog over the page. In a queue the dialog walks the
 *  layouts to check: "Approve and next", Previous and Next, and where it is ("3 of 10"). Each decision's answer is the
 *  layout, written into the cache; the page is read again (its files are read again with the decision). */
export function MappingReview({ projectId, mappingId, version, onClose, queue, returnFocus }: {
  projectId: string; mappingId: string; version?: number; onClose: () => void; queue?: Queue;
  /** where the focus goes when the dialog closes and its opener is gone (a row the decision settled) */
  returnFocus?: () => HTMLElement | null;
}) {
  const [said, setSaid] = useState<string | null>(null);
  const move = (delta: number) => { setSaid(null); queue?.go(delta); };
  // what a decision did, said in the dialog (a live region that stays while the queue moves on); once the queue has moved
  // on, as the one before ("Approved: …"), so it never reads as said of the layout now shown. The next move clears it.
  function decided(text: string, next: boolean, past: string) {
    const on = next && queue && queue.at < queue.total - 1;
    setSaid(on ? `${past}. Now ${queue!.at + 2} of ${queue!.total}.` : text);
    announce(text);
    if (on) queue!.go(1);
  }
  const shown = `${mappingId}@${version ?? "latest"}`;
  return (
    <Dialog title={queue ? `Check how tables are read · ${queue.at + 1} of ${queue.total}` : "Review how this table is read"} size="wide"
            onClose={onClose} testId="delivery-mapping-dialog" returnFocus={returnFocus} focusKey={shown}>
      <div role="status" className="mapping-said-region">
        {said && <p className="banner ok" data-testid="mapping-said">{said}</p>}
      </div>
      <MappingBody key={shown} projectId={projectId} mappingId={mappingId} version={version} onSaid={decided} queue={queue} />
      <div className="dialog-actions mapping-queue-bar">
        {queue && (
          <>
            <span className="muted" data-testid="mapping-position">{queue.at + 1} of {queue.total}</span>
            <button type="button" className="btn small" disabled={queue.at === 0} onClick={() => move(-1)} data-testid="mapping-prev">‹ Previous</button>
            <button type="button" className="btn small" disabled={queue.at >= queue.total - 1} onClick={() => move(1)} data-testid="mapping-next">Next ›</button>
          </>
        )}
        <button type="button" className="btn" onClick={onClose} data-testid="mapping-close">Close</button>
      </div>
    </Dialog>
  );
}

function MappingBody({ projectId, mappingId, version, onSaid, queue }: {
  projectId: string; mappingId: string; version?: number;
  /** a decision was made: what it did, whether the queue moves on, and what it did said of the layout before */
  onSaid: (text: string, next: boolean, past: string) => void;
  queue?: Queue;
}) {
  const params = { project_id: projectId, mapping_id: mappingId };
  const read = useResource(ROUTE, params, { poll: (d) => d.waiting, query: version !== undefined ? { version: String(version) } : undefined });
  const client = useQueryClient();
  const { decide, busy, problem } = useDecide();
  const [mode, setMode] = useState<"none" | "reject" | "edit">("none");
  const [refused, setRefused] = useState<Finding[]>([]);
  const [sent, setSent] = useState<number[]>([]);
  const m = read.data;
  const last = !queue || queue.at >= queue.total - 1;

  async function approve(note: string) {
    if (!m) return;
    const { data } = await decide(() => send("post", APPROVE, params, { version: m.version, note }), { refresh: false });
    if (!data) return;
    writeMapping(client, projectId, data);
    const again = data.queued.length ? `${plural(data.queued.length, "file")} of this layout ${data.queued.length === 1 ? "is" : "are"} read again` : "";
    onSaid(`Version ${data.version} of the ${tableKindText(data.kind)} layout is approved${again ? `: ${again}` : ""}.`, !last,
           `Approved: the ${tableKindText(data.kind)} layout, version ${data.version}${again ? ` (${again.replace("this layout", "it")})` : ""}`);
  }

  async function reject(why: string) {
    if (!m) return;
    const { data } = await decide(() => send("post", REJECT, params, { version: m.version, why }), { refresh: false });
    if (!data) return;
    writeMapping(client, projectId, data);
    setMode("none");
    onSaid(`Version ${data.version} of the ${tableKindText(data.kind)} layout is rejected: its table is read again without it.`, false, "");
  }

  async function edit(spec: Record<string, unknown>, why: string) {
    setSent(columnsSent(spec));
    // the refusal's findings come beside its message: what code found wrong on the table, each beside its column
    let found: Finding[] = [];
    const { data } = await decide(async () => {
      const env = await send("post", EDIT, params, { spec, why });
      found = (env.errors[0]?.detail?.findings as Finding[] | undefined) ?? [];
      return env;
    }, { refresh: false });
    setRefused(found);
    if (!data) return;
    writeMapping(client, projectId, data);
    setMode("none");
    onSaid(`Version ${data.version} is stored and waits for approval; its table is read again with it.`, false, "");
    queue?.stored(data.version);
  }

  return (
    <>
      {read.problem && <Problem text={read.problem} />}
      {!m && !read.problem && <p className="muted">Reading the mapping…</p>}
      {m && (
        <div className="delivery-mapping" data-testid={`delivery-mapping-view-${m.mapping_id}`}>
          <p className="muted m-0">
            <ChipFor state={m.status} table={MAPPING_STATE} testId="mapping-status" /> version {m.version} · {fieldText(m.kind)} table,{" "}
            {fieldText(m.layout)} layout · proposed by {m.origin === "llm" ? "the table mapper" : m.origin === "rule" ? "a rule" : "a person"}
            {m.origin_detail ? ` (${m.origin_detail})` : ""} · {when(m.at)}
            {m.waiting && <> · <span className="chip medium" data-testid="mapping-waiting">its files are being read again</span></>}
          </p>
          {m.not_data_reason && <p className="m-0">Read as not data: {m.not_data_reason}</p>}
          {m.questions.length > 0 && <ul className="flags">{m.questions.map((q) => <li key={q}>{q}</li>)}</ul>}

          <section>
            <h3>Each column</h3>
            <div className="table-scroll">
              <table data-testid="mapping-columns">
                <thead><tr><th className="num">Column</th><th>Header</th><th>Read as</th><th>Field</th><th>Unit</th><th>Statistic</th><th>Why</th></tr></thead>
                <tbody>
                  {m.columns.map((c) => (
                    <tr key={c.column}>
                      <td className="num">{c.column}</td><td>{c.header ?? <span className="muted">no header</span>}</td>
                      <td>{fieldText(c.role)}{c.series_role ? ` (${fieldText(c.series_role)})` : ""}{c.of !== null ? ` of column ${c.of}` : ""}</td>
                      <td>{[c.field && fieldText(c.field), c.condition && fieldText(c.condition)].filter(Boolean).join(" · ")}</td>
                      <td>{c.unit ?? ""}</td>
                      <td>{[c.statistic && fieldText(c.statistic), c.spread_kind].filter(Boolean).join(" · ")}</td>
                      <td className="muted">{c.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <dl className="delivery-facts">
              {m.field && <><dt>Field</dt><dd>{fieldText(m.field)}</dd></>}
              {m.value_unit && <><dt>Unit of the values</dt><dd>{m.value_unit}</dd></>}
              {m.time_unit && <><dt>Unit of the times</dt><dd>{m.time_unit}{m.time_row !== null ? ` (times in row ${m.time_row})` : ""}</dd></>}
              {m.statistic && <><dt>Statistic</dt><dd>{fieldText(m.statistic)}</dd></>}
              {m.time_reference && <><dt>Times counted from</dt><dd>{fieldText(m.time_reference)}</dd></>}
              <dt>Rows</dt><dd>{plural(m.header_rows, "header row")}; data from row {m.first_data_row}{m.last_data_row !== null ? ` to row ${m.last_data_row}` : ""}</dd>
              <dt>Read as below the LLOQ</dt><dd data-testid="mapping-tokens">{m.tokens.below_lloq.length ? m.tokens.below_lloq.join(", ") : "nothing"}</dd>
              <dt>Read as missing</dt><dd>{m.tokens.missing.length ? m.tokens.missing.join(", ") : "nothing"}</dd>
            </dl>
            {m.keys.length > 0 && (
              <>
                <h3>Row labels</h3>
                <ul className="plain-list">{m.keys.map((k) => (
                  <li key={k.pattern}><code>{k.pattern}</code> is {fieldText(k.field)}{k.statistic ? `, ${fieldText(k.statistic)}` : ""}{k.spread_kind ? `, ${k.spread_kind}` : ""}</li>
                ))}</ul>
              </>
            )}
            {m.rules.length > 0 && (
              <>
                <h3>Rules</h3>
                <ul className="plain-list" data-testid="mapping-rules">{m.rules.map((r, i) => (
                  <li key={i}>Column {r.column}: a cell like <code>{r.pattern}</code> is {fieldText(r.role)}{r.spread_kind ? ` (${r.spread_kind})` : ""}{r.reason ? ` · ${r.reason}` : ""}</li>
                ))}</ul>
              </>
            )}
            {m.constants.length > 0 && (
              <>
                <h3>Read once for the whole table</h3>
                <ul className="plain-list">{m.constants.map((c, i) => (
                  <li key={i}>{fieldText(c.field)}, from {citeText(c.cite)}{c.pattern ? <> by <code>{c.pattern}</code></> : null}</li>
                ))}</ul>
              </>
            )}
          </section>

          {m.sample ? <Sample sample={m.sample} /> : <p className="muted m-0">Its table is not in the source cache: read the file again to see it.</p>}

          {m.findings.length > 0 && (<section><h3>What code finds on this table</h3><Findings findings={m.findings} testId="mapping-findings" /></section>)}

          <section>
            <h3>Versions and decisions</h3>
            <ul className="plain-list" data-testid="mapping-versions">
              {m.versions.map((v) => (
                <li key={v.version}>
                  <strong>Version {v.version}</strong> <ChipFor state={v.status} table={MAPPING_STATE} />{" "}
                  <span className="muted">{v.origin}{v.origin_detail ? ` (${v.origin_detail})` : ""} · {v.by} · {when(v.at)}</span>
                  {v.decisions.map((d, i) => (
                    <div key={i} className="muted fs-12">{d.status} by {d.by}, {when(d.at)}{d.why ? `: ${d.why}` : ""}</div>
                  ))}
                </li>
              ))}
            </ul>
            {m.used_in.length > 0 && (
              <p className="muted fs-12 m-4-0-0">In use: {m.used_in.map((u) => `${whereIs(u.where).place} of ${u.file} (version ${u.version}, ${u.state})`).join("; ")}</p>
            )}
          </section>

          <Problem text={problem} testId="mapping-problem" />

          {mode === "edit" && (
            <section>
              <h3>A corrected version of the layout</h3>
              <LayoutEditor vocabulary={m.vocabulary} spec={m.spec} columns={m.sample?.n_cols ?? 0} headers={headersOf(m.sample)}
                            start={m.sample ? whereIs(m.sample.where).start : null} findings={refused} sent={sent} busy={busy}
                            action="Store this version" whyLabel="Why the layout is corrected" onSubmit={edit}
                            onCancel={() => { setMode("none"); setRefused([]); }} testId="mapping-layout" whyTestId="mapping-edit" />
            </section>
          )}
          {mode === "reject" && (
            <Why action={`Reject version ${m.version}`} label="Why the mapping is rejected" busy={busy} onSubmit={reject}
                 onCancel={() => setMode("none")} testId="mapping-reject" kind="layout rejected"
                 suggestions={["the columns are read as the wrong fields", "the table is not data"]} />
          )}
          {mode === "none" && (
            <div className="delivery-mapping-actions">
              {m.status !== "approved" && (
                <Why action={last ? `Approve version ${m.version}` : "Approve and next"} actionLabel={`Approve version ${m.version} of this layout${last ? "" : " and check the next"}`}
                     label="A note on the approval" busy={busy} onSubmit={approve} optional testId="mapping-approve" kind="layout approved"
                     suggestions={["checked against the file"]} />
              )}
              <div className="row gap-8">
                {m.status !== "rejected" && (
                  <button type="button" className="btn small" disabled={busy} onClick={() => setMode("reject")} data-testid="mapping-reject-open">Reject…</button>
                )}
                <button type="button" className="btn small" disabled={busy} data-testid="mapping-edit-open"
                        onClick={() => { setRefused([]); setMode("edit"); }}>Correct the layout…</button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}
