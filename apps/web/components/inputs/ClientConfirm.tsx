"use client";

// The client's data as the sheet form read it, confirmed where it lands (docs/plans/2026-11-03-inputs-and-client-data.md
// §3.3; the owner, 2026-11-03): a study on Clinical studies, a product on Products and dissolution, a file's values on
// Compound, each inside its one card (plan 2026-11-14 slice 3, components/inputs/cards). A group waits, "To confirm",
// until a person confirms it, and only then loads into the model. A conflict or a question sits on the card it concerns
// and blocks the confirmation until settled: the person selects an option and confirms the selection, with no reason
// asked. A settled one stays in place with its final value and its alternatives, and can be changed until the group is
// confirmed. Every value opens its source in the centre peek. On a card confirmed on the delivery the sheet form's
// reading is shown for reference ("read"), and it can still be confirmed this way (plan §2.2.1).

import { useState, type ReactNode } from "react";

import type { Profile } from "@/components/client/types";
import { PeekButton, type PeekSource } from "@/components/kit/SourcePeek";
import { send, type Schema } from "@/lib/api";
import { valueWord, whenText } from "@/lib/words";

import { confirmAfter, reviewAfter } from "./after";
import { DatasetView, ReleaseView } from "./DatasetView";
import { DraftItem } from "./DraftItem";
import { LABEL, type Run } from "./InputsTodo";

type Group = Schema<"ReviewGroup">;
type Issue = Schema<"ReviewIssue">;
type Option = Schema<"ReviewOption">;

// a link question asks whether two names are one study, product or batch (by the issue's scope: link, plink, blink)
const LINK_LABEL: Record<string, string> = { link: "Same study?", plink: "Same product?", blink: "Same batch?" };
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

/** A conflict, a difference or a question on a group, settled by selecting one option: on its card, and in To do with the
 *  same form bound to the same server state (plan 2026-11-14 §2, rule 2). */
export function IssueCard({ projectId, group, issue, run, read = false }: {
  projectId: string; group: Group; issue: Issue; run: Run;
  /** shown for reference: no selection is made here */
  read?: boolean;
}) {
  const [option, setOption] = useState<string>("");   // nothing preselected: the person chooses
  const [answer, setAnswer] = useState("");
  const [kind, tone] = issue.kind === "link" ? [LINK_LABEL[issue.id.split("|")[0]] ?? "Same?", "question"] : KIND[issue.kind];
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
          <span className="chip low">Done</span>
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
        {!confirmed && !read && (
          <button type="button" className="link-btn" data-testid={`issue-change-${issue.id}`} aria-label={`Change: ${issue.text}`}
                  onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/client-review:reopen", params,
                                                     { group: group.id, issue: issue.id }), "", reviewAfter(projectId))}>
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
      {read ? (
        <p className="muted m-0 fs-13">{issue.options.map((o) => o.label).join(" · ")}</p>
      ) : issue.answer ? (
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
      {!read && (
        <button type="button" className="btn small" disabled={!ready} data-testid={`issue-confirm-${issue.id}`}
                aria-label={`Confirm the selection: ${issue.text}`}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/client-review:select", params,
                  issue.answer ? { group: group.id, issue: issue.id, answer: Number(answer) }
                    : { group: group.id, issue: issue.id, option }), "", reviewAfter(projectId))}>
          Confirm the selection
        </button>
      )}
    </section>
  );
}

/** What is open on a group, in the status words the rest of the page counts it with (lib/inputsWork.ts): a sheet that
 *  does not say a fact is one Missing (`needs`: the facts it does not say), a conflict or a question not answered is one
 *  To decide. */
export function openOf(group: Group): { drafts: number; needs: string[]; decide: number } {
  const drafts = group.items.filter((i) => i.kind === "draft");
  const needs = drafts.flatMap((i) => {
    const d = i.draft as { needs?: string[]; labels?: Record<string, string> } | null | undefined;
    return (d?.needs ?? []).map((n) => d?.labels?.[n] ?? n.replace(/_/g, " "));
  });
  return { drafts: drafts.length, needs: [...new Set(needs)], decide: group.issues.filter((i) => i.selected === null && i.answered === null).length };
}

/** A group's open items in a few words: "2 facts to fill in · 1 to decide". */
export function openText(group: Group): string {
  const o = openOf(group);
  return [o.needs.length ? plural(o.needs.length, "fact") + " to fill in" : o.drafts ? plural(o.drafts, "sheet") + " to read" : "",
          o.decide ? `${o.decide} to decide` : ""].filter(Boolean).join(" · ");
}

