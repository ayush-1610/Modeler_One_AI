"use client";

// The To do area (plan 2026-11-14 slices 2 and 4; the design text's "Tab To do"): the one list of work
// (lib/inputsWork.ts), by group in the order a person works through it. The file-level and batch work is settled here,
// in its batch tables (slice 4): the table layouts as a queue, the values to link one row per file, the numbers not read
// by file, the compound values no source gives with one citation; each table's rows are the work model's items, so the
// counts are the same everywhere. Every other row is one line that opens where the item is settled (its area, its card);
// inline, with the same form its home uses, only the compound's values to accept and the sheet form's disagreements; a
// study's facts and its confirmation are made on its card only (one home per decision, plan §2.1). Then what to ask the
// client (with the request to download), the model checks in words, the clean-up that blocks nothing (with its batch
// tables), and what is done and in the model. After a decision the focus moves on and the live region says what it did.
// What outlives a batch table's last row is kept here for the visit (final review CODE-3, A11Y-2, owner-job gaps 2 and
// 5): the layout dialog stays until the person closes it, and what was marked as not data stays listed with "Restore…".
// A row says why it is not counted only where its group does not already say it (review CODE-9).

import Link from "next/link";
import { useMemo, useState } from "react";

import { MappingReview } from "@/components/delivery/MappingReview";
import { LiveRegion } from "@/components/kit/LiveRegion";
import { STEP_ROUTES } from "@/lib/pipeline";
import { GROUPS, GROUP_LEDE, GROUP_TITLE, INLINE_TODO, restoredText, type Group, type Subject, type WorkItem, type WorkModel } from "@/lib/inputsWork";
import { STATUS_TONE, STATUS_WORD, type Status, plural } from "@/lib/words";

import { IssueCard } from "./ClientConfirm";
import { ClientRequest } from "./ClientRequest";
import { TodoAction, type Run, type TodoItem } from "./InputsTodo";
import { LayoutQueue } from "./todo/LayoutQueue";
import { LinkTable } from "./todo/LinkTable";
import { MissingValues } from "./todo/MissingValues";
import { MarkedNow, NotReadTable } from "./todo/NotReadTable";
import { TodoVisitContext, type LayoutWalk, type Marked, type TodoVisit } from "./todo/visit";

export type Readiness = { ready: boolean; checks: { check: string; ok: boolean; detail: string[] }[]; engine_dry_run: string };
/** The status a person narrows To do to from the status line (`?status=`), or every item. */
export type StatusFilter = Exclude<Status, "done"> | null;

const SHOWN = 5;   // rows of a group shown before "Show n more"

/** A row's testid: the /inputs to-do's rows keep theirs (`missing-<kind>-<target>`), a card to confirm is
 *  `todo-confirm-<key>`, every other row `todo-row-<id>`. */
function rowTestId(i: WorkItem): string {
  if (i.todo) return `missing-${i.todo.kind}-${i.todo.target}`;
  if (i.id.startsWith("confirm:")) return `todo-confirm-${i.id.slice("confirm:".length)}`;
  // a layout's row as its entry in the delivery's list: `todo-layout-<id>`, `-v<version>` for a later version beside it
  if (i.id.startsWith("layout:")) return (i.where.anchor ?? "").replace(/^delivery-mapping-/, "todo-layout-");
  return `todo-row-${i.id.replace(/[^A-Za-z0-9:_.|-]/g, "-")}`;
}

