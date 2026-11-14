"use client";

// The spot check of a subject (contracts 2026-11-12 §8.10): the values code drew, each shown with the tuple it is ticked
// for (value, unit, time, labels, statistic) and opening its source beside it. The ticks are kept on this page until
// every value drawn has one, then sent in ONE request: a tick is accepted once. A value held as failed (its tick in an
// earlier draw said it does not match) is shown as failed and cannot be ticked: it clears when the value is corrected.
// A draw made before the values changed is stale and is drawn again; its ticks that still hold carry over.

import { Fragment, useState } from "react";

import { send, type Schema } from "@/lib/api";

import { Problem, TUPLE_HEADS, TupleCells, fieldText, num, plural, useDecide, valueText, type Subject } from "./shared";
import { ValueSource } from "./ValueSource";

type Spot = Schema<"DeliverySpotCheck">;
type SpotValue = Schema<"DeliverySpotValue">;
type Tick = { ok: boolean | null; note: string };

const DRAW = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}/spot-check:draw" as const;
const TICKS = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}/spot-check" as const;
const FAILED = "always:failed";      // the draw's reason for a value whose tick failed in an earlier draw

const REASON: Record<string, string> = {
  "always:field": "always checked: a key fact of the study",
  "always:override": "always checked: a check on it was overridden",
  "always:link": "always checked: it links two files",
  "always:cross_file": "always checked: read from another file than its study's own",
  [FAILED]: "did not match its source in an earlier spot check",
};

function reasonText(reason: string | null): string {
  if (!reason) return "";
  if (REASON[reason]) return REASON[reason];
  if (reason.startsWith("always:")) return `always checked: ${reason.slice(7).replace(/_/g, " ")}`;
  // a sampled value names the group it was sampled from ("table_kind=excretion|unit_class=other|..."): its parts, in words
  const group = reason.split("|").map((part) => part.split("=")).filter(([, x]) => x).map(([k, x]) => `${k.replace(/_/g, " ")} ${x}`);
  return `sampled from its group${group.length ? ` (${group.join(", ")})` : ""}`;
}

const STATE: Record<Subject["spot_check"]["state"], string> = {
  none: "not drawn yet",
  drawn: "drawn: tick each value against its source",
  failed: "a value does not match its source",
  complete: "complete",
  stale: "the values changed since it was drawn",
};

/** How a row that is not ticked now stands. */
function standing(v: SpotValue): { text: string; tone: string } | null {
  if (v.reason === FAILED && !v.wanted) return { text: "failed: correct the value, then draw again", tone: "high" };
  if (v.ok === false) return { text: "does not match", tone: "high" };
  if (v.ok === true) return { text: "matches", tone: "low" };
  if (v.carried_by) return { text: "matched in an earlier spot check", tone: "low" };
  return null;
}

