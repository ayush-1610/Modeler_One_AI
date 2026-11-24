"use client";

// The Data room's "Requirements for this question" (plan 2026-11-24 §6, phase 2): the checklist of what the question
// needs, from the requirement drafts per context of use. They are drafts, UNVERIFIED, awaiting the owner's and the SME's
// review, and the page says so first. Then the applications in force (as read from the question card until a person
// chooses them in Decisions); every item grouped by its status, each with its coverage line (found where, missing with
// the files searched, applies if …, for a person to check) and its source chips; "Not needed for this question" and
// "Context only" folded; what code read about the compound and the question. The engine builds the ledger; the page
// lays it out and computes nothing.

import type { ReactNode } from "react";

import type { RequirementItem, Room } from "@/lib/dataroom";

import { Card, Nothing, Row, Sources, Table, usePaper } from "./kit";

/** A coverage as a tag: its tone and its word (a word as well as a colour, never colour alone). */
const COVERAGE: Record<RequirementItem["coverage"], [string, string]> = {
  found: ["ok", "Found"], found_in_part: ["warn", "Found in part"], missing: ["bad", "Missing"], to_ask: ["warn", "To ask"],
  absent: ["quiet", "Not in the delivery"], person_checks: ["warn", "A person checks"],
  not_from_delivery: ["info", "Not from the delivery"], not_needed: ["quiet", "Not needed"], context: ["quiet", "Context"],
};

const GROUPS: { id: string; title: string; levels: RequirementItem["level"][]; note: string }[] = [
  { id: "required", title: "Required", levels: ["required"], note: "missing when the delivery does not hold it" },
  { id: "usually", title: "Usually needed", levels: ["usually_needed"], note: "required when the model carries high weight" },
  { id: "conditional", title: "Conditional", levels: ["conditional", "to_ask"], note: "required when its condition holds" },
  { id: "optional", title: "Optional", levels: ["optional"], note: "supportive; never missing" },
];

const sentence = (text: string) => `${text[0]?.toUpperCase() ?? ""}${text.slice(1)}${/[.!?)]$/.test(text) ? "" : "."}`;

function Item({ i }: { i: RequirementItem }) {
  const paper = usePaper();
  const [tone, word] = COVERAGE[i.coverage];
  const conditional = i.level === "conditional" || i.level === "to_ask" || (i.status === "CONDITIONAL" && i.applies === "no");
  return (
    <li className="dr-req" data-testid={`requirement-${i.id}`} data-coverage={i.coverage}>
      <div className="dr-req-head">
        <span className="dr-req-label">{i.label}</span>
        <span className={`dr-tag ${tone} small`}>{word}</span>
        {i.level === "usually_needed" && i.coverage === "missing" && <span className="dr-tag warn small">Usually needed</span>}
        {i.request && <span className="dr-code" title="The data request that asks for it">{i.request}</span>}
      </div>
      <p className="dr-req-line">
        <span>{sentence(i.coverage_text)}</span>
        {i.chips.length > 0 && <Sources chips={i.chips} max={3} />}
      </p>
      {conditional && i.trigger && <p className="dr-req-sub">Condition: {i.trigger}{i.trigger_state ? ` (${i.trigger_state})` : ""}</p>}
      {i.escalates && <p className="dr-req-sub">Required when: {i.escalates}</p>}
      <details className="dr-fold dr-req-more" open={paper || undefined}>
        <summary>Why, and the literature</summary>
        <dl className="dr-facts">
          <div className="wide"><dt>Why</dt><dd>{i.why}</dd></div>
          {i.alternatives.length > 0 && <div className="wide"><dt>If it is not available</dt><dd>{i.alternatives.join("; ")}</dd></div>}
          {i.record_with.length > 0 && <div className="wide"><dt>Recorded with</dt><dd>{i.record_with.join("; ")}</dd></div>}
          <div className="wide"><dt>Set by</dt><dd>{i.by.join(", ")}{i.others.length > 0 ? ` · also ${i.others.join("; ")}` : ""}</dd></div>
          <div className="wide"><dt>Literature</dt><dd>{i.sources.join("; ")}</dd></div>
          <div className="wide"><dt>Draft item</dt><dd><code>{i.id}</code> · {i.note}</dd></div>
        </dl>
      </details>
    </li>
  );
}