const NOUN: Record<Group["kind"], string> = { study: "study", product: "product", compound: "values", sheet: "sheet" };

/** One group of the sheet form on its card, in the card's order: its facts, its data (each dataset drawn, each sheet that
 *  does not say a fact with the form that asks it), what is to decide, then its one Confirm. `mode` "read": shown for
 *  reference on a card confirmed on the delivery, with no form. `files` sits after the data (the card's "Files and
 *  tables"). */
export function GroupCard({ projectId, group, run, mode = "confirm", alsoOnDelivery, files, drawn = true, confirmedSaid = false, known, why }: {
  projectId: string; group: Group; run: Run; mode?: "confirm" | "read";
  /** why the card it is on is blinded (`blindedWhy`: the delivery's reason, else the group's own); the group's own when
   *  it is alone */
  why?: string | null;
  /** the study or product is also confirmed and signed on the delivery: whichever is confirmed first is what loads */
  alsoOnDelivery?: boolean;
  files?: ReactNode;
  /** false where the card draws the group's data already (its Observed data, its dissolution): each item is one line */
  drawn?: boolean;
  /** the card it is on says already who confirmed it and when (one confirmation line per card; final review OWN-14) */
  confirmedSaid?: boolean;
  /** what the study's delivery card states already, by need: pre-filled in its sheets' drafts */
  known?: Record<string, { value: string; from: string }>;
}) {
  const confirmed = group.state === "confirmed";
  const read = mode === "read";
  const first = group.items[0]?.source ?? group.facts[0]?.source;
  const noun = NOUN[group.kind];
  const name = group.kind === "study" ? `study ${group.title.replace(/^Study /, "")}` : group.kind === "product" ? `product ${group.title.replace(/^Product /, "")}` : noun;
  const facts = group.items.filter((i) => i.kind === "draft").length;
  const data = group.items.filter((i) => i.kind !== "draft");
  const drafts = group.items.filter((i) => i.kind === "draft");
  if (group.blinded) {
    // a study or product blinded until the plan is signed (D-15: the delivery's rule or the project's list, one rule):
    // the API withholds what the sheet form read of it and refuses to read or confirm it (409 BLINDED) until then, so
    // nothing of it is drawn or offered here; one confirmed already stays in the model. Why is said (round 4: the card's
    // reason, else the group's `blinded_why`), so a wrong name match is seen where it is withheld
    const reason = why ?? group.blinded_why;
    return (
      <article className={`confirm-group ${confirmed ? "confirmed" : "to-confirm"} reading`} data-testid={`group-${group.id}`}
               id={`group-${group.id}`} aria-label={group.title}>
        <header className="confirm-head">
          <div className="confirm-title"><span className="muted fs-13">Read with the sheet form</span>
            {confirmed && <span className="chip low">Done</span>}
            <span className="chip neutral">blinded until the plan is signed</span></div>
        </header>
        <p className="delivery-withheld m-0" data-testid={`group-withheld-${group.id}`}>Withheld: {name} is blinded until the plan is
          signed{reason ? `, because ${reason}` : ""}.
          {confirmed ? " It is in the model; what the sheet form read of it is shown once the plan is signed."
            : " What the sheet form read of it is not shown, and it is read and confirmed once the plan is signed."}</p>
      </article>
    );
  }
  return (
    <article className={`confirm-group ${confirmed ? "confirmed" : "to-confirm"}${read ? " reading" : ""}`}
             data-testid={`group-${group.id}`} id={`group-${group.id}`} aria-label={group.title}>
      <header className="confirm-head">
        <div className="confirm-title">
          <span className="muted fs-13">{read ? "As the sheet form read it" : "Read with the sheet form"}</span>
          {confirmed
            ? <span className="chip low">Done</span>
            : group.kind === "sheet" && openOf(group).needs.length
              ? <span className="chip high" data-testid={`group-missing-${group.id}`}>Missing: {openOf(group).needs.join(", ")}</span>
              : openText(group) ? <span className="chip high" data-testid={`group-open-${group.id}`}>{openText(group)}</span>
                : <span className="chip medium">To confirm</span>}
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
              <dd>{valueWord(f.value)}
                {(f.fills ?? []).length > 0 && (
                  <span className="muted"> · from {String(f.source.title ?? "a client file")}, {String(f.source.locator ?? `p. ${f.source.page}`)}:
                    set on {plural((f.fills ?? []).length, "dataset")} on confirm</span>
                )}
              </dd>
              <PeekButton projectId={projectId} source={src(f.source)} label={`${group.title}: ${f.label}`} />
            </div>
          ))}
        </dl>
      )}
      {(data.length > 0 || drafts.length > 0) && (
        <ul className="confirm-items">
          {[...drafts, ...data].map((i) => (
            <li key={i.id} className={i.data || i.release || i.kind === "draft" ? "confirm-dataset" : undefined} data-testid={`item-${i.id}`}>
              <div className="confirm-row">
                <span className="confirm-item-label">{itemLabel(i.label, i.target)}</span>
                <span className="confirm-item-value">{i.value}{i.note && <span className="muted"> · {i.note}</span>}</span>
                {/* named apart from the group's own peek above when they read the same (a sheet with one draft) */}
                <PeekButton projectId={projectId} source={src(i.source)} testId={`peek-item-${i.id}`}
                            label={itemLabel(i.label, i.target) === group.title ? `${group.title}, its data` : itemLabel(i.label, i.target)} />
              </div>
              {i.kind === "draft" && !read ? <DraftItem projectId={projectId} item={i} run={run} known={known} /> : drawn ? <>
                {i.data && <DatasetView data={i.data} label={`${group.title}: ${itemLabel(i.label, i.target)}`} />}
                {/* its name is the item's line just above: not said again over the chart */}
                {i.release && <ReleaseView p={i.release as Profile} title="" />}
              </> : (i.data || i.release) && <p className="muted m-0 fs-12">Drawn above, on the card.</p>}
            </li>
          ))}
        </ul>
      )}
      {files}

      {group.issues.map((issue) => <IssueCard key={issue.id} projectId={projectId} group={group} issue={issue} run={run} read={read} />)}

      {!confirmed && group.kind === "sheet" && (
        <footer className="confirm-foot">
          <span className="muted">Once read, its data join their {group.tab === "formulations" ? "product" : "study"}, to confirm there.</span>
        </footer>
      )}
      {confirmed && !confirmedSaid && (
        <p className="m-0 fs-13" data-testid={`group-confirmed-${group.id}`}>
          Confirmed by {group.confirmed_by ?? "a person"}{group.confirmed_at ? ` on ${whenText(group.confirmed_at)}` : ""}
          {group.kind === "product" ? ": its data are in the model; its dissolution sets a formulation's release only once used as the release."
            : ": in the model."}
        </p>
      )}
      {!confirmed && !read && group.kind !== "sheet" && (
        <footer className="confirm-foot">
          <span className="muted">
            {group.open
              ? facts ? "Fill in the missing facts above and settle what is to decide, then confirm."
                : `Settle ${plural(group.open, "open item")} above first: a confirmation never waves a disagreement through.`
              : `Ready. Confirming adds this ${noun} to the model under your name.`}
            {alsoOnDelivery && <span data-testid={`both-paths-${group.id}`}> Whichever is confirmed first is what loads; nothing is
              loaded twice.</span>}
          </span>
          <button type="button" className="btn primary" disabled={group.open > 0} data-testid={`confirm-${group.id}`}
                  onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/client-review:confirm",
                                                     { project_id: projectId }, { group: group.id }),
                                          group.kind === "product"
                                            ? `${group.title}: confirmed. Its dissolution profile is kept; the formulation's release is set with “Use this profile as the release” on its card.`
                                            : `${group.title}: confirmed, in the model.`, confirmAfter(projectId, group.id))}>
            Confirm {name}
          </button>
        </footer>
      )}
    </article>
  );
}

/** The sheets whose study or product is not stated yet (sheet groups): each with what it does not say, read on its own
 *  card until it joins its study or product. */
export function SheetGroups({ projectId, groups, run, title, testId }: {
  projectId: string; groups: Group[]; run: Run; title: string; testId: string;
}) {
  if (!groups.length) return null;
  return (
    <section className="confirm-groups" data-testid={testId}>
      <h3 className="area-section-title">{title} <span className="muted">({groups.length})</span></h3>
      {groups.map((g) => <GroupCard key={g.id} projectId={projectId} group={g} run={run} />)}
    </section>
  );
}