function Row({ item, projectId, run, review, onOpen, shared }: {
  item: WorkItem; projectId: string; run: Run; review: WorkModel["subjects"][number]["groups"]; onOpen: (item: WorkItem) => void;
  /** the reason its group says once for every row (not said again on the row) */
  shared?: string;
}) {
  const [settle, setSettle] = useState(false);
  // a compound value is settled here with its own form when there is something to settle (a value to accept, values
  // that disagree); one that no source gives is filled in on Compound, where the row opens
  const todo = item.todo as TodoItem | undefined;
  const settles = todo && INLINE_TODO.has(todo.kind) && item.where.tab === "compound"
    && (todo.kind !== "missing" || (todo.items?.length ?? 0) > 0 || Boolean(todo.identity));
  const group = item.issue ? review.find((g) => g.id === item.issue!.group) : undefined;
  const issue = group?.issues.find((x) => x.id === item.issue!.issue);
  const inline = Boolean(settles) || Boolean(issue);
  // the group heading carries the status word, and says once a reason every row shares: a row says only how it differs
  // from its group (review CODE-9: no "blocks nothing" on each row of "Blocks nothing")
  const quiet = item.blocked ? "can't be acted on yet" : item.group === "tidy" || item.why === shared ? null : item.why ? "holds up nothing yet" : null;
  const said = [item.inModel, item.blocked, item.why === shared ? "" : item.why, item.detail].filter(Boolean).join(" · ");
  const inlineId = `todo-inline-${item.id.replace(/[^A-Za-z0-9_-]/g, "-")}`;
  return (
    <li className={`todo-line${item.open ? "" : " quiet"}`} data-item={item.id}>
      <div className="todo-line-head">
        {quiet && <span className="chip neutral">{quiet}</span>}
        <button type="button" className="link-btn todo-line-label" onClick={() => onOpen(item)} data-testid={rowTestId(item)}
                title={`Open where it is settled: ${item.where.tab === "files" ? "Client files" : "its area"}`}>{item.label}</button>
        {said && <span className="todo-line-detail muted">{said}</span>}
        {inline && !item.blocked && (
          <button type="button" className="btn small" aria-expanded={settle} aria-controls={inlineId} onClick={() => setSettle(!settle)}
                  data-testid={`todo-settle-${item.id}`} aria-label={`${settle ? "Hide" : "Settle here"}: ${item.label}`}>
            {settle ? "Hide" : "Settle here"}
          </button>
        )}
      </div>
      {inline && !item.blocked && (
        <div className="todo-line-inline" id={inlineId} hidden={!settle}>
          {settle && settles && todo && <TodoAction t={todo} projectId={projectId} run={run} />}
          {settle && group && issue && <IssueCard projectId={projectId} group={group} issue={issue} run={run} />}
        </div>
      )}
    </li>
  );
}

/** A missing compound value no source gives yet (nothing proposed to accept): entered in To do's batch with one citation. */
const batchMissing = (i: WorkItem) => i.todo?.kind === "missing" && i.where.tab === "compound" && !(i.todo as TodoItem).items?.length
  && !(i.todo as TodoItem).identity && !i.blocked;

/** The file-level and batch work of a group, settled in To do with its batch table (plan 2026-11-14 §2.1, slice 4): the
 *  table layouts (a queue), the values to link (a table of files), the numbers not read (by file) and the compound values
 *  no source gives (one citation); the group's other items stay rows that open where they are settled. */
function Batches({ items, projectId, subjects, heading, onOpen, group, shared }: {
  items: WorkItem[]; projectId: string; subjects: Subject[]; heading: string; onOpen: (item: WorkItem) => void;
  /** the group the tables are in, and the reason it says once for every row (not said again on a row) */
  group: Group; shared?: string;
}) {
  const layouts = items.filter((i) => i.id.startsWith("layout:"));
  const links = items.filter((i) => /^(link|alias):/.test(i.id));
  const notRead = items.filter((i) => i.id.startsWith("notread:"));
  const missing = items.filter(batchMissing);
  return (
    <>
      {layouts.length > 0 && <LayoutQueue projectId={projectId} items={layouts} heading={heading} shared={group === "tidy" ? undefined : shared} />}
      {links.length > 0 && <LinkTable projectId={projectId} items={links} subjects={subjects} heading={heading} shared={shared} />}
      {notRead.length > 0 && <NotReadTable projectId={projectId} items={notRead} heading={heading} group={group} shared={shared} />}
      {missing.length > 0 && <MissingValues projectId={projectId} items={missing} onOpen={onOpen} heading={heading} />}
    </>
  );
}
const inBatch = (i: WorkItem) => /^(layout|link|alias|notread):/.test(i.id) || batchMissing(i);

