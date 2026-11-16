"use client";

// One card per study, product and compound, whichever reader found it (plan 2026-11-14 §2 rule 3, §2.1, §2.2.1; slice 3):
// the delivery's subject and the sheet form's group of the same study are one card (joined by lib/inputsWork.ts, never a
// silent merge), with one confirm path chosen by `confirm_on`. The card reads, top to bottom: what is to do on it, its
// facts, its observed data, its files and tables, its checks, what is not loaded with it, the one confirmation, and how
// the files were read by the other reader (folded, read-only). A card confirmed on the delivery whose study the sheet
// form also read offers both paths in the card itself: while the delivery's clean-up holds "Confirm and sign", "Confirm
// now with the sheet form" is beside it, and whichever is confirmed first is what loads; it says that it is not signed
// (it records who confirmed and when), where "Confirm and sign" is (final review INT-7: the two paths have different Part
// 11 controls, an open decision for the owner, plan §5). A study the delivery blinds (D-15) offers no sheet-form path,
// and the sheet form's reading of it is withheld (final review INT-2). The clean-up itself (the per-delivery gate,
// contracts §11.10) is not changed here.

import { useEffect, useRef, useState, type ReactNode } from "react";

import { BlindedReason, focusWhenDrawn } from "@/components/delivery/BlindedReason";
import { DeliveryReview, SUBJECT } from "@/components/delivery/DeliveryReview";
import type { Suggestions } from "@/components/delivery/FactsForm";
import { MappingReview, type MappingOpen } from "@/components/delivery/MappingReview";
import type { Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { blindedWhy, cardAnchor, cardPlace, type Subject, type WorkItem, type WorkModel } from "@/lib/inputsWork";
import { AREA_NAME, STATUS_TONE, STATUS_WORD, type Status, type Tab, plural, whenText } from "@/lib/words";

import { GroupCard, openText } from "../ClientConfirm";
import type { Run } from "../InputsTodo";

type Group = Schema<"ReviewGroup">;
type Card = Schema<"DeliverySubject">;

/** A sheet's need (the sheet form's names) and the intake field the delivery card states it under. */
const NEED_OF: Record<string, string> = {
  n: "n", dose: "dose", formulation: "formulation", intended_use: "purpose", food_state: "food_state", route: "route",
  infusion_time_min: "infusion_time_min",
};

/** The facts a delivery card states already (entered by a person or read from its files), by the sheet form's need
 *  names: offered to the sheets of the same study when the person takes the sheet form's path, so nothing entered on
 *  the card is asked again (final review OWN-14). A dose only in mg, as the sheet form takes it. */
export function knownFacts(card: Card | null | undefined): Record<string, { value: string; from: string }> {
  const out: Record<string, { value: string; from: string }> = {};
  for (const t of card?.tables ?? []) {
    for (const v of t.values) {
      const need = NEED_OF[v.field];
      if (!need || v.value === null || v.blinded || v.status === "superseded" || v.status === "excluded") continue;
      if (v.field === "dose" && (v.unit ?? "mg").trim().toLowerCase() !== "mg") continue;
      if (out[need] && v.method !== "person") continue;               // a person's entry is the one offered
      out[need] = { value: String(v.value), from: v.method === "person" ? "entered on the study's card" : `stated in ${t.file ?? "its file"}` };
    }
  }
  return out;
}

/** Where a card was asked to open from (a To do row, "Next", a link): by its key, its delivery subject
 *  (`${type}/${subject}`) or its sheet-form group, and the element to bring into view in it. */
export type CardFocus = { key?: string; ref?: string; group?: string; anchor?: string; at: number };

/** What every card needs from the page: the one list of work, how to open an item where it is settled, and To do. */
export type CardEnv = {
  projectId: string; work: WorkModel; run: Run;
  onGo: (item: WorkItem) => void;
  /** open To do (the delivery's clean-up is worked there) */
  onTodo: () => void;
  focus?: CardFocus | null;
  /** a client file's name, by its id (a card's files) */
  fileName?: (id: string) => string | null;
  /** open a client file's row in Client files */
  onFile?: (id: string) => void;
  /** open "Add data" on the formulation and dissolution files, for a product (its card's release line: round 5) */
  onAddData?: (product: string) => void;
};

/** A card's own items in the one list of work: from its delivery card (facts, required items, checks, disagreements,
 *  links, other reasons) and from its sheet form (disagreements, sheets that do not say a fact). */
const CARD_ITEMS = /^(fact|need|individual|check|differ|same|hold|issue|draft):/;
const cardItems = (s: Subject, work: WorkModel) => work.items.filter((i) => i.subjects.includes(s.key) && i.status !== "done" && CARD_ITEMS.test(i.id));

const ref = (s: Subject) => (s.row ? `${s.row.subject_type}/${s.row.subject}` : null);
/** Whether `focus` asks for this card. */
export const focused = (s: Subject, focus: CardFocus | null | undefined) => Boolean(focus && (
  (focus.key && focus.key === s.key) || (focus.ref && focus.ref === ref(s)) || (focus.group && s.groups.some((g) => g.id === focus.group))));

/** A card confirmed on the delivery whose study, product or compound the sheet form confirmed first (whichever is
 *  confirmed first is what loads, plan §2.2.1): it then reads as a card confirmed with the sheet form, the delivery's
 *  reading folded under it for reference, never its forms. A card signed on the delivery is never one (its signature
 *  marks the sheet form's group confirmed too, and its dialog stays open while it loads). */
export const viaSheet = (s: Subject) => s.path === "delivery" && s.groups.some((g) => g.state === "confirmed") && !s.row?.confirmation;

/** The card's one status word: Done once confirmed; else the most pressing of its open items (Missing, then To decide),
 *  else To confirm. */
export function cardStatus(s: Subject, work: WorkModel): Status {
  const open = work.items.filter((i) => i.open && i.subjects.includes(s.key) && !i.id.startsWith("confirm:"));
  // confirmed, with work of the model's still open on it (a product whose release a tablet study needs: OWN-10)
  if (s.done) return open.some((i) => i.status === "to_decide") ? "to_decide" : "done";
  return open.some((i) => i.status === "missing") ? "missing" : open.some((i) => i.status === "to_decide") ? "to_decide" : "to_confirm";
}

export function StatusChip({ status, testId }: { status: Status; testId?: string }) {
  return <span className={`chip ${STATUS_TONE[status]}`} data-testid={testId}>{STATUS_WORD[status]}</span>;
}

/** What is open on the card, one line each, opening where it is settled on the card; the delivery's clean-up (layouts,
 *  values to link, numbers not read) is said once, as the gate line. */
export function CardTodo({ subject, env }: { subject: Subject; env: CardEnv }) {
  const items = cardItems(subject, env.work);
  if (!items.length) return null;
  const name = new RegExp(`^(Study|Product|Compound) ${subject.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}( · |: )`);
  const line = (i: WorkItem, text: string) => (
    <li key={i.id} className={i.open ? undefined : "quiet"}>
      <StatusChip status={i.status} />
      {/* the card's name is left off the line, not off its name: every card lists the same kinds of work (round 4) */}
      <button type="button" className="link-btn" onClick={() => env.onGo(i)} data-testid={`card-todo-${i.id}`}
              aria-label={`${text} (${subject.kind} ${subject.label})`}>{text}</button>
      {(i.blocked || i.why) && <span className="muted fs-12">{i.blocked ?? i.why}</span>}
    </li>
  );
  // the files' disagreements by whom they are about (review INT-10): "Subject 001, period I (11)", each time under it
  const about = new Map<string, WorkItem[]>();
  for (const i of items) if (i.about) about.set(i.about, [...(about.get(i.about) ?? []), i]);
  const grouped = new Set([...about.values()].filter((l) => l.length > 1).flat());
  return (
    <ul className="card-todo" data-testid={`card-todo-${subject.key}`}>
      {items.filter((i) => !grouped.has(i)).map((i) => line(i, i.label.replace(name, "")))}
      {[...about.entries()].filter(([, l]) => l.length > 1).map(([who, list]) => (
        <li key={who} className="card-todo-group" data-testid={`card-todo-about-${subject.key}-${who.replace(/[^A-Za-z0-9-]/g, "-")}`}>
          <details open={list.some((i) => i.open) && about.size <= 3}>
            <summary>{who.charAt(0).toUpperCase() + who.slice(1)}: {plural(list.length, "disagreement")}</summary>
            <ul className="card-todo">{list.map((i) => line(i, i.label.replace(name, "").replace(`, ${who}`, "")))}</ul>
          </details>
        </li>
      ))}
    </ul>
  );
}

/** The other reader's view of the same data, folded and read-only: drawn only once opened. */
export function HowRead({ subject, title, open, onOpen, children }: {
  subject: Subject; title: string; open: boolean; onOpen: (open: boolean) => void; children: () => ReactNode;
}) {
  return (
    <details className="how-read" data-testid={`how-read-${subject.key}`} open={open}
             onToggle={(e) => { const now = (e.currentTarget as HTMLDetailsElement).open; if (now !== open) onOpen(now); }}>
      <summary><span className="todo-caret" aria-hidden="true" />How the files were read: {title}</summary>
      {open && <div className="how-read-body">{children()}</div>}
    </details>
  );
}

/** The sheet form's answers for the facts no file states, by the intake field they are entered under: its groups'
 *  facts and the answers it pre-filled or was given for a sheet. */
export function suggestionsOf(groups: Group[]): Suggestions {
  const out: Suggestions = {};
  const field = (name: string) => (name === "purpose" ? "intended_use" : name === "dose_mg" ? "dose" : name);
  const add = (name: string, value: unknown, from: string) => {
    if (value === null || value === undefined || value === "") return;
    const f = field(name);
    const v = String(value);
    if (!(out[f] ??= []).some((x) => x.value === v)) out[f].push({ value: v, from });
  };
  for (const g of groups.filter((x) => !x.blinded)) {      // a group the delivery blinds offers nothing (D-15)
    for (const f of g.facts) add(f.field, typeof f.stored === "string" || typeof f.stored === "number" ? f.stored : f.value, `${g.title}: ${f.label}`);
    for (const i of g.items.filter((x) => x.kind === "draft")) {
      const d = i.draft as { answers?: Record<string, string>; prefill?: Record<string, string>; sheet?: string } | null | undefined;
      for (const [k, v] of Object.entries({ ...(d?.prefill ?? {}), ...(d?.answers ?? {}) })) add(k, v, `${g.title}, sheet ${d?.sheet ?? i.label}`);
    }
  }
  return out;
}

/** Who confirmed the card and when, what it put in the model and where it is now; or that it changed since it was
 *  signed. */
function InModel({ subject, onShow }: { subject: Subject; onShow?: () => void }) {
  const c = subject.row?.confirmation;
  const g = subject.groups.find((x) => x.state === "confirmed");
  if (c && !c.current) {
    return <p className="card-loaded changed" data-testid={`card-changed-${subject.key}`}>Changed since signed by {c.printed_name || c.by} on
      {" "}{whenText(c.at)}: confirm again. What changed since, with who, when and why, is under Confirm and sign.</p>;
  }
  if (!subject.done) return null;
  const who = c?.current && c.landed ? `Signed by ${c.printed_name || c.by} on ${whenText(c.at)}`
    : g ? `Confirmed with the sheet form by ${g.confirmed_by ?? "a person"}${g.confirmed_at ? ` on ${whenText(g.confirmed_at)}` : ""}` : "Confirmed";
  // what the signature's landing loaded (the signing dialog's and the status line's count), else what the sheet form
  // confirmed (final review, owner-job gap 3: one source for each count)
  const datasets = c?.current && c.landed ? c.landed_datasets.length : g ? g.items.filter((i) => i.data).length : 0;
  return (
    <p className="card-loaded" data-testid={`card-loaded-${subject.key}`}>
      <StatusChip status="done" /> {who}.{" "}
      {/* a product's data are its dissolution: its release is said on its own line (OWN-10) */}
      {subject.kind === "product" ? "Its data are in the model; whether they set a formulation's release is said above"
        : `In the model${datasets ? `: ${plural(datasets, "dataset")}` : ""}`}
      {c?.landed ? " (what was loaded and held back is under Confirm and sign)" : ""}.{" "}
      {onShow && <button type="button" className="link-btn" onClick={onShow} data-testid={`card-in-model-${subject.key}`}>Show it in the model</button>}
    </p>
  );
}

/** The card's body: its confirm path (the delivery's review with "Confirm and sign", or the sheet form's group with
 *  "Confirm"), the other reader's view folded under it, and what the card adds of its own (`observed`: its data in the
 *  model; `files`: its files). */
export function ConfirmPath({ subject: s, env, observed, files, onShow }: {
  subject: Subject; env: CardEnv; observed?: ReactNode; files?: ReactNode;
  /** bring what the card put in the model into view */
  onShow?: () => void;
}) {
  const [mapping, setMapping] = useState<MappingOpen | null>(null);
  const [reading, setReading] = useState(false);       // the other reader's view, opened
  const [sheet, setSheet] = useState(false);           // the sheet form's path, chosen on a card confirmed on the delivery
  const body = useRef<HTMLDivElement>(null);
  const { projectId, run, work, focus } = env;
  // the path the card is read on: a card the sheet form confirmed first is a sheet-form card from then on
  const path = viaSheet(s) ? "sheet-form" : s.path;
  // a study the delivery blinds (D-15): nothing of it is read or confirmed with the sheet form until the plan is signed
  // (the API refuses it, 409 BLINDED), and the sheet form's reading of it is not shown
  const blinded = Boolean(s.row?.blinded || s.groups.some((g) => g.blinded));
  // why it is blinded, said wherever it is withheld (round 4): the delivery's reason, else the sheet form's group's; the
  // part that can be changed leads where it is changed (round 5): the study's purpose on its delivery card (on a card
  // confirmed with the sheet form, in the delivery's reading, opened first), or the plan's roles
  const why = blindedWhy(s);
  const toPurpose = s.row ? () => { if (path !== "delivery") setReading(true); focusWhenDrawn(cardPlace("purpose", s.row!.subject, "intended_use")); } : undefined;
  const because = why ? <>, because <BlindedReason why={why} projectId={projectId} onPurpose={toPurpose} whose={`${s.kind} ${s.label}`} /></> : null;
  // what a withheld reading is, in its card's words: a study is blinded, with why; a product or the compound holds the values
  // of a blinded study, said once on its card's head with the study (round 6: "the study is blinded" on a product's card,
  // and the reason twice), so here only what is withheld
  const withheld = (reader: string) => (s.kind === "study"
    ? <>Withheld: the study is blinded until the plan is signed{because}, and {reader}&apos;s reading shows its values.</>
    : <>Withheld until the plan is signed: {reader}&apos;s reading shows the values it holds of a blinded study.</>);
  // the delivery card's facts (the card reads the same, under the same key), offered to the sheets' drafts
  const card = useResource(SUBJECT, { project_id: projectId, type: s.row?.subject_type ?? "study", subject: s.row?.subject ?? "" },
                           { enabled: Boolean(s.row) && !blinded && s.groups.some((g) => g.items.some((i) => i.kind === "draft")) });
  const known = blinded ? {} : knownFacts(card.data);
  const toConfirm = blinded ? [] : s.groups.filter((g) => g.state === "to_confirm" && g.kind !== "sheet");
  // a To do row that opens a sheet-form item (a sheet to read, a disagreement) of a card confirmed on the delivery opens
  // the sheet form's path there, where it is settled
  useEffect(() => {
    if (!focus || !focused(s, focus) || path !== "delivery") return;
    const inside = focus.anchor && (focus.anchor.startsWith("issue-") || focus.anchor.startsWith("group-"));
    if (inside || focus.group) { setReading(true); setSheet(true); }
  }, [focus]); // eslint-disable-line react-hooks/exhaustive-deps
  const confirmItem = work.items.find((i) => i.id === `confirm:${s.key}`);
  const gate = { text: confirmItem?.gate ?? null, owner: confirmItem?.owner ?? null, onOpen: env.onTodo };
  const todo = <CardTodo subject={s} env={env} />;
  const sheetPath = toConfirm.length ? (gated: boolean) => (
    <span className="sheet-path">
      <button type="button" className="btn" data-testid={`confirm-sheet-${s.key}`} aria-expanded={sheet}
              aria-label={`${gated ? "Confirm now with the sheet form" : "Confirm with the sheet form instead"}: ${s.kind} ${s.label}`}
              onClick={() => { setReading(true); setSheet(true);
                               window.setTimeout(() => body.current?.querySelector(".how-read")?.scrollIntoView({ block: "start", behavior: "smooth" }), 60); }}>
        {gated ? "Confirm now with the sheet form" : "Confirm with the sheet form instead"}</button>
      <span className="muted fs-13" data-testid={`confirm-sheet-note-${s.key}`}>Not signed: the sheet form records who confirmed and when,
        where Confirm and sign records your signature. Whichever is confirmed first is what loads; nothing is loaded twice.
        {toConfirm.some((g) => g.open) ? ` The sheet form has ${openText(toConfirm[0]) || "items"} first.` : ""}</span>
    </span>
  ) : undefined;

  return (
    <div className="card-body" ref={body}>
      <InModel subject={s} onShow={onShow} />
      {path === "delivery" && s.row && (
        <DeliveryReview projectId={projectId} row={s.row} mode="confirm" gate={gate} onMapping={setMapping} todo={todo}
                        suggestions={blinded ? {} : suggestionsOf(s.groups)} observed={observed} sheetPath={sheetPath}
                        howRead={s.groups.length > 0 ? (
                          <HowRead subject={s} title={sheet ? "the sheet form, to confirm it this way" : "the sheet form (for reference)"}
                                   open={reading} onOpen={setReading}>
                            {() => (blinded
                              ? <p className="delivery-withheld m-0" data-testid={`how-read-withheld-${s.key}`}>{withheld("the sheet form")} It is
                                  read and confirmed once the plan is signed.</p>
                              : s.groups.map((g) => <GroupCard key={g.id} projectId={projectId} group={g} run={run} drawn={false}
                                                               mode={sheet && g.state === "to_confirm" ? "confirm" : "read"} alsoOnDelivery
                                                               known={known} />))}
                          </HowRead>
                        ) : undefined} />
      )}
      {path === "sheet-form" && (
        <>
          {!s.done && (
            <section className="card-section" data-testid={`card-todo-section-${s.key}`}>
              <h3 className="card-section-title">To do on this {s.kind === "compound" ? "compound" : s.kind}</h3>
              {cardItems(s, work).length ? todo : <p className="muted m-0">Nothing open: it is ready to confirm.</p>}
            </section>
          )}
          {observed}
          {s.groups.map((g) => <GroupCard key={g.id} projectId={projectId} group={g} run={run} files={files} confirmedSaid={s.done}
                                          known={known} why={why} onPurpose={toPurpose} />)}
          {s.row && (
            <HowRead subject={s} title="the delivery (for reference)" open={reading} onOpen={setReading}>
              {/* a study the project blinds (D-15) that the delivery does not: its reading is not shown until the plan is signed */}
              {() => (s.blinded && !s.row!.blinded
                ? <p className="delivery-withheld m-0" data-testid={`how-read-withheld-${s.key}`}>{withheld("the delivery")}</p>
                : <DeliveryReview projectId={projectId} row={s.row!} mode="read" onMapping={setMapping} />)}
            </HowRead>
          )}
        </>
      )}
      {path === "read-only" && s.row && (
        <>
          <p className="inline-issue note" data-testid={`card-read-only-${s.key}`}>A filled client-data template: it is confirmed with the
            sheet form on this card, which is not available yet. Read the file again from Client files. The delivery&apos;s reading is shown
            for reference.</p>
          {s.blinded && !s.row.blinded
            ? <p className="delivery-withheld m-0" data-testid={`how-read-withheld-${s.key}`}>{withheld("the delivery")}</p>
            : <DeliveryReview projectId={projectId} row={s.row} mode="read" onMapping={setMapping} />}
        </>
      )}
      {mapping && <MappingReview projectId={projectId} mappingId={mapping.id} version={mapping.version} at={mapping.at} onClose={() => setMapping(null)}
                                 onStored={(version) => setMapping((was) => (was ? { ...was, version } : was))} />}
    </div>
  );
}

/** A card's head, where the card is not a row of a list (products, the compound): its name, the names the other reader
 *  gave it, its one status and the control that opens it. */
export function CardHead({ subject: s, status, open, onToggle, children }: {
  subject: Subject; status: Status; open: boolean; onToggle: () => void; children?: ReactNode;
}) {
  const toggle = s.path === "delivery" || !s.groups[0] ? `delivery-subject-open-${s.row?.subject ?? s.key}` : `toggle-${s.groups[0].id}`;
  // why it is blinded, beside the chip (round 5: the chip said only that it is), and its description
  const why = s.blinded ? blindedWhy(s) : null;
  const whyId = `${cardAnchor(s)}-blinded-why`;
  return (
    <header className="card-head">
      <button type="button" className="card-toggle" aria-expanded={open} aria-controls={`${cardAnchor(s)}-body`} onClick={onToggle}
              data-testid={toggle}>
        <span className="card-title">{s.label}</span>
      </button>
      {s.aliases.length > 0 && <span className="muted fs-13">also read as {s.aliases.join(", ")} by the sheet form</span>}
      <StatusChip status={status} testId={`card-status-${s.key}`} />
      {s.blinded && <span className="chip neutral" data-testid={`card-blinded-${s.key}`} aria-describedby={why ? whyId : undefined}>blinded
        until the plan is signed</span>}
      {why && <span className="muted fs-12" id={whyId} data-testid={`card-blinded-why-${s.key}`}>because {why}</span>}
      {children}
      <span className="muted fs-13 card-path">{viaSheet(s) ? "Confirmed with the sheet form" : s.path === "delivery" ? "Confirm and sign"
        : s.path === "sheet-form" ? "Confirm" : "not available yet"}
        {" "}· {AREA_NAME[s.area as Tab]}</span>
    </header>
  );
}
