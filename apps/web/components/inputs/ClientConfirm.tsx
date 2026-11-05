"use client";

// The client's data, confirmed inline where it lands (docs/plans/2026-11-03-inputs-and-client-data.md §3.3; the owner,
// 2026-11-03): a study on Clinical studies, a product on Products and dissolution, a file's values on Compound. A group
// waits, "to confirm", until a person confirms it, and only then loads into the project. A conflict or a question sits
// on the card it concerns and blocks the confirmation until settled: the person selects an option and confirms the
// selection, with no reason asked. A settled one stays in place with its final value and its alternatives, and can be
// changed until the group is confirmed. Every value opens its source in the centre peek.

import { useState } from "react";

import { PeekButton, type PeekSource } from "@/components/kit/SourcePeek";
import { send, type Schema } from "@/lib/api";

import { LABEL, type Run } from "./InputsTodo";

type Group = Schema<"ReviewGroup">;
type Issue = Schema<"ReviewIssue">;
type Option = Schema<"ReviewOption">;

const KIND: Record<Issue["kind"], [string, string]> = {
  conflict: ["Conflict", "conflict"], difference: ["Differs", "difference"], question: ["Question", "question"],
  link: ["Same study?", "question"],
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function src(s: Record<string, unknown> | null | undefined): PeekSource | null {
  return s ? (s as PeekSource) : null;
}

function itemLabel(label: string, target?: string | null) {
  return LABEL[target ?? label] ?? label;
}

function IssueCard({ projectId, group, issue, run }: { projectId: string; group: Group; issue: Issue; run: Run }) {
  const [option, setOption] = useState<string>("");   // nothing preselected: the person chooses
  const [answer, setAnswer] = useState("");
  const [kind, tone] = KIND[issue.kind];
  const settled = issue.selected !== null || issue.answered !== null;
  const confirmed = group.state === "confirmed";
  const chosen = issue.options.find((o) => o.id === issue.selected);
  const params = { project_id: projectId };

  if (settled) {
    // "explained" or "different things": every file keeps its own value, so none is set aside
    const keepsEach = chosen !== undefined && chosen.value === null;
    const others = issue.options.filter((o) => o.id !== issue.selected && o.value !== null);
    return (
      <section className="issue settled" aria-label={`${kind}: ${issue.text}`} data-testid={`issue-${issue.id}`}>
        <div className="issue-head">
          <span className="chip low">Resolved</span>
          <span className="issue-text">{issue.text}</span>
        </div>
        <div className="issue-final">
          <strong data-testid={`issue-final-${issue.id}`}>{chosen ? chosen.label : `${issue.answered}`}</strong>
          {chosen?.source && <PeekButton projectId={projectId} source={src(chosen.source)} label={chosen.label} />}
          {issue.selected_by && <span className="muted"> · selected by {issue.selected_by}</span>}
        </div>
        {others.length > 0 && (
          <ul className="issue-alternatives">
            {others.map((o) => (
              <li key={o.id}><span className="muted">{keepsEach ? "Kept as given:" : "Not used:"}</span> {o.label}
                {o.source && <PeekButton projectId={projectId} source={src(o.source)} label={o.label} />}</li>
            ))}
          </ul>
        )}
        {!confirmed && (
          <button type="button" className="link-btn" data-testid={`issue-change-${issue.id}`}
                  onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/client-review:reopen", params,
                                                     { group: group.id, issue: issue.id }), "")}>
            Change
          </button>
        )}
      </section>
    );
  }

  const ready = issue.answer ? Number(answer) > 0 : Boolean(option);
  return (
    <section className={`issue ${tone}`} aria-label={`${kind}: ${issue.text}`} data-testid={`issue-${issue.id}`}>
      <div className="issue-head">
        <span className={`chip issue-chip ${tone}`}>{kind}</span>
        <span className="issue-text">{issue.text}</span>
      </div>
      {issue.answer ? (
        <label className="issue-answer">
          <span>The value</span>
          <input type="number" inputMode="decimal" min={0} step="any" value={answer} data-testid={`issue-answer-${issue.id}`}
                 onChange={(e) => setAnswer(e.target.value)} />
        </label>
      ) : (
        <fieldset className="issue-options">
          <legend className="sr-only">Select one</legend>
          {issue.options.map((o: Option) => (
            <label key={o.id} className={`issue-option${option === o.id ? " on" : ""}`}>
              <input type="radio" name={issue.id} value={o.id} checked={option === o.id} onChange={() => setOption(o.id)}
                     data-testid={`issue-option-${issue.id}-${o.id}`} />
              <span className="issue-option-label">{o.label}
                {o.source?.title ? <span className="muted"> · {String(o.source.title)}</span> : null}</span>
              {o.source && <PeekButton projectId={projectId} source={src(o.source)} label={o.label} />}
            </label>
          ))}
        </fieldset>
      )}
      <button type="button" className="btn small primary" disabled={!ready} data-testid={`issue-confirm-${issue.id}`}
              onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/client-review:select", params,
                issue.answer ? { group: group.id, issue: issue.id, answer: Number(answer) }
                  : { group: group.id, issue: issue.id, option }), "")}>
        Confirm the selection
      </button>
    </section>
  );
}

