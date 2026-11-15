"use client";

// To do's "Link values to a study or product" (plan 2026-11-14 §2.1, §2.2.2, slice 4; the design text's `LinkTable`): one
// row per file whose values say no study or product (366 values in 6 files on the 9-file project: one row each, not one
// form per table and per fact), each with what it holds and where its values go: suggested from the file's own labels
// (its tables' titles and the lines read with them, its name), or asked first when the sheet form read it under a name
// that only starts with a delivery study's ("Same study as 230-23?": Yes fills that study and the arm that keeps the
// file apart). A file whose tables belong to different places (a workbook with one sheet per study) is split: each table,
// with the facts read beside it, goes where it says, suggested from its own title; the row's editor splits any file, or
// puts it back together. A row opens on its editor (the fill round's link form: study and arm, product and batch,
// analyte, each an existing one or a new one) and its values. Rows are picked and linked together from the bulk bar with
// one reason: each where its row says, or all to one place; one `values:assign` per destination.
// Before anything is sent, two files that hold the same subject in the same period are refused one arm of one study
// (§2.2.2), with "A new arm" for each offered right there, and so is a file whose subjects the study already holds in
// that arm: what the study holds is read from its card (the page's cache when it has just read it, else the card once),
// never taken as empty because the page has not read it. A refusal of the server is said on its row, in its words.
// Each answer is the page, written into the cache (writes.ts): a link costs the request and the one card it changed.

import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Problem, useDecide, type Page } from "@/components/delivery/shared";
import { LinkEditor, TargetFields } from "@/components/delivery/Unassigned";
import { writePage } from "@/components/delivery/writes";
import { BulkBar } from "@/components/kit/BulkBar";
import { focusAfter, focusSoon, nextRow } from "@/components/kit/focus";
import { announce } from "@/components/kit/LiveRegion";
import { ReasonForm } from "@/components/kit/Reason";
import { send } from "@/lib/api";
import { fetchResource, useResource, useResources } from "@/lib/hooks";
import {
  NEW, NO_TARGET, analyteChoice, analyteChoices, assignBody, collisions, destinationKey, distinctWords, heldBy, linkCount, linkRows, normLabel,
  targetProblem,
  type Collision, type Held, type LinkPart, type LinkPiece, type LinkRow, type LinkTarget, type Subject, type WorkItem,
} from "@/lib/inputsWork";
import { plural } from "@/lib/words";

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
const ASSIGN = "/api/v1/projects/{project_id}/delivery/values:assign" as const;
const CARD = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;
/** How long a card the page has just read stands for what the study holds when a link is sent (else it is read again). */
const FRESH = 10_000;

/** A piece of work going somewhere: a file (its row), or one of its tables when the file is split. */
type Send = { row: LinkPiece; target: LinkTarget };