export function SpotCheck({ projectId, subject }: { projectId: string; subject: Subject }) {
  const params = { project_id: projectId, type: subject.subject_type, subject: subject.subject };
  const { decide, busy, problem } = useDecide();
  const [drawn, setDrawn] = useState<Spot | null>(null);
  const [ticks, setTicks] = useState<Record<string, Tick>>({});
  const [source, setSource] = useState<string | null>(null);
  const card = subject.spot_check;
  // the rows are those of the subject's latest draw: an older draw kept here is not shown once the card names another
  const spot = drawn && drawn.draw?.id === card.draw_id && card.state !== "stale" ? drawn : null;
  const id = `${subject.subject_type}-${subject.subject}`;

  async function draw() {
    const { data } = await decide(() => send("post", DRAW, params));
    if (data) { setDrawn(data); setTicks({}); setSource(null); }
  }

  async function submit() {
    if (!spot?.draw) return;
    const body = { draw_id: spot.draw.id, ticks: spot.wanted.map((value_id) => ({ value_id, ok: ticks[value_id]?.ok === true, note: ticks[value_id]?.note ?? "" })) };
    const { data } = await decide(() => send("post", TICKS, params, body));
    if (data) { setDrawn(data); setTicks({}); }
  }

  const set = (valueId: string, change: Partial<Tick>) =>
    setTicks((t) => ({ ...t, [valueId]: { ...(t[valueId] ?? { ok: null, note: "" }), ...change } }));
  const wanted = spot?.wanted ?? [];
  const ticked = wanted.filter((v) => ticks[v]?.ok !== null && ticks[v]?.ok !== undefined).length;
  const wrong = wanted.filter((v) => ticks[v]?.ok === false).length;

  return (
    <section className="delivery-spot" data-testid={`delivery-spot-${subject.subject}`}>
      <div className="delivery-block-head">
        <h3>Spot check</h3>
        <span className={`chip ${card.state === "complete" ? "low" : card.state === "failed" ? "high" : "medium"}`}
              data-testid={`spot-state-${subject.subject}`}>{STATE[card.state]}</span>
        {card.drawn > 0 && <span className="muted">{plural(card.drawn, "value")} drawn{card.wanted ? `, ${card.wanted} still to tick` : ""}</span>}
      </div>
      {subject.blinded ? (
        <p className="delivery-withheld" data-testid="spot-blinded">A blinded study&apos;s values are withheld until the MAP
          is signed, so they cannot be checked against their source: its spot check is drawn after that.</p>
      ) : (
        <>
          <p className="muted m-0">Code draws the values to read against their source: the key facts always, and a sample of
            the rest. A tick says the value, its unit, its time, its labels and its statistic are as in the source.</p>
          {!spot && (
            <div className="row gap-8">
              <button type="button" className="btn small primary" disabled={busy} onClick={() => void draw()} data-testid={`spot-draw-${subject.subject}`}>
                {card.state === "none" ? "Draw the spot check" : card.state === "stale" ? "Draw again" : "Show the values drawn"}
              </button>
              {card.state === "stale" && <span className="muted" data-testid="spot-stale">The values or their overrides changed since
                the draw: draw again. Ticks of values that did not change carry over.</span>}
            </div>
          )}
          <Problem text={problem} testId="spot-problem" />
          {spot && (
            <>
              <div className="table-scroll">
                <table className="delivery-values" data-testid={`spot-values-${subject.subject}`}>
                  <caption className="sr-only">The values drawn for the spot check</caption>
                  <thead><tr><th>Field</th>{TUPLE_HEADS}<th>Why it is here</th><th>Matches its source?</th></tr></thead>
                  <tbody>
                    {spot.values.map((row) => {
                      const v = row.value, tick = ticks[v.id], stands = standing(row);
                      return (
                        <Fragment key={v.id}>
                          <tr data-testid={`spot-row-${v.id}`} className={row.ok === false || row.reason === FAILED ? "delivery-flagged" : undefined}>
                            <td>
                              {fieldText(v.field)}
                              <div>
                                {v.anchor ? (
                                  <button type="button" className="link-btn" aria-expanded={source === v.id} data-testid={`spot-source-${v.id}`}
                                          onClick={() => setSource(source === v.id ? null : v.id)}>
                                    {source === v.id ? "Hide the source" : "Show the source"}</button>
                                ) : <span className="muted fs-12">{v.method === "person" ? "entered by a person: no source" : "computed: its inputs are below"}</span>}
                              </div>
                            </td>
                            <TupleCells v={v} />
                            <td className="muted">{reasonText(row.reason)}</td>
                            <td>
                              {row.wanted ? (
                                <fieldset className="delivery-tick">
                                  <legend className="sr-only">{fieldText(v.field)} {v.id}</legend>
                                  <label><input type="radio" name={`spot-${id}-${v.id}`} checked={tick?.ok === true}
                                                onChange={() => set(v.id, { ok: true })} data-testid={`spot-tick-${v.id}`} /> matches</label>
                                  <label><input type="radio" name={`spot-${id}-${v.id}`} checked={tick?.ok === false}
                                                onChange={() => set(v.id, { ok: false })} data-testid={`spot-wrong-${v.id}`} /> does not match</label>
                                  {tick?.ok === false && (
                                    <input type="text" aria-label={`What differs for ${fieldText(v.field)}`} placeholder="what differs" value={tick.note}
                                           onChange={(e) => set(v.id, { note: e.target.value })} data-testid={`spot-note-${v.id}`} />
                                  )}
                                </fieldset>
                              ) : stands ? (
                                <span className={`chip ${stands.tone}`} data-testid={`spot-standing-${v.id}`}>{stands.text}</span>
                              ) : null}
                              {!row.wanted && row.note && <div className="muted fs-12">{row.note}</div>}
                            </td>
                          </tr>
                          {row.inputs.length > 0 && (
                            <tr className="delivery-inputs"><td colSpan={8}>
                              Computed from: {row.inputs.map((i) => `${fieldText(i.field)} ${valueText(i)}${i.unit ? ` ${i.unit}` : ""}${i.blinded || i.spread === null ? "" : ` ± ${num(i.spread)}${i.spread_kind ? ` ${i.spread_kind}` : ""}`}`).join("; ")}
                            </td></tr>
                          )}
                          {source === v.id && (
                            <tr className="delivery-source-row"><td colSpan={8}><ValueSource projectId={projectId} valueId={v.id} onClose={() => setSource(null)} /></td></tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {wanted.length > 0 ? (
                <div className="row gap-8">
                  <button type="button" className="btn small primary" disabled={busy || ticked < wanted.length} onClick={() => void submit()}
                          data-testid={`spot-submit-${subject.subject}`}>Record the spot check</button>
                  <span className="muted" data-testid={`spot-progress-${subject.subject}`} role="status">
                    {ticked} of {wanted.length} ticked{wrong ? `, ${wrong} not matching` : ""}. They are recorded together, once.</span>
                </div>
              ) : (
                <p className="muted m-0" data-testid={`spot-done-${subject.subject}`}>
                  {spot.state === "complete" ? "Every value drawn matches its source."
                    : spot.state === "failed" ? "A value does not match its source: correct it in the values below (Correct), then draw again."
                      : "Nothing is left to tick in this draw."}
                  {spot.record ? ` Recorded by ${spot.record.by}, ${spot.record.at.slice(0, 16).replace("T", " ")}.` : ""}
                </p>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