function GroupCard({ projectId, group, run }: { projectId: string; group: Group; run: Run }) {
  const confirmed = group.state === "confirmed";
  const first = group.items[0]?.source ?? group.facts[0]?.source;
  const count = group.items.length ? `${group.items.length} item${group.items.length === 1 ? "" : "s"}`
                                   : `${group.facts.length} fact${group.facts.length === 1 ? "" : "s"}`;
  const noun = group.kind === "study" ? "study" : group.kind === "product" ? "product" : "values";
  return (
    <article className={`confirm-group ${confirmed ? "confirmed" : "to-confirm"}`} data-testid={`group-${group.id}`}
             aria-label={group.title}>
      <header className="confirm-head">
        <div className="confirm-title">
          <h3>{group.title}</h3>
          {confirmed
            ? <span className="chip low">Confirmed by {group.confirmed_by ?? "a person"} · loaded</span>
            : <span className="chip medium">To confirm · {count}</span>}
        </div>
        <PeekButton projectId={projectId} source={src(first)} label={group.title} testId={`peek-group-${group.id}`} />
      </header>

      {(group.notes ?? []).length > 0 && (
        <ul className="confirm-notes" data-testid={`notes-${group.id}`}>
          {(group.notes ?? []).map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}

      {group.facts.length > 0 && (
        <dl className="confirm-facts">
          {group.facts.map((f) => (
            <div key={f.field} className="confirm-row" data-testid={`fact-${group.id}-${f.field}`}>
              <dt>{f.label}</dt>
              <dd>{f.value}
                {(f.fills ?? []).length > 0 && (
                  <span className="muted"> · from {String(f.source.title ?? "a document")}, p. {String(f.source.page ?? "?")}:
                    set on {plural((f.fills ?? []).length, "dataset")} on confirm</span>
                )}
              </dd>
              <PeekButton projectId={projectId} source={src(f.source)} label={`${group.title}: ${f.label}`} />
            </div>
          ))}
        </dl>
      )}
      <ul className="confirm-items">
        {group.items.map((i) => (
          <li key={i.id} className="confirm-row" data-testid={`item-${i.id}`}>
            <span className="confirm-item-label">{itemLabel(i.label, i.target)}</span>
            <span className="confirm-item-value">{i.value}{i.note && <span className="muted"> · {i.note}</span>}</span>
            <PeekButton projectId={projectId} source={src(i.source)} label={itemLabel(i.label, i.target)} testId={`peek-item-${i.id}`} />
          </li>
        ))}
      </ul>

      {group.issues.map((issue) => <IssueCard key={issue.id} projectId={projectId} group={group} issue={issue} run={run} />)}

      {!confirmed && (
        <footer className="confirm-foot">
          <span className="muted">
            {group.open
              ? `Settle ${group.open} open item${group.open === 1 ? "" : "s"} first: a group confirm never waves a conflict or a question through.`
              : `Nothing open. Confirming loads this ${noun} into the project; it is recorded with your name.`}
          </span>
          <button type="button" className="btn primary" disabled={group.open > 0} data-testid={`confirm-${group.id}`}
                  onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/client-review:confirm",
                                                     { project_id: projectId }, { group: group.id }),
                                          `${group.title}: confirmed and loaded into the project.`)}>
            Confirm {group.kind === "study" ? group.title.replace(/^Study /, "") : noun} · {count}
          </button>
        </footer>
      )}
    </article>
  );
}

/** The client's data of one domain, each group to confirm or confirmed. */
export function ConfirmGroups({ projectId, groups, run }: { projectId: string; groups: Group[]; run: Run }) {
  if (!groups.length) return null;
  const open = groups.filter((g) => g.state === "to_confirm").length;
  return (
    <section className="confirm-groups" aria-label="The client's data" data-testid="client-groups">
      <h2 className="input-block-title">The client&apos;s data{open ? ` · ${open} to confirm` : " · confirmed"}</h2>
      {groups.map((g) => <GroupCard key={g.id} projectId={projectId} group={g} run={run} />)}
    </section>
  );
}