function Folded({ title, items, note, testId }: { title: string; items: RequirementItem[]; note: string; testId: string }): ReactNode {
  const paper = usePaper();
  if (!items.length) return null;
  return (
    <Card testId={testId}>
      <details className="dr-fold" open={paper || undefined}>
        <summary>{title} ({items.length})</summary>
        <p className="dr-note">{note}</p>
        <ul className="dr-reqs">{items.map((i) => <Item key={i.id} i={i} />)}</ul>
      </details>
    </Card>
  );
}

export function Requirements({ room, go }: { room: Room; go: (section: string) => void }) {
  const paper = usePaper();
  const req = room.requirements;
  if (!req) return <Nothing>No question card yet: the checklist follows the question. Set or confirm it on the Overview.</Nothing>;
  const notNeeded = req.items.filter((i) => i.level === "not_needed");
  const context = req.items.filter((i) => i.level === "context");
  const apps = req.applications.length ? req.applications.join(" + ") : "None of these: the core items only";
  return (
    <div className="dr-stack" data-testid="dr-requirements">
      <p className="dr-draft" role="note" data-testid="requirements-draft">
        <strong>Requirements: {req.label}.</strong> Drafted from the literature for each context of use; the Data room
        shows them and asks for what they name, marked so. No data plan, gate or template reads them.
      </p>
      <Card title="What the question is for" testId="requirements-applications"
            aside={req.chosen ? <span className="dr-tag ok">Chosen</span> : <span className="dr-tag warn">As read from the question card</span>}>
        <p className="dr-lede">{apps}</p>
        {req.read.length > 0 && (
          <ul className="dr-list">
            {req.read.map((r) => (
              <li key={r.application}><strong>{r.label}</strong><span className="muted dr-small">read from {r.words.join(", ")}</span></li>
            ))}
          </ul>
        )}
        {!paper && (
          <button type="button" className="dr-link" onClick={() => go("decisions")} data-testid="requirements-choose">
            {req.chosen ? "Change the applications in Decisions" : "Confirm the applications in Decisions"}
          </button>
        )}
      </Card>
      {GROUPS.map((g) => {
        const list = req.items.filter((i) => g.levels.includes(i.level));
        if (!list.length) return null;
        const missing = list.filter((i) => i.coverage === "missing").length;
        return (
          <Card key={g.id} title={`${g.title} (${list.length})`} testId={`requirements-${g.id}`}
                aside={<span className="muted dr-small">{missing ? `${missing} missing · ` : ""}{g.note}</span>}>
            <ul className="dr-reqs">{list.map((i) => <Item key={i.id} i={i} />)}</ul>
          </Card>
        );
      })}
      <Folded title="Not needed for this question" items={notNeeded} testId="requirements-not-needed"
              note="Not needed for these applications, or their condition does not hold: never shown as missing, never asked for." />
      <Folded title="Context only" items={context} testId="requirements-context"
              note="Kept as context when a delivery holds it: never a model input, never missing, never asked for." />
      {req.properties.length > 0 && (
        <Card title="What code read about the compound and the question" testId="requirements-properties"
              aside={<span className="muted dr-small">the conditions above are decided from these; a cut-off the SME sets is never invented</span>}>
          <Table head={["Property", "Value", "How", "Basis"]} label="The properties the conditions name">
            {req.properties.map((p) => (
              <Row key={p.name} testId={`property-${p.name}`} cells={[
                <span key="n">{p.label}</span>,
                <span key="v" className={p.known ? "dr-value" : "muted"}>{p.value}</span>,
                <span key="h" className="muted">{p.how === "code" ? "read by code" : p.how === "brief" ? "as stated" : "a person answers"}</span>,
                <span key="b" className="dr-req-line"><span>{p.basis}</span>{p.sources.length > 0 && <Sources chips={p.sources} max={2} />}</span>,
              ]} />
            ))}
          </Table>
        </Card>
      )}
      <p className="dr-note">{req.version}</p>
    </div>
  );
}