function GroupList({ group, items, projectId, run, review, subjects, onOpen, first }: {
  group: Group; items: WorkItem[]; projectId: string; run: Run; review: WorkModel["subjects"][number]["groups"]; subjects: Subject[];
  onOpen: (item: WorkItem) => void; first: boolean;
}) {
  const [all, setAll] = useState(false);
  const rows = items.filter((i) => !inBatch(i));
  const shown = all || first ? rows : rows.slice(0, SHOWN);
  const open = items.filter((i) => i.open);
  const held = items.length - open.length;
  // the status word, once for the group (every row of a group has the same); amber only where a person decides or signs
  const status = (open[0] ?? items[0]).status;
  // what holds up the signatures on the delivery, said once; so is a reason every row not counted shares, and, when the
  // rows are counted and not counted, each reason with how many it keeps out of the count (a delivery whose files name
  // no study yet is shown with the rest of its kind of work, not under "Blocks nothing")
  const gates = [...new Set(items.map((i) => i.gate).filter(Boolean))];
  // what of it still needs the owner's decision, in one sentence (review OWN-2 d): the most a card of the group waits for
  const owners = [...new Set(items.filter((i) => i.gate && i.owner).map((i) => i.owner!))].sort((a, b) => b.length - a.length);
  const whys = [...new Set(items.map((i) => i.why))];
  const shared = whys.length === 1 && whys[0] ? whys[0] : undefined;
  const apart = shared ? [] : whys.filter((w): w is string => Boolean(w)).map((w) => [w, items.filter((i) => i.why === w).length] as const);
  const heading = `todo-group-${group}-title`;
  return (
    <section className="todo-group" data-testid={`todo-group-${group}`} aria-labelledby={heading}>
      <h3 id={heading} tabIndex={-1}>
        <span className={`chip ${STATUS_TONE[status]}`}>{STATUS_WORD[status]}</span> {GROUP_TITLE[group]}{" "}
        <span className="muted">({open.length}{held ? ` · ${held} not counted now` : ""})</span>
      </h3>
      <p className="muted todo-group-lede">{GROUP_LEDE[group]}</p>
      {gates.map((g) => (
        <p key={g} className="todo-gate" data-testid="todo-gate">Signing on the delivery waits for its clean-up: {g}.{" "}
          {owners[0] && <span data-testid="todo-owner">{owners[0]}</span>}</p>
      ))}
      {shared && <p className="todo-gate" data-testid={`todo-why-${group}`}>{shared}</p>}
      {apart.map(([why, n]) => <p key={why} className="todo-gate" data-testid={`todo-why-${group}`}>{n} not counted now: {why}</p>)}
      <Batches items={items} projectId={projectId} subjects={subjects} heading={heading} onOpen={onOpen} group={group} shared={shared} />
      {rows.length > 0 && (
        <ul className="todo-lines">
          {shown.map((i) => <Row key={i.id} item={i} projectId={projectId} run={run} review={review} onOpen={onOpen} shared={shared} />)}
        </ul>
      )}
      {rows.length > shown.length && (
        <button type="button" className="link-btn" onClick={() => setAll(true)} data-testid={`todo-more-${group}`}>
          Show {rows.length - shown.length} more</button>
      )}
    </section>
  );
}