/** Where a target sends the values, in words: "study 230-23 · arm Reference (new) · analyte Exampleamide". */
function whereText(t: LinkTarget, page: Page, row: Pick<LinkPiece, "own">): string {
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

/** A refusal of the collision guard, in words. */
function clashText(c: Collision): string {
  return `${c.files.length === 2 ? `${c.files[0]} and ${c.files[1]} both hold ${c.example}` : `${c.files[0]} holds ${c.example}, which study ${c.study} has in that arm already`}`
    + `: in study ${c.study} each file needs its own arm`;
}
/** The analyte ids a study's values carry (its card): of two analytes of one name, the one it uses is offered and sent. */
const analytesOf = (card: { tables: { values: { entity: Record<string, string> }[] }[] } | null | undefined) =>
  [...new Set((card?.tables ?? []).flatMap((t) => t.values.map((v) => v.entity.analyte)).filter((x): x is string => Boolean(x)))];
/** The bulk bar's "as the file says", naming what each picked file states (review gap 8: not "none stated" when it does). */
function asTheFilesSay(rows: LinkRow[]): string {
  const names = [...new Set(rows.map((r) => r.own.analyte?.label).filter((x): x is string => Boolean(x)))];
  const none = rows.some((r) => !r.own.analyte);
  if (!names.length) return "as the files say (none stated)";
  return `as ${rows.length > 1 ? "each file says" : "the file says"} (${names.join(", ")}${none ? "; none stated in some" : ""})`;
}
/** The studies a link would add individual values to (those it could mix with what they hold). */
const studiesOf = (sends: Send[]) => [...new Set(sends.filter((s) => s.row.pairs.length && s.target.study && s.target.study !== NEW).map((s) => s.target.study))].sort();
const rowOf = (key: string) => key.split("#")[0];
/** Past this many picked files, the bar folds where each goes under one line (the bar stays low over the rows). */
const LISTED = 2;

export function LinkTable({ projectId, items, subjects, heading, shared }: {
  projectId: string;
  /** the work model's link and alias items shown (To do's filters applied) */
  items: WorkItem[];
  subjects: Subject[];
  /** the group heading's element id: where the focus goes when the last row is linked */
  heading: string;
  /** the reason the group says once for every row: a row's chip says only a reason of its own (review CODE-9) */
  shared?: string;
}) {
  const page = useResource(DELIVERY, { project_id: projectId }).data;
  const client = useQueryClient();
  const { decide, busy } = useDecide();
  const rows = useMemo(() => linkRows(items, page, subjects), [items, page, subjects]);
  const [targets, setTargets] = useState<Record<string, LinkTarget>>({});
  const [partTargets, setPartTargets] = useState<Record<string, LinkTarget>>({});
  const [splitAt, setSplitAt] = useState<Record<string, boolean>>({});
  const [answers, setAnswers] = useState<Record<string, "yes" | "no">>({});
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [onePlace, setOnePlace] = useState(false);
  const [bulk, setBulk] = useState<LinkTarget>(NO_TARGET);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [armNames, setArmNames] = useState<Record<string, string>>({});
  const [checking, setChecking] = useState(false);

  // a row's target: what the person chose for it, else Yes to the alias question, else what its labels suggest
  const own = (r: LinkRow): LinkTarget | null => targets[r.sha] ?? (r.alias ? (answers[r.sha] === "yes" ? r.alias.target
    : answers[r.sha] === "no" && r.sheet ? { ...NO_TARGET, study: NEW, newStudy: r.sheet, analyte: r.own.analyte?.id ?? "" } : null)
    : r.suggested?.target ?? null);
  const targetOf = (r: LinkRow) => own(r) ?? { ...NO_TARGET, analyte: r.own.analyte?.id ?? "" };
  const suggested = (r: LinkRow) => !targets[r.sha] && own(r) !== null;
  const asking = (r: LinkRow) => Boolean(r.alias) && !answers[r.sha] && !targets[r.sha];
  // a file's tables to different places: as its tables' titles say, or as the person set it in the editor
  const isSplit = (r: LinkRow) => r.parts.length > 1 && (splitAt[r.sha] ?? r.split);
  // a table's target: the person's for it, else the file's they chose, else its own title's, else the file's suggestion
  const partTarget = (r: LinkRow, p: LinkPart): LinkTarget => partTargets[p.key] ?? targets[r.sha] ?? p.suggested?.target
    ?? own(r) ?? { ...NO_TARGET, analyte: p.own.analyte?.id ?? "" };
  const partSuggested = (r: LinkRow, p: LinkPart) => !partTargets[p.key] && !targets[r.sha] && Boolean(p.suggested);
  const sendsOf = (r: LinkRow): Send[] => (isSplit(r) ? r.parts.map((p) => ({ row: p, target: partTarget(r, p) })) : [{ row: r, target: targetOf(r) }]);
  const chosen = rows.filter((r) => picked.has(r.sha));
  const bulkSends = (r: LinkRow): Send[] => (onePlace ? [{ row: r, target: bulk }] : sendsOf(r));

  // what each study a row or the bulk bar sends individual values to holds already: its card, read while the row says
  // where it goes (never taken as empty because the page has not read it yet)
  const shown = [...rows.flatMap(sendsOf), ...(onePlace ? chosen.flatMap(bulkSends) : [])];
  const ids = studiesOf(shown);
  const cards = useResources(CARD, ids.map((subject) => ({ project_id: projectId, type: "study", subject })));
  const held: Held = Object.fromEntries(ids.flatMap((id, n) => (cards[n]?.data ? [[id, heldBy(cards[n].data)]] : [])));
  const usedBy: Record<string, string[]> = Object.fromEntries(ids.flatMap((id, n) => (cards[n]?.data ? [[id, analytesOf(cards[n].data)]] : [])));
  const reading = new Set(ids.filter((_, n) => !cards[n]?.data && !cards[n]?.problem));
  if (!page?.enabled || !rows.length) return null;
  // the page's subjects, and a study or product a link made before a re-read named that has no value left (review OWN-1)
  const earlier = rows.flatMap((r) => [r.before, ...r.parts.map((p) => p.before)]).flatMap((b) => b?.subjects ?? [])
    .filter((x, i, all) => !page.subjects.some((s) => s.subject === x.subject) && all.findIndex((y) => y.subject === x.subject) === i);
  const view: Page = earlier.length ? { ...page, subjects: [...page.subjects, ...earlier] } : page;
  const studies = view.subjects;
  const label = (id: string) => studies.find((s) => s.subject === id)?.label ?? id;
  const used = (study: string) => usedBy[study] ?? [];
  /** a target whose analyte is sent as the one of its name the study already uses (one analyte per name, review OWN-11) */
  const oneAnalyte = (row: LinkPiece, t: LinkTarget, uses: string[]): LinkTarget =>
    ({ ...t, analyte: analyteChoice(t.analyte, analyteChoices(page.analytes, row.own.analyte, uses), page.analytes, row.own.analyte) });

  const setTarget = (r: LinkRow, t: LinkTarget) => {
    setTargets((was) => ({ ...was, [r.sha]: t }));
    setProblems((was) => Object.fromEntries(Object.entries(was).filter(([sha]) => sha !== r.sha)));
  };
  const setPart = (r: LinkRow, p: LinkPart, t: LinkTarget) => {
    setPartTargets((was) => ({ ...was, [p.key]: t }));
    setProblems((was) => Object.fromEntries(Object.entries(was).filter(([sha]) => sha !== r.sha)));
  };
  const guard = (sends: Send[]): Collision[] => collisions(sends, studies, held, page?.analytes);

  /** Link the rows, one `values:assign` per destination; a name made by an earlier call of the batch is used by its id.
   *  First what each study holds is read (its card, unless the page read it a moment ago) and the guard is run on it. */
  async function link(list: LinkRow[], why: string, plan: (r: LinkRow) => Send[]): Promise<boolean> {
    const sends = list.flatMap((r) => plan(r).map((s) => ({ ...s, of: r })));
    const check = studiesOf(sends);
    let now: Held = {};
    let uses: Record<string, string[]> = {};
    if (check.length) {
      setChecking(true);
      try {
        const read = await Promise.all(check.map((subject) => fetchResource(client, CARD, { project_id: projectId, type: "study", subject }, FRESH)));
        now = Object.fromEntries(check.map((id, n) => [id, heldBy(read[n])]));
        uses = Object.fromEntries(check.map((id, n) => [id, analytesOf(read[n])]));
      } catch (e) {
        const text = `What study ${check.map(label).join(", ")} holds could not be read, so its arms are not checked: nothing was linked. Try again.`
          + ` (${e instanceof Error ? e.message : String(e)})`;
        // said by each row's alert, not a second time in the live region (final review A11Y-6)
        setProblems((was) => ({ ...was, ...Object.fromEntries(list.map((r) => [r.sha, text])) }));
        return false;
      } finally {
        setChecking(false);
      }
    }
    const clash = collisions(sends, studies, now, page?.analytes);
    if (clash.length) {
      const said = Object.fromEntries(list.flatMap((r) => {
        const c = clash.find((x) => x.keys.some((k) => rowOf(k) === r.sha));
        return c ? [[r.sha, `${clashText(c)}. Nothing was linked.`]] : [];
      }));
      setProblems((was) => ({ ...was, ...said }));
      return false;
    }
    const groups = new Map<string, { target: LinkTarget; sends: typeof sends }>();
    for (const s of sends) {
      const target = oneAnalyte(s.row, s.target, uses[s.target.study] ?? used(s.target.study));
      const key = destinationKey(target);
      groups.set(key, { target, sends: [...(groups.get(key)?.sends ?? []), s] });
    }
    const order = rows.map((r) => `link-${r.fileId}`);
    let current = page!;
    const failed: Record<string, string> = {};
    for (const g of groups.values()) {
      const target = made(g.target, page!, current);
      const { data, problem } = await decide(() => send("post", ASSIGN, { project_id: projectId },
        assignBody(target, g.sends.flatMap((s) => s.row.values.map((v) => v.id)), why)), {});
      if (data) {
        writePage(client, projectId, data);
        current = data;
      } else for (const s of g.sends) failed[s.of.sha] = problem ?? "It was not linked.";
    }
    const done = list.filter((r) => !failed[r.sha]);
    setProblems((was) => ({ ...Object.fromEntries(Object.entries(was).filter(([sha]) => !done.some((r) => r.sha === sha))), ...failed }));
    setPicked((was) => new Set([...was].filter((s) => !done.some((r) => r.sha === s))));
    if (done.length) {
      const left = rows.length - done.length;
      // where each went, as the page now holds it: a study or arm the batch made is named as it now is, not "(new)" (CODE-10)
      const whereOf = (r: LinkRow) => [...new Set(plan(r).map((s) => whereText(made(s.target, page!, current), current, s.row)))].join(" and ");
      announce(`${done.map((r) => r.file).join(", ")} linked to ${[...new Set(done.map(whereOf))].join("; ")}. `
        + `${left ? `${plural(left, "file")} left to link.` : "Every file is linked."}${Object.keys(failed).length ? ` ${plural(Object.keys(failed).length, "file")} not linked: see its row.` : ""}`);
      const decided = done.map((r) => `link-${r.fileId}`);
      focusAfter(decided, nextRow(order, decided), [heading, "todo-title"]);
      setOnePlace(false);
      if (done.some((r) => r.sha === open)) setOpen(null);
    }
    return done.length === list.length;
  }

  // what the picked rows still need, and the arms that would mix two files' subjects
  const picks = chosen.flatMap(bulkSends);
  const clash = guard(picks);
  const lacking = picks.map((p) => [p.row, targetProblem(p.target, page.analytes)] as const).filter(([, m]) => m);
  const bulkMissing = lacking.length ? `${lacking[0][0].name}: ${lacking[0][1]}` : clash.length ? "Give each file its own arm first (above)" : null;
  const reasons = (list: LinkRow[]) => [...new Set(list.flatMap((r) => [
    answers[r.sha] === "yes" && r.alias ? `the sheet form read it as ${r.sheet}, a part of study ${r.alias.study.label}` : "",
    !isSplit(r) && suggested(r) && r.suggested ? `${r.suggested.why.replace(/^its/, "the file's")}` : "",
    ...(isSplit(r) ? r.parts.filter((p) => partSuggested(r, p)).map((p) => `${p.place || p.label}: ${p.suggested!.why.replace(/^its/, "the table's")}`) : []),
  ]).filter(Boolean))].slice(0, 3);
  const giveArms = (c: Collision[]) => {
    const keys = new Set(c.flatMap((x) => x.keys));
    const clashing = picks.filter((p) => keys.has(p.row.key));
    for (const p of clashing) {
      const name = armNames[p.row.key] ?? distinctWords(p.row.name, clashing.filter((x) => x !== p).map((x) => x.row.name));
      const t = { ...p.target, arm: NEW, newArm: name };
      if (p.row.key === p.row.sha) setTargets((was) => ({ ...was, [p.row.sha]: t }));
      else setPartTargets((was) => ({ ...was, [p.row.key]: t }));
    }
    setOnePlace(false);
  };
  const allPicked = rows.every((r) => picked.has(r.sha));
  const targetList = (
    <ul className="bulk-targets">
      {chosen.map((r) => (
        <li key={r.sha}>{r.file} → {isSplit(r)
          ? r.parts.map((p) => `${p.place || p.label}: ${targetProblem(partTarget(r, p)) === "Pick a study or a product" ? "not chosen yet" : whereText(partTarget(r, p), view, p)}`).join("; ")
          : own(r) || targets[r.sha] ? whereText(targetOf(r), view, r) : <em>not chosen yet</em>}</li>
      ))}
    </ul>
  );
  const holdsText = (sends: Send[]) => {
    const c = guard(sends)[0];
    return c ? `${c.example} is in study ${c.study} in that arm already` : null;
  };
  const readingText = (sends: Send[]) => {
    const waiting = studiesOf(sends).filter((id) => reading.has(id));
    return waiting.length ? `checking what study ${waiting.map(label).join(", ")} holds…` : null;
  };

  return (
    <div className="batch link-table" data-testid="link-table">
      <div className="batch-head">
        <label className="batch-all">
          <input type="checkbox" checked={allPicked} ref={(el) => { if (el) el.indeterminate = !allPicked && picked.size > 0; }}
                 onChange={() => setPicked(allPicked ? new Set() : new Set(rows.map((r) => r.sha)))} data-testid="link-pick-all" />
          Pick every file
        </label>
        <span className="muted" data-testid="link-table-count">{plural(rows.length, "file")} · {linkCount(rows.flatMap((r) => r.values))}</span>
      </div>
      <ul className="batch-rows">
        {rows.map((r) => {
          const t = targetOf(r);
          const split = isSplit(r);
          const context = `${linkCount(r.values)} of ${r.file}`;
          const sends = sendsOf(r);
          const rowClash = holdsText(sends);
          const wait = readingText(sends);
          const missing = sends.map((s) => [s, targetProblem(s.target, page.analytes)] as const).find(([, m]) => m);
          return (
            <li key={r.sha} className={`batch-row${open === r.sha ? " open" : ""}`} data-testid={`link-${r.fileId}`}>
              <div className="batch-line">
                <input type="checkbox" checked={picked.has(r.sha)} aria-label={`Pick the ${context}`} data-testid={`link-pick-${r.fileId}`}
                       onChange={() => setPicked((was) => { const n = new Set(was); if (!n.delete(r.sha)) n.add(r.sha); return n; })} />
                <div className="batch-what">
                  <strong>{r.file}</strong>
                  <span className="muted">{r.holds}</span>
                  {r.item.why && r.item.group !== "tidy" && r.item.why !== shared && <span className="chip neutral" title={r.item.why}>holds up nothing yet</span>}
                </div>
                <div className="batch-where" data-testid={`link-to-${r.fileId}`}>
                  {asking(r) && !split ? (
                    <span className="link-ask">
                      <span>The sheet form read it as {r.sheet}.</span>{" "}
                      <span className="link-ask-q">
                        <strong>Same study as {r.alias!.study.label}?</strong>
                        <button type="button" className="btn small" data-testid={`link-alias-yes-${r.fileId}`}
                                aria-label={`Yes: the ${context} are study ${r.alias!.study.label}`}
                                onClick={() => { setAnswers((was) => ({ ...was, [r.sha]: "yes" })); focusSoon(`link-open-${r.fileId}`); }}>Yes</button>
                        <button type="button" className="btn small" data-testid={`link-alias-no-${r.fileId}`}
                                aria-label={`No: the ${context} are not study ${r.alias!.study.label}`}
                                onClick={() => { setAnswers((was) => ({ ...was, [r.sha]: "no" })); focusSoon(`link-open-${r.fileId}`); }}>No</button>
                      </span>
                    </span>
                  ) : split ? (
                    <ul className="link-parts-where">
                      {r.parts.map((p, n) => {
                        const pt = partTarget(r, p);
                        return (
                          <li key={p.key} data-testid={`link-to-${r.fileId}-${n}`}>
                            <span className="muted">{p.place || p.label}:</span>{" "}
                            {targetProblem(pt) === "Pick a study or a product" ? <span className="muted">not chosen yet</span> : <span>→ {whereText(pt, view, p)}</span>}
                            {partSuggested(r, p) && <span className="chip neutral" title={p.suggested!.why}>suggested</span>}
                          </li>
                        );
                      })}
                    </ul>
                  ) : own(r) ? (
                    <>
                      <span>→ {whereText(t, view, r)}</span>
                      {suggested(r) && <span className="chip neutral" title={r.suggested?.why ?? (answers[r.sha] === "yes" ? "you said it is the same study" : "the sheet form's name")}>suggested</span>}
                    </>
                  ) : <span className="muted">not chosen yet{r.sheet ? ` · the sheet form read it as ${r.sheet}` : ""}</span>}
                  {wait && <span className="muted link-checking" data-testid={`link-checking-${r.fileId}`}>{wait}</span>}
                  {/* linked before a re-read of its table, and that link not carried over: said, and the row filled with it */}
                  {[r.before, ...(r.before ? [] : r.parts.map((p) => p.before))].filter((b) => b !== null).map((b, n) => (
                    <span key={n} className="muted link-before" data-testid={`link-before-${r.fileId}`}>{b!.note}</span>
                  ))}
                  {rowClash && <span className="link-clash">{rowClash}: give it an arm of its own</span>}
                </div>
                <button type="button" className="btn small" aria-expanded={open === r.sha} aria-controls={`link-editor-${r.fileId}`}
                        aria-label={`${open === r.sha ? "Close" : "Choose"} where the ${context} go`} data-testid={`link-open-${r.fileId}`}
                        onClick={() => setOpen(open === r.sha ? null : r.sha)}>{open === r.sha ? "Close" : "Edit…"}</button>
              </div>
              <Problem text={problems[r.sha] ?? null} testId={`link-row-problem-${r.fileId}`} />
              {open === r.sha && (
                <div id={`link-editor-${r.fileId}`}>
                  <LinkEditor projectId={projectId} row={r} target={t} onTarget={(x) => setTarget(r, x)} subjects={studies} analytes={page.analytes}
                              busy={busy || checking} used={used}
                              missing={missing ? (split ? `${missing[0].row.name}: ${missing[1]}` : missing[1])
                                : rowClash ? `${rowClash}: choose another arm` : null}
                              split={r.parts.length > 1 ? {
                                on: split, set: (on) => setSplitAt((was) => ({ ...was, [r.sha]: on })),
                                target: (p) => partTarget(r, p), onTarget: (p, x) => setPart(r, p, x),
                              } : undefined}
                              suggestions={reasons([r])} onLink={(why) => link([r], why, sendsOf)} problem={null} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <BulkBar count={chosen.length} noun="file" label="Link the picked files" onClear={() => setPicked(new Set())} testId="bulk-link-bar"
               clearLabel="Clear the files picked to link" after={["link-pick-all"]}>
        <div className="bulk-where">
          <label className="only-mine">
            <input type="checkbox" checked={onePlace} onChange={(e) => setOnePlace(e.target.checked)} data-testid="bulk-link-one" />
            All to one place
          </label>
          {onePlace ? (
            <TargetFields row={{ own: { arm: null, batch: null, analyte: null } }} target={bulk} onTarget={setBulk} subjects={studies}
                          analytes={page.analytes} keyId="bulk" context={`for the ${plural(chosen.length, "picked file")}`}
                          used={used(bulk.study)} noneAnalyte={asTheFilesSay(chosen)} />
          ) : chosen.length <= LISTED ? targetList : (
            <details className="bulk-targets-fold" data-testid="bulk-link-where">
              <summary>Where each of the {chosen.length} files goes</summary>
              {targetList}
            </details>
          )}
        </div>
        {onePlace && readingText(picks) && <p className="muted m-0 link-checking">{readingText(picks)}</p>}
        {clash.length > 0 && (
          <div className="link-collision" role="alert" data-testid="link-collision">
            {clash.map((c) => <p key={c.keys.join("|")} className="m-0">{clashText(c)}.</p>)}
            <div className="row gap-6">
              {picks.filter((p) => clash.some((c) => c.keys.includes(p.row.key))).map((p, _i, all) => (
                <label key={p.row.key} className="delivery-pick">A new arm for {p.row.name}
                  <input type="text" maxLength={80} data-testid={`link-collision-arm-${p.row.key === p.row.sha ? rows.find((r) => r.sha === p.row.sha)?.fileId : p.row.key.replace(/[^A-Za-z0-9-]/g, "-")}`}
                         value={armNames[p.row.key] ?? distinctWords(p.row.name, all.filter((x) => x !== p).map((x) => x.row.name))}
                         onChange={(e) => setArmNames((was) => ({ ...was, [p.row.key]: e.target.value }))} />
                </label>
              ))}
              <button type="button" className="btn small" onClick={() => giveArms(clash)} data-testid="link-collision-apply">Give each its own arm</button>
            </div>
          </div>
        )}
        <ReasonForm action={chosen.length > 1 ? `Link ${plural(chosen.length, "file")}` : "Link"} kind="link" testId="bulk-link"
                    actionLabel={`Link the values of ${plural(chosen.length, "picked file")}`} label="Why the picked files' values belong there"
                    busy={busy || checking} missing={bulkMissing} suggestions={reasons(chosen)} onSubmit={(why) => link(chosen, why, bulkSends)}
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
