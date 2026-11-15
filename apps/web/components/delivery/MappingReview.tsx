"use client";

// A mapping, reviewed (contracts 2026-11-12 §8.10): how a table's layout is read (each header to what it holds, its field
// and unit; the cells that mean "below the LLOQ" or "missing"; the row rules and the facts read once for the table), a
// table of the layout with no digit of its body, how each version reads each table of the layout, the versions with the
// decisions made on them, and the three decisions: approve, reject with the reason, or store a corrected version. A
// correction is made in the layout form (`LayoutEditor`, built from the mapping's own `vocabulary`; the layout as text
// for experts) and checked by code on the table shown: what code finds wrong is shown beside the column it names, and
// nothing is stored. Each decision reads the files of that layout again.
//
// Final review (OWN-2, OWN-8, OWN-15, A11Y-2): the dialog opens at the version and on the table the row it was opened
// from names (`at`: its file and region); every table the layout reads says the version it is read with, whether the
// version shown reads it, and why the newest approved version does not, with "Correct the layout for this table…"; the
// layout is said in words (rule ids, patterns and codes in a "technical detail" fold); the table's header rows are the
// layout's, and the rows the sample leaves out are named; "Reject…" and "Correct the layout…" move the focus into their
// form, and Cancel puts it back on the button that opened it.

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Dialog } from "@/components/kit/Dialog";
import { send, type Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import {
  constantText, factsInText, findingsInline, layoutFieldText, layoutFindingText, layoutMadeBy, layoutRoleText, moveText, patternWords, placeText, rowRuleText, rowsLeftOut,
  tableKindText, valueWord, whenText, whereIs,
} from "@/lib/words";

import { LayoutEditor, columnsSent } from "./LayoutEditor";
import { ChipFor, MAPPING_STATE, Problem, WITHHELD, Why, plural, useDecide } from "./shared";
import { readReading, writeMapping } from "./writes";

type Mapping = Schema<"DeliveryMapping">;
type Finding = Schema<"DeliveryMappingFinding">;
type Table = Schema<"DeliveryMappingTable">;

/** The table a layout is shown on: a file and its region, as the row the dialog was opened from names them. */
export type MappingAt = { file_sha256: string; region_id: string };
/** What opens the layout dialog: the layout, the version the row names (else its latest) and the row's table. */
export type MappingOpen = { id: string; version?: number; at?: MappingAt };

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
/** When a table's times are counted from (`MappingSpec.time_reference`), in words. */
const TIME_FROM: Record<string, string> = { first_dose: "the first dose", last_dose: "the last dose", occasion_dose: "each occasion's dose" };
/** What a layout is (`MappingSpec.layout`), in words. */
const LAYOUT_WORD: Record<string, string> = {
  long: "one row per value", wide_series: "times down a column, one column per series",
  wide_times: "times across the header, one row per series", key_value: "a label column says what each row is",
};
const sameTable = (a: { file_sha256: string; region_id: string } | null | undefined, b: { file_sha256: string; region_id: string } | null | undefined) =>
  Boolean(a && b && a.file_sha256 === b.file_sha256 && a.region_id === b.region_id);

function Findings({ findings, constants, testId }: { findings: Finding[]; constants: Mapping["constants"]; testId: string }) {
  if (!findings.length) return null;
  return (
    <ul className="delivery-findings" data-testid={testId}>
      {findings.map((f, i) => (
        <li key={`${f.code}-${f.location}-${i}`}>
          <span className={`chip ${f.severity === "error" ? "high" : "medium"}`}>{f.severity === "error" ? "to fix" : "note"}</span>{" "}
          {layoutFindingText(f, constants)}
        </li>
      ))}
    </ul>
  );
}

/** The table, its numbers masked: the context lines, the header rows as the layout counts them, the body rows shown,
 *  and the rows the sample leaves out, named (review OWN-15). */
function Sample({ sample }: { sample: NonNullable<Mapping["sample"]> }) {
  const left = rowsLeftOut(sample.header_rows + 1, sample.n_rows, sample.body_rows);
  return (
    <section data-testid="mapping-sample">
      <h3>The table, its numbers masked <span className="muted">{whereIs(sample.where).place} of {sample.file}</span></h3>
      {sample.blinded ? <p className="delivery-withheld">{WITHHELD}: the table holds a blinded study&apos;s values, so its body is not shown.</p> : (
        <>
          {sample.context.map((c) => <p key={`${c.near}-${c.line}`} className="delivery-source-line muted">{c.text}</p>)}
          <div className="delivery-source-grid" role="region" aria-label="The table with its numbers masked" tabIndex={0}>
            <table>
              <thead>{sample.header.map((row, i) => <tr key={i}><th scope="row">{i + 1}</th>{row.map((h, k) => <th key={k}>{h}</th>)}</tr>)}</thead>
              <tbody>{sample.body.map((row, i) => <tr key={i}><th scope="row">{sample.body_rows[i] ?? ""}</th>{row.map((c, k) => <td key={k}>{c}</td>)}</tr>)}</tbody>
            </table>
          </div>
          <p className="muted fs-12 m-4-0-0" data-testid="mapping-sample-said">Every number of the body is masked (#): the layout is reviewed, not the values.
            {" "}{sample.n_rows} rows × {sample.n_cols} columns, {plural(sample.header_rows, "header row")} as the layout says.
            {left ? ` ${left}: the sample shows the first 5 and the last 3 rows of the body.` : ""}</p>
        </>
      )}
    </section>
  );
}

/** Walking through the layouts to check, one after the other (To do's queue, plan 2026-11-14 slice 4): where this one
 *  is in the queue, and moving on. */
export type Queue = { at: number; total: number; go: (delta: number) => void };

/** The mapping `mappingId` (at `version`, else its latest), on the table `at` (else one where it is in use), in a dialog
 *  over the page. In a queue the dialog walks the layouts to check: "Approve and next", Previous and Next, and where it
 *  is ("3 of 10"). Each decision's answer is the layout, written into the cache; the page is read again (its files are
 *  read again with the decision). The dialog stays until the person closes it. */
export function MappingReview({ projectId, mappingId, version, at, onClose, queue, returnFocus, onStored }: {
  projectId: string; mappingId: string; version?: number; at?: MappingAt; onClose: () => void; queue?: Queue;
  /** a corrected version was stored: the dialog shows it next (its caller moves `version` to it) */
  onStored?: (version: number) => void;
  /** where the focus goes when the dialog closes and its opener is gone (a row the decision settled) */
  returnFocus?: () => HTMLElement | null;
}) {
  const [said, setSaid] = useState<string | null>(null);
  // another table of the layout chosen in the dialog ("Correct the layout for this table…"), for this layout and version
  const here = `${mappingId}@${version ?? "latest"}`;
  const [chosen, setChosen] = useState<{ key: string; at: MappingAt; edit: boolean } | null>(null);
  const table = chosen?.key === here ? chosen.at : at;
  const move = (delta: number) => { setSaid(null); queue?.go(delta); };
  // what a decision did, said in the dialog (a live region that stays while the queue moves on); once the queue has moved
  // on, as the one before ("Approved: …"), so it never reads as said of the layout now shown. The next move clears it.
  // Said there only: the page's live region under the dialog would say it a second time (final review A11Y-6)
  function decided(text: string, next: boolean, past: string) {
    const on = next && queue && queue.at < queue.total - 1;
    setSaid(on ? `${past}. Now ${queue!.at + 2} of ${queue!.total}.` : text);
    if (on) queue!.go(1);
  }
  const shown = `${here}@${table ? `${table.file_sha256}/${table.region_id}` : "any"}`;
  return (
    <Dialog title={queue ? `Check how tables are read · ${queue.at + 1} of ${queue.total}` : "Review how this table is read"} size="wide"
            onClose={onClose} testId="delivery-mapping-dialog" returnFocus={returnFocus} focusKey={shown}>
      <div role="status" className="mapping-said-region">
        {said && <p className="banner ok" data-testid="mapping-said">{said}</p>}
      </div>
      <MappingBody key={shown} projectId={projectId} mappingId={mappingId} version={version} at={table} onSaid={decided} queue={queue}
                   startEdit={chosen?.key === here && chosen.edit} onStored={onStored}
                   onTable={(t, edit) => setChosen({ key: here, at: t, edit })} />
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

/** How the version shown reads one table of the layout, and why a newer approved version does not (review OWN-2 a). */
function tableWords(t: Table, m: Mapping): string[] {
  const out = [t.version === m.version ? "Read with this version." : `Read with version ${t.version}.`];
  if (t.reads === false) {
    out.push(`This version does not read it: ${findingsInline(t.findings, m.constants)}.`);
  }
  if (t.newer) {
    out.push(`Version ${t.newer.version}, the newest approved, does not read it (${findingsInline(t.newer.findings, t.newer.constants)}), so it is still`
      + ` read with version ${t.version}.`);
  }
  if (t.reads === null) out.push("Its file is not in the source cache: read the file again to check it.");
  // a version waiting for approval that the pipeline would then read this table with (final review round 3)
  if (t.moves) out.push(moveText(t.moves, m.version));
  return out;
}

function MappingBody({ projectId, mappingId, version, at, onSaid, queue, startEdit, onTable, onStored }: {
  projectId: string; mappingId: string; version?: number; at?: MappingAt; onStored?: (version: number) => void;
  /** a decision was made: what it did, whether the queue moves on, and what it did said of the layout before */
  onSaid: (text: string, next: boolean, past: string) => void;
  queue?: Queue;
  /** open on the layout form (the person chose to correct the layout for this table) */
  startEdit?: boolean;
  /** show the layout on another of its tables, and open the layout form there */
  onTable: (at: MappingAt, edit: boolean) => void;
}) {
  const params = { project_id: projectId, mapping_id: mappingId };
  const query = { ...(version !== undefined ? { version: String(version) } : {}), ...(at ? { file_sha256: at.file_sha256, region_id: at.region_id } : {}) };
  const read = useResource(ROUTE, params, { poll: (d) => d.waiting, query: Object.keys(query).length ? query : undefined });
  const client = useQueryClient();
  const { decide, busy, problem } = useDecide();
  const [mode, setMode] = useState<"none" | "reject" | "edit">(startEdit ? "edit" : "none");
  const [refused, setRefused] = useState<Finding[]>([]);
  const [sent, setSent] = useState<number[]>([]);
  const rejectButton = useRef<HTMLButtonElement>(null);
  const editButton = useRef<HTMLButtonElement>(null);
  const editHead = useRef<HTMLHeadingElement>(null);
  const was = useRef(mode);
  const m = read.data;
  const last = !queue || queue.at >= queue.total - 1;
  // the table the answer is shown on: the one this dialog shows (a decision's answer keeps it)
  const shownAt = m?.sample ? { file_sha256: m.sample.file_sha256, region_id: m.sample.region_id } : at;

  // the layout's files are read again after a decision (its answer waits, and is read every few seconds until they are):
  // once they are, the delivery page and the cards are read again, so a table's row in To do and a card follow the
  // reading by the layout's own word, not only by the page's "reading" flag (final review round 3)
  const waiting = m?.waiting ?? false;
  const wasWaiting = useRef(false);
  useEffect(() => {
    if (waiting) wasWaiting.current = true;
    else if (wasWaiting.current) {
      wasWaiting.current = false;
      readReading(client, projectId);
    }
  }, [waiting]); // eslint-disable-line react-hooks/exhaustive-deps

  // the focus follows the form (review A11Y-2): into the layout form's heading when it opens, back to the button that
  // opened a form when it is cancelled (the reject form's reason takes it by itself: autoFocus)
  useEffect(() => {
    const before = was.current;
    was.current = mode;
    if (mode === "edit" && m) editHead.current?.focus();
    else if (mode === "none" && before === "reject") rejectButton.current?.focus();
    else if (mode === "none" && before === "edit") editButton.current?.focus();
    // (on a change of form or when the layout first arrives, never on each poll of it: the focus stays where the person types)
  }, [mode, m !== null]); // eslint-disable-line react-hooks/exhaustive-deps

  async function approve(note: string): Promise<boolean> {
    if (!m) return false;
    const { data } = await decide(() => send("post", APPROVE, params, { version: m.version, note, ...(shownAt ?? {}) }), {});
    if (!data) return false;
    writeMapping(client, projectId, data);
    const again = data.queued.length ? `${plural(data.queued.length, "file")} of this layout ${data.queued.length === 1 ? "is" : "are"} read again` : "";
    // a table this version does not read stays with the version it is read with: said, not left to be found later; and
    // another table its approval moved to it, with what it no longer reads (as the dialog said before the approval)
    const stays = data.tables.filter((t) => t.reads === false).map((t) => `${t.file} stays with version ${t.version}: this version does not read it`);
    const moved = m.tables.filter((t) => t.moves && !sameTable(t, shownAt)).map((t) => `${t.file} moves to it`
      + (t.moves!.facts_lost.length ? ` and no longer reads ${factsInText(t.moves!.facts_lost)}` : ""));
    const more = [...moved, ...stays].length ? ` ${[...moved, ...stays].join("; ")}.` : "";
    onSaid(`Version ${data.version} of the ${tableKindText(data.kind)} layout is approved${again ? `: ${again}` : ""}.${more}`, !last,
           `Approved: the ${tableKindText(data.kind)} layout, version ${data.version}${again ? ` (${again.replace("this layout", "it")})` : ""}${more ? `.${more.replace(/\.$/, "")}` : ""}`);
    return true;
  }

  async function reject(why: string): Promise<boolean> {
    if (!m) return false;
    const { data } = await decide(() => send("post", REJECT, params, { version: m.version, why, ...(shownAt ?? {}) }), {});
    if (!data) return false;
    writeMapping(client, projectId, data);
    setMode("none");
    onSaid(`Version ${data.version} of the ${tableKindText(data.kind)} layout is rejected: its table is read again without it.`, false, "");
    return true;
  }

  async function edit(spec: Record<string, unknown>, why: string): Promise<boolean> {
    setSent(columnsSent(spec));
    // the refusal's findings come beside its message: what code found wrong on the table, each beside its column
    let found: Finding[] = [];
    const { data } = await decide(async () => {
      const env = await send("post", EDIT, params, { spec, why, ...(shownAt ?? {}) });
      found = (env.errors[0]?.detail?.findings as Finding[] | undefined) ?? [];
      return env;
    }, {});
    setRefused(found);
    if (!data) return false;
    writeMapping(client, projectId, data);
    setMode("none");
    const others = data.tables.filter((t) => !sameTable(t, shownAt) && t.reads === false).length;
    onSaid(`Version ${data.version} is stored and waits for approval; its table is read again with it.`
      + `${others ? ` It does not read ${plural(others, "other table")} of this layout: ${others === 1 ? "that one keeps" : "those keep"} the version ${others === 1 ? "it is" : "they are"} read with.` : ""}`, false, "");
    onStored?.(data.version);
    return true;
  }

  return (
    <>
      {read.problem && <Problem text={read.problem} />}
      {!m && !read.problem && <p className="muted">Reading the layout…</p>}
      {m && (
        <div className="delivery-mapping" data-testid={`delivery-mapping-view-${m.mapping_id}`}>
          <p className="muted m-0">
            <ChipFor state={m.status} table={MAPPING_STATE} testId="mapping-status" /> <span data-testid="mapping-version">version {m.version}</span>
            {" "}· {tableKindText(m.kind)}, {LAYOUT_WORD[m.layout] ?? m.layout.replace(/_/g, " ")} · {layoutMadeBy(m.origin, m.by, m.origin === "person" ? m.origin_detail : "")}
            {" "}· {whenText(m.at)}
            {m.waiting && <> · <span className="chip medium" data-testid="mapping-waiting">its files are being read again</span></>}
          </p>
          {m.not_data_reason && <p className="m-0">Read as not data: {m.not_data_reason}</p>}
          {m.questions.length > 0 && <ul className="flags">{m.questions.map((q) => <li key={q}>{q}</li>)}</ul>}

          <section>
            <h3>Each column</h3>
            <div className="table-scroll">
              <table data-testid="mapping-columns">
                <thead><tr><th className="num">Column</th><th>Header</th><th>Holds</th><th>Field</th><th>Unit</th><th>Statistic</th><th>Why</th></tr></thead>
                <tbody>
                  {m.columns.map((c) => (
                    <tr key={c.column}>
                      <td className="num">{c.column}</td><td>{c.header ?? <span className="muted">no header</span>}</td>
                      <td>{layoutRoleText(c.role)}{c.series_role ? ` (${layoutRoleText(c.series_role)})` : ""}{c.of !== null ? ` of column ${c.of}` : ""}</td>
                      <td>{[c.field && layoutFieldText(c.field), c.condition && layoutFieldText(c.condition)].filter(Boolean).join(" · ")}</td>
                      <td>{c.unit ?? ""}</td>
                      <td>{[c.statistic && valueWord(c.statistic), c.spread_kind].filter(Boolean).join(" · ")}</td>
                      <td className="muted">{c.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <dl className="delivery-facts">
              {m.field && <><dt>Field of the values</dt><dd>{layoutFieldText(m.field)}</dd></>}
              {m.value_unit && <><dt>Unit of the values</dt><dd>{m.value_unit}</dd></>}
              {m.time_unit && <><dt>Unit of the times</dt><dd>{m.time_unit}{m.time_row !== null ? ` (times in row ${m.time_row})` : ""}</dd></>}
              {m.statistic && <><dt>Statistic</dt><dd>{valueWord(m.statistic)}</dd></>}
              {m.time_reference && <><dt>Times counted from</dt><dd>{TIME_FROM[m.time_reference] ?? m.time_reference.replace(/_/g, " ")}</dd></>}
              <dt>Rows</dt><dd>{plural(m.header_rows, "header row")}; data from row {m.first_data_row}{m.last_data_row !== null ? ` to row ${m.last_data_row}` : ""}</dd>
              <dt>Read as below the LLOQ</dt><dd data-testid="mapping-tokens">{m.tokens.below_lloq.length ? m.tokens.below_lloq.join(", ") : "nothing"}</dd>
              <dt>Read as missing</dt><dd>{m.tokens.missing.length ? m.tokens.missing.join(", ") : "nothing"}</dd>
            </dl>
            {m.keys.length > 0 && (
              <>
                <h3>Row labels</h3>
                <ul className="plain-list">{m.keys.map((k) => {
                  const words = patternWords(k.pattern);
                  return (
                    <li key={k.pattern}>{words !== null ? `A row labelled “${words}”` : "A row whose label matches a pattern (technical detail)"} holds {layoutFieldText(k.field)}
                      {k.statistic ? `, ${valueWord(k.statistic)}` : ""}{k.spread_kind ? `, ${k.spread_kind}` : ""}.</li>
                  );
                })}</ul>
              </>
            )}
            {m.rules.length > 0 && (
              <>
                <h3>Rows told apart by a cell</h3>
                <ul className="plain-list" data-testid="mapping-rules">{m.rules.map((r, i) => (
                  <li key={i}>{rowRuleText(r, patternWords(r.pattern))}{r.spread_kind ? ` (${r.spread_kind})` : ""}</li>
                ))}</ul>
              </>
            )}
            {m.constants.length > 0 && (
              <>
                <h3>Read once for the whole table</h3>
                <ul className="plain-list" data-testid="mapping-constants">{m.constants.map((c, i) => <li key={i}>{constantText(c)}</li>)}</ul>
              </>
            )}
            <Technical m={m} />
          </section>

          {m.sample ? <Sample sample={m.sample} /> : <p className="muted m-0">Its table is not in the source cache: read the file again to see it.</p>}

          {m.findings.length > 0 && (
            <section><h3>What code finds on this table</h3><Findings findings={m.findings} constants={m.constants} testId="mapping-findings" /></section>
          )}

          {m.tables.length > 0 && (
            <section data-testid="mapping-tables">
              <h3>The tables of this layout</h3>
              <ul className="plain-list">
                {m.tables.map((t) => {
                  const here = sameTable(t, shownAt);
                  const fix = t.reads === false || Boolean(t.newer);
                  return (
                    <li key={`${t.file_sha256}/${t.region_id}`} data-testid={`mapping-table-${t.region_id}`}>
                      <strong>{t.file}</strong> <span className="muted">{placeText(t.where)}{here ? " (shown here)" : ""}</span>{" "}
                      {tableWords(t, m).join(" ")}
                      {(fix || !here) && mode === "none" && (
                        <span className="row gap-8">
                          {!here && (
                            <button type="button" className="link-btn" onClick={() => onTable({ file_sha256: t.file_sha256, region_id: t.region_id }, false)}
                                    data-testid={`mapping-table-show-${t.region_id}`} aria-label={`Show the layout on ${t.file}`}>Show it here</button>
                          )}
                          {fix && (
                            <button type="button" className="link-btn" data-testid={`mapping-table-fix-${t.region_id}`}
                                    aria-label={`Correct the layout for the table of ${t.file}`}
                                    onClick={() => (here ? (setRefused([]), setMode("edit")) : onTable({ file_sha256: t.file_sha256, region_id: t.region_id }, true))}>
                              Correct the layout for this table…</button>
                          )}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          <section>
            <h3>Versions and decisions</h3>
            <ul className="plain-list" data-testid="mapping-versions">
              {m.versions.map((v) => (
                <li key={v.version}>
                  <strong>Version {v.version}</strong> <ChipFor state={v.status} table={MAPPING_STATE} />{" "}
                  <span className="muted">{layoutMadeBy(v.origin, v.by, v.origin === "person" ? v.origin_detail : "")} · {whenText(v.at)}</span>
                  {v.decisions.map((d, i) => (
                    <div key={i} className="muted fs-12">{d.status} by {d.by}, {whenText(d.at)}{d.why ? `: ${d.why}` : ""}</div>
                  ))}
                </li>
              ))}
            </ul>
          </section>

          <Problem text={problem} testId="mapping-problem" />

          {mode === "edit" && (
            <section>
              <h3 ref={editHead} tabIndex={-1} data-testid="mapping-edit-title">A corrected version of the layout
                {m.sample ? <span className="muted">, checked on {whereIs(m.sample.where).place} of {m.sample.file}</span> : null}</h3>
              <LayoutEditor vocabulary={m.vocabulary} spec={m.spec} columns={m.sample?.n_cols ?? 0} headers={headersOf(m.sample)}
                            start={m.sample ? whereIs(m.sample.where).start : null} findings={refused} sent={sent} busy={busy}
                            action="Store this version" whyLabel="Why the layout is corrected" onSubmit={edit}
                            onCancel={() => { setMode("none"); setRefused([]); }} testId="mapping-layout" whyTestId="mapping-edit" />
            </section>
          )}
          {mode === "reject" && (
            <Why action={`Reject version ${m.version}`} label="Why the layout is rejected" busy={busy} onSubmit={reject} autoFocus
                 onCancel={() => setMode("none")} testId="mapping-reject" kind="layout rejected"
                 suggestions={["the columns are read as the wrong fields", "the table is not data"]} />
          )}
          {mode === "none" && (
            <div className="delivery-mapping-actions">
              {/* what the approval changes for the layout's other tables, said before it is made (final review round 3:
                  the pipeline reads each table with the approved version that leaves the fewest numbers unread) */}
              {m.status === "proposed" && m.tables.some((t) => t.moves && !sameTable(t, shownAt)) && (
                <div className="inline-issue warn" data-testid="mapping-approve-moves">
                  <p className="m-0">Approving version {m.version} also changes how {plural(m.tables.filter((t) => t.moves && !sameTable(t, shownAt)).length, "other table")} of
                    this layout {m.tables.filter((t) => t.moves && !sameTable(t, shownAt)).length === 1 ? "is" : "are"} read:</p>
                  <ul className="plain-list">
                    {m.tables.filter((t) => t.moves && !sameTable(t, shownAt)).map((t) => (
                      <li key={`${t.file_sha256}/${t.region_id}`} data-testid={`mapping-move-${t.region_id}`}>
                        <strong>{t.file}</strong> <span className="muted">{placeText(t.where)}</span>: {moveText(t.moves!, m.version)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {m.status !== "approved" && (
                <Why action={last ? `Approve version ${m.version}` : "Approve and next"} actionLabel={`Approve version ${m.version} of this layout${last ? "" : " and check the next"}`}
                     label="A note on the approval" busy={busy} onSubmit={approve} optional testId="mapping-approve" kind="layout approved"
                     suggestions={["checked against the file"]} />
              )}
              <div className="row gap-8">
                {m.status !== "rejected" && (
                  <button ref={rejectButton} type="button" className="btn small" disabled={busy} onClick={() => setMode("reject")}
                          data-testid="mapping-reject-open">Reject…</button>
                )}
                <button ref={editButton} type="button" className="btn small" disabled={busy} data-testid="mapping-edit-open"
                        onClick={() => { setRefused([]); setMode("edit"); }}>Correct the layout…</button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}

/** What the words above leave out, for whoever needs it: who or what proposed the layout (a rule's id), the patterns
 *  the rows, labels and facts are matched with, and each finding's code and place in the layout (review OWN-8). */
function Technical({ m }: { m: Mapping }) {
  const patterns = [
    ...m.rules.map((r) => `row rule, column ${r.column}: ${r.pattern}`),
    ...m.keys.map((k) => `row label → ${k.field}: ${k.pattern}`),
    ...m.constants.filter((c) => c.pattern).map((c) => `${c.field}: ${c.pattern}`),
  ];
  const findings = [...m.findings, ...m.tables.flatMap((t) => [...t.findings, ...(t.newer?.findings ?? [])])];
  if (!m.origin_detail && !patterns.length && !findings.length) return null;
  return (
    <details className="mapping-technical" data-testid="mapping-technical">
      <summary>Technical detail</summary>
      <ul className="plain-list muted fs-12">
        <li>Layout {m.mapping_id}, version {m.version}: {m.origin}{m.origin_detail ? ` (${m.origin_detail})` : ""}</li>
        {patterns.map((p) => <li key={p}><code>{p}</code></li>)}
        {[...new Map(findings.map((f) => [`${f.code}|${f.location}|${f.message}`, f])).values()].map((f) => (
          <li key={`${f.code}|${f.location}|${f.message}`}><code>{f.code}</code> {f.location}: {f.message}</li>
        ))}
      </ul>
    </details>
  );
}