export function TodoTab({ projectId, work, run, status, only, onStatus, onOnly, readiness, selectionRule, onOpen }: {
  projectId: string; work: WorkModel; run: Run;
  status: StatusFilter; only: boolean;
  onStatus: (status: StatusFilter) => void; onOnly: (on: boolean) => void;
  readiness: Readiness | null | undefined;
  selectionRule: string;
  onOpen: (item: WorkItem) => void;
}) {
  const review = work.subjects.flatMap((s) => s.groups);
  // what outlives a batch table's last row, for the visit: the layout dialog and the notes marked as not data
  const [marked, setMarked] = useState<Marked[]>([]);
  const [said, setSaid] = useState<string | null>(null);
  const [layout, setLayout] = useState<LayoutWalk | null>(null);
  const visit = useMemo<TodoVisit>(() => ({
    marked, said, walk: setLayout,
    mark: (entries, text) => {
      setMarked((was) => [...was, ...entries.map((e, i) => ({ ...e, id: `${e.file.file_id}-${was.length + i}` }))]);
      setSaid(text);
    },
    // a restore says what it did on the same line: what was said of the marking no longer holds
    unmark: (id) => {
      const gone = marked.find((m) => m.id === id);
      setMarked((was) => was.filter((m) => m.id !== id));
      if (gone) setSaid(restoredText(gone.label));
    },
  }), [marked, said]);
  const visible = work.items.filter((i) => (!status || i.status === status) && (!only || i.open));
  const groups = GROUPS.filter((g) => g !== "tidy" && g !== "done")
    .map((g) => [g, visible.filter((i) => i.group === g)] as const).filter(([, items]) => items.length);
  const tidy = work.items.filter((i) => i.group === "tidy");
  const tidyWhys = [...new Set(tidy.map((i) => i.why))];
  const tidyWhy = tidyWhys.length === 1 ? tidyWhys[0] : undefined;
  // the notes marked in this visit whose table is not shown now (its last row went): listed on their own (review CODE-3)
  const notReadIn = new Set<string>([
    ...groups.filter(([, items]) => items.some((i) => i.id.startsWith("notread:"))).map(([g]) => g as string),
    ...(!only && !status && tidy.some((i) => i.id.startsWith("notread:")) ? ["tidy"] : []),
  ]);
  const orphans = marked.filter((m) => !notReadIn.has(m.group));
  const shownLayout = layout ? layout.list[layout.at] : null;
  const done = work.items.filter((i) => i.group === "done");
  // an open check whose gap a group above lists already is not said again (final review OWN-14)
  const openChecks = work.checks.filter((c) => !c.ok && !c.said);
  const passed = work.checks.filter((c) => c.ok);
  const filters: [StatusFilter, string, number][] = [
    [null, "All", work.counts.open], ["missing", STATUS_WORD.missing, work.counts.missing],
    ["to_confirm", STATUS_WORD.to_confirm, work.counts.to_confirm], ["to_decide", STATUS_WORD.to_decide, work.counts.to_decide],
  ];
  return (
    <TodoVisitContext.Provider value={visit}>
    <section className="card todo-work" data-testid="still-missing">
      <LiveRegion testId="todo-live" />
      <div className="todo-head">
        <div>
          <h2 className="m-0" id="todo-title" tabIndex={-1}>What needs you</h2>
          <p className="muted m-0">Start at the top: each group unblocks the ones below.</p>
        </div>
        <div className="todo-filters">
          <div className="table-chips" role="group" aria-label="Show">
            {filters.map(([id, label, n]) => (
              <button key={label} type="button" aria-pressed={status === id} data-testid={`todo-filter-${id ?? "all"}`}
                      onClick={() => onStatus(id)}>{label} <span className="status-num">{n}</span></button>
            ))}
          </div>
          <label className="only-mine">
            <input type="checkbox" checked={only} onChange={(e) => onOnly(e.target.checked)} data-testid="todo-only" />
            Only what needs me
          </label>
        </div>
      </div>

      {work.counts.open === 0 && (readiness?.ready ? (
        <div className="todo-ready" data-testid="inputs-ready">
          <h3 className="mt-0">Everything the model needs is here</h3>
          <p className="m-0-0-8">Every value the model needs has a source, and every planned simulation builds.</p>
          {/* the page's one primary is the status line's "Next" */}
          <Link className="btn" href={STEP_ROUTES.review(projectId)}>Go to Review &amp; sign</Link>
        </div>
      ) : (
        <p className="muted" data-testid="todo-nothing">Nothing needs you here now.{openChecks.length ? " The model checks below say what is left." : ""}</p>
      ))}

      {groups.map(([group, items], n) => (
        <GroupList key={group} group={group} items={items} projectId={projectId} run={run} review={review} subjects={work.subjects}
                   onOpen={onOpen} first={n === 0} />
      ))}
      {orphans.length > 0 && <MarkedNow projectId={projectId} entries={orphans} said={said} alone titleId="notread-marked-title" />}

      {!status && (
        <section className="todo-group" data-testid="todo-group-ask">
          <h3>Ask the client {work.ask.length > 0 && <span className="muted">({work.ask.length})</span>}</h3>
          {work.ask.length > 0 ? (
            <ul className="todo-lines">
              {work.ask.map((a) => (
                <li key={`${a.req}|${a.what}`} className="todo-line" data-testid={`todo-ask-${a.req}`}>
                  <div className="todo-line-head">
                    <span>{a.what}{a.subjects.length > 0 && <span className="muted"> · {a.subjects.join(", ")}</span>}</span>
                  </div>
                  {/* said once: what it is needed (or useful) for (final review OWN-14) */}
                  <p className="todo-line-detail muted">{a.required ? "needed" : "useful"} for {a.why}</p>
                </li>
              ))}
            </ul>
          ) : <p className="muted m-0">Nothing the client alone holds is missing from the files they sent.</p>}
          <ClientRequest projectId={projectId} />
        </section>
      )}

      {!status && (
        <section className="todo-group" data-testid="todo-group-checks">
          <h3>Model checks {openChecks.length > 0 && <span className="muted">({openChecks.length} open)</span>}</h3>
          <ul className="checks" data-testid="readiness">
            {openChecks.map((c) => (
              <li key={c.raw} data-testid={`check-${c.raw}`} data-ok="false">
                <strong>{c.label}</strong>{c.fix && <span className="muted"> · {c.fix}</span>}
              </li>
            ))}
            {!only && passed.length > 0 && (
              <li className="checks-passed">
                <details>
                  <summary>{plural(passed.length, "check passes", "checks pass")}</summary>
                  <ul className="checks">
                    {passed.map((c) => <li key={c.raw} data-testid={`check-${c.raw}`} data-ok="true"><span aria-hidden="true">✓ </span>{c.label}</li>)}
                  </ul>
                </details>
              </li>
            )}
          </ul>
          {readiness && <p className="muted fs-12 m-6-0-0">PK-Sim test load: {readiness.engine_dry_run}</p>}
          <p className="muted fs-13 m-6-0-0">How values are chosen: when sources disagree, the client&apos;s value comes first, then the
            best-graded paper. Values are never averaged.</p>
          <p className="muted fs-12 m-4-0-0" data-testid="selection-rule">Source selection rules: {selectionRule}</p>
        </section>
      )}

      {!only && !status && tidy.length > 0 && (
        <details className="todo-group todo-fold" data-testid="todo-group-tidy">
          <summary id="todo-group-tidy-title"><span className="todo-caret" aria-hidden="true" /><strong>{GROUP_TITLE.tidy}</strong>{" "}
            <span className="muted">({tidy.length})</span></summary>
          <p className="muted todo-group-lede">{tidyWhy ? `${tidyWhy} Tidy it for the delivery record.` : GROUP_LEDE.tidy}</p>
          <Batches items={tidy} projectId={projectId} subjects={work.subjects} heading="todo-group-tidy-title" onOpen={onOpen} group="tidy"
                   shared={tidyWhy} />
          {tidy.some((i) => !inBatch(i)) && (
            <ul className="todo-lines">
              {tidy.filter((i) => !inBatch(i)).map((i) => <Row key={i.id} item={i} projectId={projectId} run={run} review={review} onOpen={onOpen} shared={tidyWhy} />)}
            </ul>
          )}
        </details>
      )}
      {!only && !status && done.length > 0 && (
        <details className="todo-group todo-fold" data-testid="todo-group-done">
          <summary><span className="todo-caret" aria-hidden="true" /><strong>{GROUP_TITLE.done}</strong> <span className="muted">({done.length})</span></summary>
          <ul className="todo-lines">
            {done.map((i) => <Row key={i.id} item={i} projectId={projectId} run={run} review={review} onOpen={onOpen} />)}
          </ul>
        </details>
      )}
      {layout && shownLayout && (
        <MappingReview projectId={projectId} mappingId={shownLayout.id} version={shownLayout.version} at={shownLayout.at}
                       onClose={() => setLayout(null)}
                       returnFocus={() => document.getElementById(layout.heading) ?? document.getElementById("todo-title")}
                       onStored={(version) => setLayout((q) => (q ? { ...q, list: q.list.map((x, n) => (n === q.at ? { ...x, version } : x)) } : q))}
                       queue={layout.queue ? {
                         at: layout.at, total: layout.list.length,
                         go: (delta) => setLayout((q) => (q ? { ...q, at: Math.max(0, Math.min(q.list.length - 1, q.at + delta)) } : q)),
                       } : undefined} />
      )}
    </section>
    </TodoVisitContext.Provider>
  );
}
