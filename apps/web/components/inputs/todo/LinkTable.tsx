"use client";

// To do's "Link values to a study or product" (plan 2026-11-14 §2.1, §2.2.2, slice 4; the design text's `LinkTable`): one
// row per file whose values say no study or product (366 values in 6 files on the 9-file project: one row each, not one
// form per table and per fact), each with what it holds and where its values go: suggested from the file's own labels
// (its tables' titles and the lines read with them, its name), or asked first when the sheet form read it under a name
// that only starts with a delivery study's ("Same study as 230-23?": Yes fills that study and the arm that keeps the
// file apart). A row opens on its editor (the fill round's link form: study and arm, product and batch, analyte, each an
// existing one or a new one) and its values. Rows are picked and linked together from the bulk bar with one reason:
// each where its row says, or all to one place; one `values:assign` per destination, every value of the files in it.
// Before anything is sent, two files that hold the same subject in the same period are refused one arm of one study
// (§2.2.2), with "A new arm" for each offered right there. A refusal of the server is said on its row, in its words.
// Each answer is the page, written into the cache (writes.ts): a link costs the request and the one card it changed.

import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Problem, useDecide, type Page } from "@/components/delivery/shared";
import { LinkEditor, TargetFields } from "@/components/delivery/Unassigned";
import { writePage } from "@/components/delivery/writes";
import { BulkBar } from "@/components/kit/BulkBar";
import { focusAfter, nextRow } from "@/components/kit/focus";
import { announce } from "@/components/kit/LiveRegion";
import { ReasonForm } from "@/components/kit/Reason";
import { send, type Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import {
  NEW, NO_TARGET, assignBody, collisions, destinationKey, distinctWords, linkRows, normLabel, targetProblem, type Collision, type LinkRow,
  type LinkTarget, type Subject, type WorkItem,
} from "@/lib/inputsWork";
import { plural } from "@/lib/words";

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
const ASSIGN = "/api/v1/projects/{project_id}/delivery/values:assign" as const;
const CARD = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;
type Card = Schema<"DeliverySubject">;

/** Where a target sends the values, in words: "study 230-23 · arm Reference (new) · analyte Exampleamide". */
function whereText(t: LinkTarget, page: Page, row: LinkRow): string {
  const name = (choice: string, fresh: string, list: { id: string; label: string }[]) =>
    (choice === NEW ? `${fresh.trim() || "…"} (new)` : list.find((x) => x.id === choice)?.label ?? choice);
  const study = page.subjects.find((s) => s.subject === t.study);
  const product = page.subjects.find((s) => s.subject === t.product);
  const own = (e: { id: string; label: string } | null) => (e ? [e] : []);
  return [
    t.study ? `study ${name(t.study, t.newStudy, page.subjects.map((s) => ({ id: s.subject, label: s.label })))}` : "",
    t.study && t.arm ? `arm ${name(t.arm, t.newArm, [...own(row.own.arm), ...(study?.arms ?? [])])}` : "",
    t.product ? `product ${name(t.product, t.newProduct, page.subjects.map((s) => ({ id: s.subject, label: s.label })))}` : "",
    t.product && t.batch ? `batch ${name(t.batch, t.newBatch, [...own(row.own.batch), ...(product?.batches ?? [])])}` : "",
    t.analyte ? `analyte ${name(t.analyte, t.newAnalyte, [...own(row.own.analyte), ...page.analytes])}` : "",
  ].filter(Boolean).join(" · ");
}

/** A new study, product, arm, batch or analyte named in this batch and made by an earlier call of it: its id now. */
function made(t: LinkTarget, before: Page, after: Page): LinkTarget {
  const fresh = <T extends { id: string; label: string }>(was: T[], now: T[], label: string) =>
    now.find((x) => !was.some((y) => y.id === x.id) && normLabel(x.label) === normLabel(label));
  const subjects = (p: Page) => p.subjects.map((s) => ({ id: s.subject, label: s.label }));
  const out = { ...t };
  if (out.study === NEW) { const s = fresh(subjects(before), subjects(after), out.newStudy); if (s) Object.assign(out, { study: s.id, newStudy: "" }); }
  if (out.product === NEW) { const s = fresh(subjects(before), subjects(after), out.newProduct); if (s) Object.assign(out, { product: s.id, newProduct: "" }); }
  const arms = (p: Page) => p.subjects.find((s) => s.subject === out.study)?.arms ?? [];
  if (out.arm === NEW) { const a = fresh(arms(before), arms(after), out.newArm); if (a) Object.assign(out, { arm: a.id, newArm: "" }); }
  const batches = (p: Page) => p.subjects.find((s) => s.subject === out.product)?.batches ?? [];
  if (out.batch === NEW) { const b = fresh(batches(before), batches(after), out.newBatch); if (b) Object.assign(out, { batch: b.id, newBatch: "" }); }
  if (out.analyte === NEW) { const a = fresh(before.analytes, after.analytes, out.newAnalyte); if (a) Object.assign(out, { analyte: a.id, newAnalyte: "" }); }
  return out;
}

export function LinkTable({ projectId, items, subjects, heading }: {
  projectId: string;
  /** the work model's link and alias items shown (To do's filters applied) */
  items: WorkItem[];
  subjects: Subject[];
  /** the group heading's element id: where the focus goes when the last row is linked */
  heading: string;
}) {
  const page = useResource(DELIVERY, { project_id: projectId }).data;
  const client = useQueryClient();
  const { decide, busy } = useDecide();
  const rows = useMemo(() => linkRows(items, page, subjects), [items, page, subjects]);
  const [targets, setTargets] = useState<Record<string, LinkTarget>>({});
  const [answers, setAnswers] = useState<Record<string, "yes" | "no">>({});
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [onePlace, setOnePlace] = useState(false);
  const [bulk, setBulk] = useState<LinkTarget>(NO_TARGET);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [armNames, setArmNames] = useState<Record<string, string>>({});
  if (!page?.enabled || !rows.length) return null;

  // a row's target: what the person chose for it, else Yes to the alias question, else what its labels suggest
  const own = (r: LinkRow): LinkTarget | null => targets[r.sha] ?? (r.alias ? (answers[r.sha] === "yes" ? r.alias.target
    : answers[r.sha] === "no" && r.sheet ? { ...NO_TARGET, study: NEW, newStudy: r.sheet, analyte: r.own.analyte?.id ?? "" } : null)
    : r.suggested?.target ?? null);
  const targetOf = (r: LinkRow) => own(r) ?? { ...NO_TARGET, analyte: r.own.analyte?.id ?? "" };
  const suggested = (r: LinkRow) => !targets[r.sha] && own(r) !== null;
  const setTarget = (r: LinkRow, t: LinkTarget) => {
    setTargets((was) => ({ ...was, [r.sha]: t }));
    setProblems((was) => Object.fromEntries(Object.entries(was).filter(([sha]) => sha !== r.sha)));
  };
  const chosen = rows.filter((r) => picked.has(r.sha));
  const effective = (r: LinkRow) => (onePlace ? bulk : targetOf(r));
  const studies = page.subjects;

  // what a study already holds, by arm and analyte (its card, when the page has read it): a file cannot join an arm
  // that holds its subjects and periods already
  const existing = (picks: { row: LinkRow; target: LinkTarget }[]) => {
    const out: Record<string, { arm: string; analyte: string; pair: string }[]> = {};
    for (const id of new Set(picks.map((p) => p.target.study).filter((s) => s && s !== NEW))) {
      const card = client.getQueryData<Card>([CARD, { project_id: projectId, type: "study", subject: id }, {}]);
      out[id] = (card?.tables ?? []).flatMap((t) => t.values).filter((v) => v.labels.subject)
        .map((v) => ({ arm: v.entity.arm ?? "", analyte: v.entity.analyte ?? "", pair: `${v.labels.subject} · ${v.labels.period ?? ""}` }));
    }
    return out;
  };
  const guard = (picks: { row: LinkRow; target: LinkTarget }[]): Collision[] => collisions(picks, studies, existing(picks));

  /** Link the rows, one `values:assign` per destination; a name made by an earlier call of the batch is used by its id. */
  async function link(list: LinkRow[], why: string, where: (r: LinkRow) => LinkTarget = effective) {
    const groups = new Map<string, { target: LinkTarget; rows: LinkRow[] }>();
    for (const r of list) {
      const t = where(r), key = destinationKey(t);
      groups.set(key, { target: t, rows: [...(groups.get(key)?.rows ?? []), r] });
    }
    const order = rows.map((r) => `link-${r.fileId}`);
    let current = page!;
    const done: LinkRow[] = [];
    const failed: Record<string, string> = {};
    for (const g of groups.values()) {
      const target = made(g.target, page!, current);
      const { data, problem } = await decide(() => send("post", ASSIGN, { project_id: projectId },
        assignBody(target, g.rows.flatMap((r) => r.values.map((v) => v.id)), why)), { refresh: false });
      if (data) {
        writePage(client, projectId, data);
        current = data;
        done.push(...g.rows);
      } else for (const r of g.rows) failed[r.sha] = problem ?? "It was not linked.";
    }
    setProblems((was) => ({ ...was, ...failed }));
    setPicked((was) => new Set([...was].filter((s) => !done.some((r) => r.sha === s))));
    if (done.length) {
      const left = rows.length - done.length;
      announce(`${done.map((r) => r.file).join(", ")} linked to ${[...new Set(done.map((r) => whereText(where(r), current, r)))].join("; ")}. `
        + `${left ? `${plural(left, "file")} left to link.` : "Every file is linked."}${Object.keys(failed).length ? ` ${plural(Object.keys(failed).length, "file")} not linked: see its row.` : ""}`);
      const decided = done.map((r) => `link-${r.fileId}`);
      focusAfter(decided, nextRow(order, decided), [heading, "todo-title"]);
      setOnePlace(false);
      if (done.some((r) => r.sha === open)) setOpen(null);
    }
  }

  // what the picked rows still need, and the arms that would mix two files' subjects
  const picks = chosen.map((r) => ({ row: r, target: effective(r) }));
  const clash = guard(picks);
  const lacking = picks.map((p) => [p.row, targetProblem(p.target)] as const).filter(([, m]) => m);
  const bulkMissing = lacking.length ? `${lacking[0][0].file}: ${lacking[0][1]}` : clash.length ? "Give each file its own arm first (above)" : null;
  const reasons = (list: LinkRow[]) => [...new Set(list.flatMap((r) => [
    answers[r.sha] === "yes" && r.alias ? `the sheet form read it as ${r.sheet}, a part of study ${r.alias.study.label}` : "",
    suggested(r) && r.suggested ? `${r.suggested.why.replace(/^its/, "the file's")}` : "",
  ]).filter(Boolean))].slice(0, 3);
  const giveArms = (c: Collision[]) => {
    const keys = new Set(c.flatMap((x) => x.keys));
    const clashing = picks.filter((p) => keys.has(p.row.sha));
    setTargets((was) => {
      const next = { ...was };
      for (const p of clashing) {
        const name = armNames[p.row.sha] ?? distinctWords(p.row.file, clashing.filter((x) => x !== p).map((x) => x.row.file));
        next[p.row.sha] = { ...p.target, arm: NEW, newArm: name };
      }
      return next;
    });
    setOnePlace(false);
  };
  const allPicked = rows.every((r) => picked.has(r.sha));

  return (
    <div className="batch link-table" data-testid="link-table">
      <div className="batch-head">
        <label className="batch-all">
          <input type="checkbox" checked={allPicked} ref={(el) => { if (el) el.indeterminate = !allPicked && picked.size > 0; }}
                 onChange={() => setPicked(allPicked ? new Set() : new Set(rows.map((r) => r.sha)))} data-testid="link-pick-all" />
          Pick every file
        </label>
        <span className="muted">{plural(rows.length, "file")} · {plural(rows.reduce((n, r) => n + r.values.length, 0), "value")}</span>
      </div>
      <ul className="batch-rows">
        {rows.map((r) => {
          const t = targetOf(r);
          const asking = r.alias && !answers[r.sha] && !targets[r.sha];
          const context = `${plural(r.values.length, "value")} of ${r.file}`;
          const rowClash = guard([{ row: r, target: t }]);
          return (
            <li key={r.sha} className={`batch-row${open === r.sha ? " open" : ""}`} data-testid={`link-${r.fileId}`}>
              <div className="batch-line">
                <input type="checkbox" checked={picked.has(r.sha)} aria-label={`Pick the ${context}`} data-testid={`link-pick-${r.fileId}`}
                       onChange={() => setPicked((was) => { const n = new Set(was); if (!n.delete(r.sha)) n.add(r.sha); return n; })} />
                <div className="batch-what">
                  <strong>{r.file}</strong>
                  <span className="muted">{r.holds}</span>
                  {r.item.why && r.item.group !== "tidy" && <span className="chip neutral" title={r.item.why}>holds up nothing yet</span>}
                </div>
                <div className="batch-where" data-testid={`link-to-${r.fileId}`}>
                  {asking ? (
                    <span className="link-ask">
                      <span>The sheet form read it as {r.sheet}.</span>{" "}
                      <span className="link-ask-q">
                        <strong>Same study as {r.alias!.study.label}?</strong>
                        <button type="button" className="btn small" data-testid={`link-alias-yes-${r.fileId}`}
                                aria-label={`Yes: the ${context} are study ${r.alias!.study.label}`}
                                onClick={() => setAnswers((was) => ({ ...was, [r.sha]: "yes" }))}>Yes</button>
                        <button type="button" className="btn small" data-testid={`link-alias-no-${r.fileId}`}
                                aria-label={`No: the ${context} are not study ${r.alias!.study.label}`}
                                onClick={() => setAnswers((was) => ({ ...was, [r.sha]: "no" }))}>No</button>
                      </span>
                    </span>
                  ) : own(r) ? (
                    <>
                      <span>→ {whereText(t, page, r)}</span>
                      {suggested(r) && <span className="chip neutral" title={r.suggested?.why ?? (answers[r.sha] === "yes" ? "you said it is the same study" : "the sheet form's name")}>suggested</span>}
                    </>
                  ) : <span className="muted">not chosen yet{r.sheet ? ` · the sheet form read it as ${r.sheet}` : ""}</span>}
                  {rowClash.length > 0 && <span className="link-clash">{rowClash[0].example} is in study {rowClash[0].study} in that arm already: give it an arm of its own</span>}
                </div>
                <button type="button" className="btn small" aria-expanded={open === r.sha} aria-controls={`link-editor-${r.fileId}`}
                        aria-label={`${open === r.sha ? "Close" : "Choose"} where the ${context} go`} data-testid={`link-open-${r.fileId}`}
                        onClick={() => setOpen(open === r.sha ? null : r.sha)}>{open === r.sha ? "Close" : "Edit…"}</button>
              </div>
              <Problem text={problems[r.sha] ?? null} testId={`link-row-problem-${r.fileId}`} />
              {open === r.sha && (
                <div id={`link-editor-${r.fileId}`}>
                  <LinkEditor projectId={projectId} row={r} target={t} onTarget={(x) => setTarget(r, x)} subjects={page.subjects} analytes={page.analytes}
                              busy={busy} missing={targetProblem(t) ?? (rowClash.length ? `${rowClash[0].example} is in study ${rowClash[0].study} in that arm already: choose another arm` : null)}
                              suggestions={reasons([r])} onLink={(why) => link([r], why, targetOf)} problem={null} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <BulkBar count={chosen.length} noun="file" label="Link the picked files" onClear={() => setPicked(new Set())} testId="bulk-link-bar">
        <div className="bulk-where">
          <label className="only-mine">
            <input type="checkbox" checked={onePlace} onChange={(e) => setOnePlace(e.target.checked)} data-testid="bulk-link-one" />
            All to one place
          </label>
          {onePlace ? (
            <TargetFields row={{ own: { arm: null, batch: null, analyte: null } }} target={bulk} onTarget={setBulk} subjects={page.subjects}
                          analytes={page.analytes} keyId="bulk" context={`for the ${plural(chosen.length, "picked file")}`} />
          ) : (
            <ul className="bulk-targets">
              {picks.map((p) => <li key={p.row.sha}>{p.row.file} → {own(p.row) || targets[p.row.sha] ? whereText(p.target, page, p.row) : <em>not chosen yet</em>}</li>)}
            </ul>
          )}
        </div>
        {clash.length > 0 && (
          <div className="link-collision" role="alert" data-testid="link-collision">
            {clash.map((c) => (
              <p key={c.keys.join("|")} className="m-0">
                {c.files.length === 2 ? `${c.files[0]} and ${c.files[1]} both hold ${c.example}` : `${c.files[0]} holds ${c.example}, which study ${c.study} has in that arm already`}:
                {" "}in study {c.study} each file needs its own arm.
              </p>
            ))}
            <div className="row gap-6">
              {picks.filter((p) => clash.some((c) => c.keys.includes(p.row.sha))).map((p, _i, all) => (
                <label key={p.row.sha} className="delivery-pick">A new arm for {p.row.file}
                  <input type="text" maxLength={80} data-testid={`link-collision-arm-${p.row.fileId}`}
                         value={armNames[p.row.sha] ?? distinctWords(p.row.file, all.filter((x) => x !== p).map((x) => x.row.file))}
                         onChange={(e) => setArmNames((was) => ({ ...was, [p.row.sha]: e.target.value }))} />
                </label>
              ))}
              <button type="button" className="btn small" onClick={() => giveArms(clash)} data-testid="link-collision-apply">Give each its own arm</button>
            </div>
          </div>
        )}
        <ReasonForm action={chosen.length > 1 ? `Link ${plural(chosen.length, "file")}` : "Link"} kind="link" testId="bulk-link"
                    actionLabel={`Link the values of ${plural(chosen.length, "picked file")}`} label="Why the picked files' values belong there"
                    busy={busy} missing={bulkMissing} suggestions={reasons(chosen)} onSubmit={(why) => link(chosen, why)}
                    placeholder="reason, e.g. the file names say 230-23 (kept on the audit trail)" />
        {Object.keys(problems).length > 0 && (
          <ul className="bulk-problems" data-testid="bulk-link-problems">
            {rows.filter((r) => problems[r.sha]).map((r) => <li key={r.sha}>{r.file}: {problems[r.sha]}</li>)}
          </ul>
        )}
      </BulkBar>
    </div>
  );
}
