"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { BriefList } from "@/components/brief/BriefList";
import { type Act, type Retag, retagCall } from "@/components/client/ClientFiles";
import { BLINDING_ROLES, type Reach, ReachContext } from "@/components/delivery/BlindedReason";
import { useDeliveryRefresh } from "@/components/delivery/DeliverySection";
import type { View as ClientView } from "@/components/client/types";
import { Banner, PageShell } from "@/components/kit";
import { TabPanel, Tabs } from "@/components/kit/Tabs";
import { narrow, send, type Envelope, type Narrow, type Schema } from "@/lib/api";
import { TAG_LABELS } from "@/lib/fileTags";
import { blindedStudies } from "@/lib/freshness";
import { HeldReads, readAgain, useMutation, useResource, type After } from "@/lib/hooks";
import { areaHead, cardAnchor, type InputsLike, nextText, normLabel, productFor, releaseAnchor, releaseOf, type Subject,
         type WorkItem } from "@/lib/inputsWork";
import { type ArtifactView, STEP_ROUTES } from "@/lib/pipeline";
import { AREA_NAME, askAt, elsewhereText, type FormulationWay, formulationWays, inputsHref, STATUS_MEANS, plural as count, studyWay,
         profileText, valueWord } from "@/lib/words";

import { AddDataMenu, type AddDataOpen } from "./AddDataMenu";
import { DOCUMENTS, FILES, SEARCH, blindingChanged, inputsAfter, valuesAfter, valuesArrived } from "./after";
import { SheetGroups } from "./ClientConfirm";
import { ClientFilesTab, type FilesShown } from "./ClientFilesTab";
import { type CardEnv, type CardFocus, focused } from "./cards/ConfirmPath";
import { Dissolution, ProductCard, dissolutionNotes, productOf } from "./cards/ProductCard";
import { CompoundCard } from "./cards/StudyCard";
import { StudyIndividuals } from "./IndividualsTab";
import { InputRows, type Row } from "./InputRows";
import type { Run, TodoItem } from "./InputsTodo";
import { AccessRequests } from "./ObservedDatasets";
import { useReadingRefresh } from "./ReadingTray";
import { type Intent, type Options, StudiesTab } from "./StudiesTab";
import { downloadTemplate, fileArea, whereShown } from "./TabFiles";
import { OpenSheetContext, type SheetAsk } from "./openSheet";
import { type Readiness, type StatusFilter, TodoTab } from "./TodoTab";
import { useInputsWork } from "./useInputsWork";
import { SystemPanel } from "@/components/system/SystemPanel";
import { ValueReuse } from "./ValueReuse";

// The areas, in a bar across the top that stays in view (plan 2026-11-14 slice 1; the 2026-11-06 segmented-control
// decision): To do first, then the data domains (plan 2026-11-03 §3.2: the client's data land in their home, Products and
// dissolution, Clinical studies, Compound, never in an area of their own; the ids stay those of PK-Sim's building
// blocks), then the client's files themselves.
export type Tab = "todo" | "compound" | "formulations" | "individuals" | "settings" | "studies" | "files";
const TABS: [Tab, string][] = (["todo", "compound", "formulations", "studies", "individuals", "settings", "files"] as Tab[])
  .map((id) => [id, AREA_NAME[id]]);
const SOLID = ["ir_tablet", "ir_capsule", "mr", "suspension"];
const ONE_BY_ONE = 3;   // past this many cards in an area, one is open at a time
const STATUSES: StatusFilter[] = ["missing", "to_confirm", "to_decide"];
const isTab = (t: string | undefined): t is Tab => TABS.some(([id]) => id === t);
const isStatus = (s: string | undefined): StatusFilter => (STATUSES.includes(s as StatusFilter) ? s as StatusFilter : null);

// GET /projects/{id}/inputs (InputsPage): the readiness, choices and the open items are typed here
type View = Narrow<Schema<"InputsPage">, {
  readiness: ArtifactView<Readiness & { split: Record<string, string[]> }> | null;
  todo: TodoItem[];
}>;

/** The formulation a tablet study used, chosen with why. A study whose own file names its product (`named`, round 7) starts
 *  with none chosen, that product's formulation listed first where the model holds one: another product's is never
 *  preselected for it (the model's only formulation was shown chosen for a study whose file names another product). */
function FormulationChoice({ study, options, named, projectId, run }: {
  study: string; options: string[]; named?: string | null; projectId: string; run: Run;
}) {
  const mine = (o: string) => Number(Boolean(named) && normLabel(o) === normLabel(named!));
  const listed = named ? [...options].sort((a, b) => mine(b) - mine(a)) : options;
  const [value, setValue] = useState(named ? "" : options[0] ?? "");
  const [reason, setReason] = useState("");
  return (
    <div className="row gap-4">
      <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={`formulation of ${study}`}
              data-testid={`formulation-choice-${study}`}>
        {named && <option value="" disabled>choose the formulation it used</option>}
        {listed.map((o) => <option key={o}>{o}</option>)}
      </select>
      <input placeholder="why" value={reason} onChange={(e) => setReason(e.target.value)} className="w-160" />
      <button className="btn" disabled={!reason.trim() || !value}
              onClick={() => void run(() => send("put", "/api/v1/projects/{project_id}/inputs/choices", { project_id: projectId },
                                                 { kind: "formulation", key: study, value, reason }), `${study}: ${value}.`,
                                      inputsAfter(projectId, []))}>Choose</button>
    </div>
  );
}

type LiteratureRun = Schema<"LiteratureRun">;
type SourceRead = { name: string; ok: boolean; detail: string; title?: string; url?: string; values: number };
const SOURCES_AGENT = "A2-sources";

/** What the free structured sources gave the compound (plan 2026-11-05 §3.3): each source with what it is and how many
 *  values it gave; a source not reached says why; what was left for the literature agent and the person. */
function SourcesRead({ run }: { run: NonNullable<LiteratureRun["sources"]> }) {
  const summary = run.summary as { sources?: SourceRead[]; notes?: string[] };
  const sources = summary.sources ?? [];
  if (!sources.length) return null;
  return (
    <section className="sources-read" data-testid="sources-read">
      <h3>Read by code from the structured sources <span className="muted">{new Date(run.started_at).toLocaleString()}</span></h3>
      <ul>
        {sources.map((s) => (
          <li key={s.name} data-testid={`source-${s.name}`}>
            <span className={`chip ${s.ok ? (s.values ? "low" : "neutral") : "medium"}`}>{s.ok ? plural(s.values, "value") : "not read"}</span>{" "}
            <strong>{s.name}</strong>{" "}
            {s.ok && s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> : null}{" "}
            <span className="muted">{s.ok ? s.detail.replace(/^CID \d+;?\s*/, "") : s.detail}</span>
          </li>
        ))}
      </ul>
      {(summary.notes ?? []).length > 0 && <ul className="flags">{summary.notes!.map((n) => <li key={n}>{n}</li>)}</ul>}
    </section>
  );
}
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The status counts, said to a screen reader only when they change once the page has read its work (final review
 *  A11Y-6): never while it loads (the cards are read one by one and the counts climb), and once they settle after a
 *  decision (whose own words the decision's live region says), so each change is said once. */
function CountsSaid({ ready, text }: { ready: boolean; text: string }) {
  const [said, setSaid] = useState("");
  const heard = useRef<string | null>(null);
  useEffect(() => {
    if (!ready) return;
    if (heard.current === null) { heard.current = text; return; }
    if (text === heard.current) return;
    const settle = window.setTimeout(() => { heard.current = text; setSaid(`Now ${text}.`); }, 1500);
    return () => window.clearTimeout(settle);
  }, [ready, text]);
  return <span className="sr-only" role="status" data-testid="status-said">{said}</span>;
}

/** The literature agent at work (plan 2026-11-05 §3.3): how long, how far into its budget, and what it found so far;
 *  in place of a red "already running". */
function LiteratureProgress({ r }: { r: LiteratureRun }) {
  const minutes = r.run ? Math.max(0, Math.round((Date.now() - new Date(r.run.started_at).getTime()) / 60000)) : null;
  if (r.run?.agent === SOURCES_AGENT && !r.run.finished_at) {
    return <Banner tone="ok" testId="literature-progress">Reading PubChem, the FDA label and ChEMBL for the compound&apos;s
      values; then the literature agent searches what is still missing.</Banner>;
  }
  return (
    <Banner tone="ok" testId="literature-progress">
      The literature agent is searching{minutes !== null ? ` (${minutes} min so far)` : ""}: turn {r.turns}
      {r.max_turns ? ` of at most ${r.max_turns}` : ""}, {plural(r.proposed, "value")} proposed so far. They flow into the rows
      when it finishes; you can keep working meanwhile.
    </Banner>
  );
}

type WorkspaceProps = { projectId: string; initialTab?: string; initialOnly?: boolean; initialStatus?: string; steps?: ReactNode };

/** Step 2 · Inputs (redesign §3.2): one workspace in PK-Sim's building blocks. Values flow in from every source not
 *  excluded and the source-selection rule keeps one per input (D-32). The frame (plan 2026-11-14 slice 1): a compact head
 *  with "Add data", the step bar, and a bar of areas that stays in view; To do lists the one list of work (slice 2,
 *  lib/inputsWork.ts), each item opening where it is settled, and Client files holds the files, their reading and the
 *  delivery. Every count on the page is read from that one list. The area and To do's filters are in the URL
 *  (`?tab=…&only=1&status=…`). Nothing is accepted here: the one review is at the MAP signature (D-27). The page holds
 *  what it has read for the visit (`HeldReads`; final review CODE-4): an area shown again reads nothing it holds, and a
 *  decision reads again only what it changed (`after.ts`, `components/delivery/writes.ts`). */
export function InputsWorkspace(props: WorkspaceProps) {
  return <HeldReads><Workspace {...props} /></HeldReads>;
}

/** The step bar's say on Inputs, from the readiness the inputs answer with: its state, what it waits on
 *  (`modeler_project.steps.inputs_step`) and the lever it names for a tablet study's formulation (round 4: a product or a
 *  dissolution profile added changes it without changing the checks). */
function stepSays(view: View): string | null {
  const readiness = view.readiness;
  if (!readiness) return null;
  const failing = (readiness.content?.checks ?? []).filter((c) => !c.ok).map((c) => c.check);
  const way = (view.todo as TodoItem[]).find((t) => t.kind === "formulation")?.way ?? null;
  return JSON.stringify([readiness.status, Boolean(readiness.content?.ready), failing, way]);
}

function Workspace({ projectId, initialTab, initialOnly, initialStatus, steps }: WorkspaceProps) {
  const page = useResource("/api/v1/projects/{project_id}/inputs", { project_id: projectId }, { select: (d) => narrow<View>(d) });
  const client = useResource("/api/v1/projects/{project_id}/client-data", { project_id: projectId },
    { select: (d) => narrow<ClientView>(d), poll: (d) => d.running });
  const work = useInputsWork(projectId);
  const model = work.model;
  const mutation = useMutation();
  const pathname = usePathname();
  const url = useSearchParams();
  // an explicit ?tab= wins; otherwise the page opens on To do while anything is open, else on Compound
  const [chosen, setChosen] = useState<Tab | null>(isTab(initialTab) ? initialTab : null);
  const [only, setOnlyState] = useState(Boolean(initialOnly));
  const [status, setStatusState] = useState<StatusFilter>(isStatus(initialStatus));
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [intent, setIntent] = useState<Intent | null>(null);
  // the card a To do row, "Next" or a link opened, in its area (plan 2026-11-14 slice 3): by its key, its delivery subject
  // or its sheet-form group, with the element to bring into view in it
  const [cardFocus, setCardFocus] = useState<CardFocus | null>(null);
  // the products and the compound open on their cards (a study opens under its row in Clinical studies)
  const [cardsOpen, setCardsOpen] = useState<Record<string, boolean>>({});
  // the client files opened on their sheets, and the last sheet form saved, held while another area is shown
  const [filesOpen, setFilesOpen] = useState<ReadonlySet<string>>(new Set());
  const [lastSheet, rememberSheet] = useState<FilesShown["memory"]["last"]>(null);
  // a sheet a card asked to open in the reader, with the cells its own words name as no sample (final review OWN-2 c)
  const [sheetAsk, setSheetAsk] = useState<SheetAsk | null>(null);
  const shown: FilesShown = {
    open: filesOpen, memory: { last: lastSheet, remember: rememberSheet }, ask: sheetAsk, asked: () => setSheetAsk(null),
    toggle: (id) => {
      setFilesOpen((was) => {
        const next = new Set(was);
        if (!next.delete(id)) next.add(id);
        return next;
      });
      // a card's ask is spent once its file's row is closed: opened again, the row shows the file as it is, not the reader
      // with the ask's cells added again (round 2's gate-todo skeptic)
      if (filesOpen.has(id) && sheetAsk?.file === id) setSheetAsk(null);
    },
  };
  const review = useResource("/api/v1/projects/{project_id}/client-review", { project_id: projectId });
  const literature = useResource("/api/v1/projects/{project_id}/literature-run", { project_id: projectId },
    { poll: (d) => d.running, interval: 5000 });
  const queries = useQueryClient();
  const router = useRouter();
  // a file read by code or by the agent brings values onto the cards, whichever area is open
  const deliveryPage = useDeliveryRefresh(projectId);
  useReadingRefresh(projectId);
  const assembled = useRef(false);
  const searching = useRef(false);
  const view = page.data;
  // the inputs follow every change on the server; a page opened after a change upstream (the brief) assembles them once
  const stale = view && (!view.readiness || view.readiness.status === "STALE");
  // where a blinded reason may lead (round 6): Review & sign shows its studies and roles once the inputs are ready (the
  // plan is made from them), and the purpose that blinds a study is changed by a person who may set the blinding (the
  // signed-in person's roles, read once for the visit with the page)
  const me = useResource("/api/v1/me", {}, { select: (d) => d.roles });
  const reachRoles = Boolean(view?.readiness?.content?.ready) && !stale;
  const reachPurpose = (me.data ?? []).some((r) => BLINDING_ROLES.includes(r));
  const reach = useMemo<Reach>(() => ({ roles: reachRoles, purpose: reachPurpose }), [reachRoles, reachPurpose]);

  // the area the page opened on is kept once the work is read, so a list that empties does not move the page; chosen
  // once the inputs are assembled: on a project's first visit they are read before that, with no to-do yet, and the page
  // opened on Compound with every compound value still to fill
  useEffect(() => {
    if (chosen === null && view && !stale && work.loaded) setChosen(model.counts.open ? "todo" : "compound");
  }, [chosen, view, stale, work.loaded, model.counts.open]);
  // what a message said is about the area it was said in: another area starts without it, however the area changes (the
  // area bar, a To do row, a status-line count, a link; final review OWN-16, round 4: the counts kept it). Once the page
  // has settled on its first area: a message said while it loads stays
  const lastArea = useRef<Tab | null>(null);
  useEffect(() => {
    if (chosen === null) return;
    if (lastArea.current !== null && lastArea.current !== chosen) setNotice(null);
    lastArea.current = chosen;
  }, [chosen]);
  // a link to another area of this page (Add data's "See each file on Inputs") changes the area and the filters without a
  // new page; the URL this page writes itself says what the page already shows
  const urlTab = url.get("tab") ?? undefined, urlOnly = url.get("only") === "1", urlStatus = url.get("status") ?? undefined;
  useEffect(() => { if (isTab(urlTab)) setChosen(urlTab); }, [urlTab]);
  useEffect(() => { setOnlyState(urlOnly); }, [urlOnly]);
  useEffect(() => { setStatusState(isStatus(urlStatus)); }, [urlStatus]);
  // a link that names the way forward lands on it (round 3, owner-job gap 11): `add=product` opens the form that adds a
  // product on Products and dissolution (the step bar's, To do's and Review & sign's "add a product"); `at=<place>` brings
  // a place of the area into view and gives it the focus ("ask the client": the line of To do that asks for it, else the
  // group "Ask the client")
  const urlAdd = url.get("add"), urlAt = url.get("at");
  const [addProduct, setAddProduct] = useState<number | null>(null);
  useEffect(() => {
    if (urlAdd !== "product") return;
    setChosen("formulations");
    setOnlyState(false);          // the form is among what is there to add, not under "Only what needs me"
    setAddProduct(Date.now());
  }, [urlAdd]);
  const shownNow = Boolean(view) && work.loaded;
  useEffect(() => {
    if (!urlAt || !shownNow) return;
    let tries = 0, timer = 0;
    const find = () => {
      const q = (selector: string) => document.querySelector<HTMLElement>(selector);
      // a line of "Ask the client" is found by its requirement too when it is a product's ("todo-ask-REQ-form.release@<product>");
      // the line of the product a study names (`…~<product>`, round 6), or the delivery's line it joined (round 7: the
      // line stands for it, `data-also`), else the delivery's line of that product, else the line of the studies that
      // name none, else the group
      const ask = urlAt.startsWith("todo-ask-");
      const [base, product] = urlAt.split("~");
      const el = q(`[data-testid="${CSS.escape(urlAt)}"]`)
        ?? (ask ? q(`[data-also~="${CSS.escape(urlAt)}"]`) : null)
        ?? (ask && product ? q(`[data-testid="${CSS.escape(`${base}@${product}`)}"]`) : null)
        ?? (ask && !product ? q(`[data-testid^="${CSS.escape(`${urlAt}@`)}"]`) : null)
        ?? (ask && product && tries > 10 ? q(`[data-testid="${CSS.escape(base)}"]`) : null)
        ?? (ask && tries > 10 ? q('[data-testid="todo-group-ask"]') : null);
      if (!el) { if (++tries < 30) timer = window.setTimeout(find, 100); return; }
      el.scrollIntoView({ block: "center" });
      if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
      el.focus({ preventScroll: true });
      el.classList.add("just-opened");
      window.setTimeout(() => el.classList.remove("just-opened"), 1600);
    };
    timer = window.setTimeout(find, 50);
    return () => window.clearTimeout(timer);
  }, [urlAt, shownNow]);
  // `release=<product>` (round 4: the step bar's "use a product's dissolution profile as its release" and "add a product's
  // dissolution data") opens that product's card at its release ("Use this profile as the release", focused, or "Add its
  // dissolution file…"); a product with no card opens what settles it: a profile of it listed under the profiles of no
  // product, else (one only the proposal or a study names: round 5, it landed on the proposal's "Change") "Add data" on
  // "Formulation and dissolution files…", focused
  const urlRelease = url.get("release");
  const [addOpen, setAddOpen] = useState<AddDataOpen | null>(null);
  useEffect(() => {
    if (urlRelease === null || !shownNow) return;
    const card = productFor(model.subjects, urlRelease);
    setOnlyState(false);
    if (card) { openCard(card, releaseAnchor(card)); return; }
    // the URL is written again (without `release`), so the same link followed again lands again
    setTab("formulations");
    const listed = (client.data?.dissolution?.profiles ?? []).some((p) => !model.subjects.some((s) => s.kind === "product" && productOf(s)(p))
                                                                     && normLabel(String(p.key.product ?? "")) === normLabel(urlRelease));
    if (listed) bringIntoView("dissolution-unlinked", "inputs-products");
    else setAddOpen({ at: Date.now(), area: "formulations", product: urlRelease || undefined });
  }, [urlRelease, shownNow]); // eslint-disable-line react-hooks/exhaustive-deps

  const run: Run = async <T,>(fn: () => Promise<Envelope<T>>, ok: string, after: After<T>) => {
    const { problem } = await mutation.run(fn, after);
    setNotice(problem ? { ok: false, text: problem } : ok ? { ok: true, text: ok } : null);
    return problem;
  };

  // a file's tag files it under the area of its data (plan 2026-11-05 §3.1): changed, the file moves there
  const retag: Retag = (file, kind) => run(retagCall(projectId, file, kind),
                                           `${file.file}: ${TAG_LABELS[kind].toLowerCase()}, ${whereShown(kind)}.`, FILES);
  const clientAct: Act = (fn, after) => run(fn, "", after);
  const clientSaved = async (m: string) => setNotice({ ok: true, text: m });

  // the literature agent's end is said once, with what it found, when the page saw it searching
  const running = literature.data?.running ?? false;
  useEffect(() => {
    if (running) searching.current = true;
    else if (searching.current && literature.data) {
      searching.current = false;
      setNotice({ ok: true, text: `The literature agent finished: ${plural(literature.data.proposed, "value")} proposed, in the rows below.` });
      // what it proposed is in the model's inputs and the evidence, its sources in the documents
      void valuesArrived(queries, projectId);
      void readAgain(queries, [DOCUMENTS]);
    }
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  async function askLiterature() {
    const problem = await run(() => send("post", "/api/v1/projects/{project_id}/evidence:research", { project_id: projectId }),
                              "PubChem, the FDA label and ChEMBL are being read; then the literature agent searches what is still missing.", SEARCH);
    if (problem && /already in progress/.test(problem)) {   // started elsewhere: its progress is shown, not a refusal
      setNotice(null);
      await readAgain(queries, SEARCH.reads!);
    }
  }

  useEffect(() => {
    if (!stale || assembled.current) return;
    assembled.current = true;
    // in the background: it reports only a problem, so it never wipes the message of what the person just did
    void mutation.run(() => send("post", "/api/v1/projects/{project_id}/inputs:assemble", { project_id: projectId }), inputsAfter(projectId, []))
      .then(({ problem }) => { if (problem) setNotice({ ok: false, text: problem }); });
  }, [stale]); // eslint-disable-line react-hooks/exhaustive-deps

  // the step bar is drawn on the server from the readiness: drawn again when what it says on Inputs changes (a change
  // assembled the inputs again, a reading or the literature brought values in), not after every decision (final review
  // OWN-7: a decision on a card leaves it as it was)
  const says = view ? stepSays(view) : null;
  const said = useRef<string | null>(null);
  useEffect(() => {
    if (says === null) return;
    if (said.current !== null && said.current !== says) router.refresh();
    said.current = says;
  }, [says]); // eslint-disable-line react-hooks/exhaustive-deps
  // what the project's blinding list withholds follows the studies it names (final review round 5): an answer of the
  // inputs that names other blinded studies than the one before it, whatever changed them (a study's group confirmed, a
  // dataset kept or left out, values brought in: the MS-01 split proposes its roles again before a plan), has the
  // client's files, the sheet form, the evidence, the documents and the delivery read again (`blindingChanged`)
  const blinded = blindedStudies(view);
  const blindedWas = useRef<string | null>(null);
  useEffect(() => {
    if (blinded === null) return;
    if (blindedWas.current !== null && blindedWas.current !== blinded) void blindingChanged(queries, projectId);
    blindedWas.current = blinded;
  }, [blinded]); // eslint-disable-line react-hooks/exhaustive-deps

  const head = { tone: "inputs" as const, steps, eyebrow: "Step 2 of 4", title: "Inputs", noReveal: true, slim: true,
                 lede: "Fill in what the model needs and confirm the client's data." };
  if (page.problem || !view) {
    return (
      <PageShell {...head}>
        {page.problem ? <div className="banner err">{page.problem}</div> : <p className="muted">Loading the inputs…</p>}
      </PageShell>
    );
  }

  const tab: Tab = chosen ?? (view.todo.length ? "todo" : "compound");
  const todo = view.todo;
  // the client's data, by the domain it lands in (plan 2026-11-03 §3.3): one card per study, product and compound
  // (lib/inputsWork.ts), and the sheets whose study or product is not stated yet
  const groups = review.data?.groups ?? [];
  // a sheet whose file a person linked to a study or product on the delivery is that card's: not listed apart (OWN-4)
  const joinedSheets = new Set(model.subjects.flatMap((s) => s.groups.map((g) => g.id)));
  const sheetsFor = (t: Tab) => groups.filter((g) => g.kind === "sheet" && g.tab === t && !joinedSheets.has(g.id));
  const cardsFor = (t: Tab) => model.subjects.filter((s) => s.area === t && (!only || !s.done));
  const forTab = (t: Tab) => todo.filter((i) => (i.tab ?? "compound") === t);
  // a group to confirm is settled on its own card, above the panel: listed in To do, not twice in the panel
  const panelTodo = (t: Tab) => forTab(t).filter((i) => i.kind !== "confirm");
  // with the rows to fill ("empty": a model input the data plan owns with no value yet), which each tab folds away
  const rows = (t: Tab) => (view.compound as Row[]).filter((r) => r.tab === t);
  const options = view.study_options as Options;
  const studies = view.studies;
  const used = studies.filter((s) => !s.excluded);
  const formulations = view.compound.filter((r) => /^form\.[^.]+\.type$/.test(r.id) && r.state === "kept").map((r) => r.id.split(".")[1]);
  const files = client.data?.files ?? [];
  const unplaced = files.filter((f) => !fileArea(f)).length;
  // an area's rows as listed: with "Only what needs me", a value already kept is left out
  const listed = (t: Tab) => rows(t).filter((r) => !only || r.state !== "kept");

  // a published OSP model of the drug as a source (in place of the old Quick start): its values and datasets flow in,
  // ranked below the client and the literature (D-32), and the person checks them at the review like any other
  async function take(templateId: string) {
    const { data, problem } = await mutation.run(() => send("post", "/api/v1/projects/{project_id}/evidence:published-model",
                                                            { project_id: projectId }, { template_id: templateId }), valuesAfter(projectId));
    setNotice(problem ? { ok: false, text: problem } : data ? { ok: true, text:
      `The published OSP ${data.model} model: ${data.values} values and ${data.datasets} datasets added`
      + (data.already ? `, ${data.already} already here` : "") + (data.skipped.length ? `; ${data.skipped.length} not taken (not plasma data of the drug)` : "")
      + ". They rank below the client's and the literature's values." } : null);
  }

  // the area, the "Only what needs me" filter and To do's status filter, in the URL (plan 2026-11-14 §2.1, "URL state"):
  // the history entry is replaced, never pushed, and the page keeps its place. Through the history API, which Next's
  // router follows (useSearchParams), not router.replace: the page is the same, so no server render is asked for at
  // each change, and an answer that arrives late cannot put back an area already left (plan §5).
  const sync = (t: Tab, o: boolean, s: StatusFilter) => {
    const q = new URLSearchParams({ tab: t });
    if (o) q.set("only", "1");
    if (s && t === "todo") q.set("status", s);
    window.history.replaceState(null, "", `${pathname}?${q.toString()}`);
  };
  // (a message of one area is cleared when the area changes: the effect on `chosen` above)
  const setTab = (t: Tab) => {
    setChosen(t); sync(t, only, t === "todo" ? status : null); if (t !== "todo") setStatusState(null);
  };
  const setOnly = (o: boolean) => { setOnlyState(o); sync(tab, o, status); };
  // "Add data" opened on "Formulation and dissolution files…", for a product (round 5: a product's dissolution data are
  // added there, whoever asks: a card's release line, a tablet study's row)
  const addDissolution = (product?: string) => setAddOpen({ at: Date.now(), area: "formulations", product: product || undefined });
  const setStatus = (s: StatusFilter) => { setStatusState(s); setChosen("todo"); sync("todo", only, s); };
  // a status-line count opens To do narrowed to its word; pressed again, To do shows every item
  const toggleStatus = (s: Exclude<StatusFilter, null>) => setStatus(tab === "todo" && status === s ? null : s);

  const FOCUSABLE = "input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), a[href]";
  /** Bring an element of the area just opened into view (it is drawn once the area shows it, and its card once opened),
   *  opening the folds around it, and mark it a moment; `fallback` when the element is not drawn there. `within`: the
   *  card it is on, looked in first, so a place on one card never lands on the same place of another (final review
   *  CODE-1; the places on a delivery card are its subject's own, too). */
  function bringIntoView(testId: string, fallback?: string, within?: string) {
    let tries = 0;
    const at = (id: string) => (within ? document.querySelector<HTMLElement>(`[data-testid="${CSS.escape(within)}"] [data-testid="${CSS.escape(id)}"]`) : null)
      ?? document.querySelector<HTMLElement>(`[data-testid="${CSS.escape(id)}"]`);
    const find = () => {
      const el = at(testId) ?? (tries > 10 && fallback ? at(fallback) : null);
      if (!el) { if (++tries < 30) window.setTimeout(find, 100); return; }
      for (let fold = el.closest("details"); fold; fold = fold.parentElement?.closest("details") ?? null) if (!fold.open) fold.open = true;
      // a card opens at its head (a study's: its row in the list), under the area bar, with the focus on the control that
      // opens it; a place inside a card is brought to the middle, the focus on its first control
      const card = /^(study|product|compound)-card-/.test(el.dataset.testid ?? "");
      const row = card ? el.closest("tr.row-detail")?.previousElementSibling as HTMLElement | null : null;
      const target = row ?? el;
      target.scrollIntoView({ block: card ? "start" : "center", behavior: "smooth" });
      // a card's head stays where it was brought once what is above it has finished drawing (cards read as they open)
      if (card) {
        window.setTimeout(() => {
          const pad = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
          const top = target.getBoundingClientRect().top;
          if (top < pad - 8 || top > pad + 48) target.scrollIntoView({ block: "start" });
        }, 900);
      }
      const control = card ? target.querySelector<HTMLElement>("button[aria-expanded]")
        : el.matches(FOCUSABLE) ? el : el.querySelector<HTMLElement>(FOCUSABLE);
      control?.focus({ preventScroll: true });
      el.classList.add("just-opened");
      window.setTimeout(() => el.classList.remove("just-opened"), 1600);
    };
    window.setTimeout(find, 50);
  }
  /** A study's individual on Populations and individuals, from its row in the studies table: its own row there, with the
   *  focus on its first field, or, shared with other studies, the button that opens its form (final review round 6). */
  const toIndividual = (studyId: string) => {
    setTab("individuals");
    bringIntoView(`individual-${studyId}`, `individual-change-${studyId}`);
  };
  /** Open a card in its area and bring `anchor` in it into view (the card itself by default). */
  function openCard(s: Subject, anchor?: string) {
    setTab(s.area);
    setCardsOpen((was) => ({ ...was, [s.key]: true }));
    setCardFocus({ key: s.key, anchor, at: Date.now() });
    bringIntoView(anchor ?? cardAnchor(s), cardAnchor(s), anchor ? cardAnchor(s) : undefined);
  }
  /** Open where a work item is settled: its area, its card (the study, product or compound it concerns, in its area) or
   *  its file's row. An item of the /inputs to-do on a study opens that study's row (its regimen) or its individual.
   *  The filters that would hide it there are dropped: To do narrowed to another status word, and "Only what needs me"
   *  for an item that is not counted (a delivery whose files name no study yet, "Blocks nothing"). */
  function go(item: WorkItem) {
    const w = item.where;
    const keepStatus = w.tab === "todo" && status === item.status ? status : null;
    const keepOnly = only && item.open;
    setChosen(w.tab);
    setStatusState(keepStatus);
    if (keepOnly !== only) setOnlyState(keepOnly);
    sync(w.tab, keepOnly, keepStatus);
    const at = Date.now();
    if (w.file && !filesOpen.has(w.file)) setFilesOpen((was) => new Set([...was, w.file!]));
    const group = item.issue?.group ?? (w.anchor?.startsWith("group-") ? w.anchor.slice("group-".length) : undefined);
    const card = w.tab !== "files" && w.tab !== "todo"
      ? model.subjects.find((s) => (w.subject && s.row && `${s.row.subject_type}/${s.row.subject}` === w.subject) || (group && s.groups.some((g) => g.id === group))
                                   || ((item.id.startsWith("confirm:") || item.todo?.kind === "formulation") && item.subjects[0] === s.key)
                                   // the formulation item opens the card of the product whose release it names (round 4)
                                   || (item.todo?.kind === "formulation" && w.anchor === releaseAnchor(s)))
      : undefined;
    if (card) {
      setCardsOpen((was) => ({ ...was, [card.key]: true }));
      setCardFocus({ key: card.key, ref: w.subject, group, anchor: w.anchor, at });
    }
    const fallback = item.todo?.kind === "regimen" ? `study-${item.todo.target}` : item.todo?.kind === "demographics" ? `individual-${item.todo.target}`
      : card ? cardAnchor(card) : undefined;
    // a card to confirm opens at its head (its whole body is what is confirmed); an item on a card, at its place there
    if (card && item.id.startsWith("confirm:")) bringIntoView(cardAnchor(card));
    else if (w.anchor) bringIntoView(w.anchor, fallback, card ? cardAnchor(card) : undefined);
    else if (card) bringIntoView(cardAnchor(card));
  }
  // a link to an area (the delivery's line in Client files: `group` ""), or to a sheet-form group's card
  const openGroup = (group: string, t: Tab) => {
    const card = group ? model.subjects.find((s) => s.groups.some((g) => g.id === group)) : undefined;
    if (card) openCard(card, `group-${group}`);
    else setTab(t);
  };
  // a tool the head's "Add data" opens on Clinical studies
  function startStudies(what: Intent["what"]) {
    if (only) setOnly(false);   // the tool opens among what is there to add, not under "Only what needs me"
    setTab("studies");
    setIntent({ what, at: Date.now() });
  }

  // the status line (plan 2026-11-14 §2): the open work by status word, each opening To do narrowed to it; what is done;
  // what the model holds now; and the page's one primary button, "Next", the first open item in the order the work is
  // done (lib/inputsWork.ts). Every number here is counted from the one list, as are the area bar's and To do's.
  const counts = model.counts;
  const ready = model.ready;
  const nextLabel = nextText(model);
  const next: { text: string; go: () => void } | { text: string; href: string } | null =
    model.next && nextLabel ? { text: nextLabel, go: () => go(model.next!) }
      : ready ? { text: "Next: Review & sign", href: STEP_ROUTES.review(projectId) } : null;
  const pressed = (s: StatusFilter) => tab === "todo" && status === s;
  const inModel = model.inModel;

  const tabs = TABS.map(([id, label]) => ({
    id, label, count: model.byArea[id], countLabel: id === "todo" ? "to do" : "open", testId: `tab-${id}`,
    badge: id === "files" && unplaced > 0 ? <span className="chip medium" data-testid="files-unplaced"
                                                  title="files not filed under an area yet: say what each is">{unplaced} to place</span> : null,
  }));
  // each area's one line: what it holds and what is open in it, counted from the same list as its badge; "Only what
  // needs me" (in the URL, as on To do and Client files) leaves out what is done and what is there to read (the
  // proposal's lists, the sources read, the studies in the model, the other observed data)
  const areaLine = (t: Exclude<Tab, "todo" | "files">) => (
    <div className="area-head-row">
      {/* the area's heading, under the page's (h1) and over its sections (h3): read, not drawn (the bar names it) */}
      <h2 className="sr-only" id={`area-title-${t}`}>{AREA_NAME[t]}</h2>
      <p className="area-head" data-testid={`area-head-${t}`}>{areaHead(model, t)}</p>
      <label className="only-mine">
        <input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} data-testid={`only-${t}`} />
        Only what needs me
      </label>
    </div>
  );
  // what every card needs from the page
  const fileNames = new Map(files.map((f) => [f.id, f.file] as const));
  const env: CardEnv = {
    projectId, work: model, run, onGo: go, onTodo: () => setTab("todo"), focus: cardFocus, onAddData: addDissolution,
    fileName: (id) => fileNames.get(id) ?? null,
    onFile: (id) => { setTab("files"); if (!filesOpen.has(id)) setFilesOpen((was) => new Set([...was, id])); bringIntoView(`inputs-file-${fileNames.get(id) ?? ""}`); },
  };
  // "Read this sheet" from a card: its file's row in Client files, opened on the sheet in the reader
  const openSheet = (ask: Omit<SheetAsk, "at">) => {
    setTab("files");
    if (!filesOpen.has(ask.file)) setFilesOpen((was) => new Set([...was, ask.file]));
    setSheetAsk({ ...ask, at: Date.now() });
    bringIntoView(`sheet-${ask.sheet}`, `inputs-file-${fileNames.get(ask.file) ?? ""}`);
  };
  const cardOpen = (s: Subject, first: boolean) => cardsOpen[s.key] ?? (focused(s, cardFocus) || first);
  const toggleCard = (s: Subject, first: boolean) => setCardsOpen((was) => ({ ...was, [s.key]: !(was[s.key] ?? (focused(s, cardFocus) || first)) }));
  // the dissolution profiles, each on its product's card; those of no product's card after them
  const dissolution = client.data?.dissolution;
  const profileLabel = (id: string) => profileText(dissolution?.profiles.find((p) => p.id === id)?.label ?? id);
  const products = cardsFor("formulations").filter((s) => s.kind === "product");
  // what gives a tablet study its formulation as the project stands (round 4: the API's, the step bar's and To do's lever):
  // a product's dissolution profile here, products without one, or no product at all; each study's own (round 5)
  const formulationWay = todo.find((t) => t.kind === "formulation")?.way ?? null;
  const profilesOf = (s: Subject) => (dissolution?.profiles ?? []).filter(productOf(s));
  const unlinkedProfiles = (dissolution?.profiles ?? []).filter((p) => !model.subjects.some((s) => s.kind === "product" && productOf(s)(p)));
  // where a study's way lands, as the step bar's link does (`release=`): the first product's card at its release, a profile
  // of no card under the profiles of no product, else "Add data" on the dissolution files, for that product
  const openRelease = (product: string | undefined) => {
    if (only) setOnly(false);
    const card = productFor(model.subjects, product);
    if (card) openCard(card, releaseAnchor(card));
    else if (unlinkedProfiles.some((p) => normLabel(String(p.key.product ?? "")) === normLabel(product ?? ""))) {
      bringIntoView("dissolution-unlinked", "inputs-products");
    } else addDissolution(product);
  };
  // the solid studies, each with its own way to a formulation (round 5: the row said the step bar's lever, which may be
  // another study's): one that names its formulation is listed while the model lacks it
  const ownWay = (study: string) => (formulationWay?.each?.some((e) => normLabel(e.study) === normLabel(study)) ? studyWay(formulationWay, study) : null);
  const solidRows = used.filter((s) => SOLID.includes(String(s.facts.formulation)))
    .map((s) => ({ s, own: s.facts.formulation_name ? ownWay(s.study_id) : studyWay(formulationWay, s.study_id) }))
    .filter(({ s, own }) => !only || !s.facts.formulation_name || own);
  /** What gives a tablet study its formulation here, as the project stands (round 4: the step bar's lever, the API's
   *  `way`; round 5: the study's own): a product's dissolution profile above; a product without one, its dissolution data;
   *  no product at all, the product first; or the client. `named`: the study's record names the formulation (said after
   *  its name); a study whose own file names its product says so (round 6: why only that product's profile settles it),
   *  and its "ask the client" lands on the line that asks for that product. */
  const studyLever = (study: string, way: FormulationWay | null, named = false) => {
    const first = way?.products[0];
    const card = productFor(model.subjects, first);
    const fileNamed = named ? null : way?.each?.[0]?.named ?? null;
    const lead = named ? "not in the model yet" : `no formulation in the model yet${fileNamed ? ` (its file names ${fileNamed})` : ""}`;
    const askHref = inputsHref(projectId, { area: "todo", query: `at=${askAt(way?.each?.[0]?.named ? first : null)}` });
    // round 7: the model would use another product's release for it (its only formulation), though the readiness check
    // passes: said, with what sets its own product's release; its ask stays
    const uses = named ? null : way?.each?.[0]?.uses ?? null;
    if (uses && fileNamed && (way?.way === "use_profile" || way?.way === "add_dissolution")) {
      return <span className="muted" data-testid={`formulation-elsewhere-${study}`}>{elsewhereText(fileNamed, uses)}:{" "}
        {way.way === "use_profile"
          // its profile here: used (or its data confirmed first), as the step bar says it
          ? <><button type="button" className="link-btn" onClick={() => openRelease(first)} data-testid={`formulation-release-${study}`}
                      aria-label={first ? `${formulationWays(way).ways[0]?.say}: ${first}` : undefined}>
              {formulationWays(way).ways[0]?.say}</button>, above{card ? ` (${card.label}'s card)` : ""}</>
          : <><button type="button" className="link-btn" onClick={() => openRelease(first)} data-testid={`formulation-dissolution-${study}`}>
              add {first}&apos;s dissolution data</button>{" (its dissolution file, Add data), or "}
              <Link href={askHref} prefetch={false} data-testid={`formulation-ask-${study}`}>ask the client</Link></>}</span>;
    }
    if (way?.way === "use_profile") {
      return <span className="muted" data-testid={`formulation-none-${study}`}>{lead}:{" "}
        <button type="button" className="link-btn" onClick={() => openRelease(first)} data-testid={`formulation-release-${study}`}
                aria-label={first ? `${formulationWays(way).ways[0]?.say}: ${first}` : undefined}>
          {formulationWays(way).ways[0]?.say}</button>, above{card ? ` (${card.label}'s card)` : ""}</span>;
    }
    if (way?.way === "add_dissolution") {
      return <span className="muted" data-testid={`formulation-none-${study}`}>{lead}, and{" "}
        {named || way.each?.[0]?.named ? `no dissolution profile of ${first} can give it` : "no product here has a dissolution profile that can give it"}:{" "}
        <button type="button" className="link-btn" onClick={() => openRelease(first)} data-testid={`formulation-dissolution-${study}`}
                aria-label={first ? `add a product's dissolution data: ${first}` : undefined}>add a product&apos;s dissolution data</button>
        {" (its dissolution file, Add data), or "}<Link href={askHref} prefetch={false} data-testid={`formulation-ask-${study}`}>ask the client</Link></span>;
    }
    if (way?.way === "add_product") {
      return <span className="muted" data-testid={`formulation-none-${study}`}>{lead}, and no product here:{" "}
        <button type="button" className="link-btn" onClick={() => { if (only) setOnly(false); setAddProduct(Date.now()); }}
                data-testid={`formulation-add-product-${study}`}>add the product it used</button>
        {" (“Add a product”, above) with its dissolution data, or "}<Link href={askHref} prefetch={false} data-testid={`formulation-ask-${study}`}>ask the client</Link></span>;
    }
    return <span className="muted" data-testid={`formulation-none-${study}`}>{lead}</span>;
  };
  // up to three cards are all open; past three, the first to confirm is (the owner, 2026-11-05: "one by one")
  const opens = (list: Subject[], s: Subject) => list.length <= ONE_BY_ONE || s.key === list.find((x) => !x.done && !x.blinded)?.key;
  // Simulation settings: shown behind "Change…", or by themselves while one needs the person
  const settingsOpen = cardsOpen["settings"] ?? false;
  const setSettingsOpen = (o: boolean) => setCardsOpen((was) => ({ ...was, settings: o }));
  const settingsNeed = rows("settings").some((r) => r.state === "missing" || r.state === "conflict" || r.state === "held")
    || panelTodo("settings").length > 0;

  // the plan's skip link to the areas (§2.1): past the head's menu, the step bar and the status line, to the area shown
  const toAreas = (
    <a className="skip-link" href={`#inputs-tab-${tab}`} data-testid="skip-to-areas"
       onClick={(e) => {
         const at = document.getElementById(`inputs-tab-${tab}`);
         if (!at) return;
         e.preventDefault();
         at.focus();
       }}>Skip to the input areas</a>
  );

  return (
    <OpenSheetContext.Provider value={openSheet}>
    <ReachContext.Provider value={reach}>
    <PageShell {...head} before={toAreas}
      actions={(
        <AddDataMenu projectId={projectId} run={run} open={addOpen}
                     onTemplate={() => void downloadTemplate(client.data?.template).then((p) => { if (p) setNotice({ ok: false, text: p }); })}
                     onDigitize={() => startStudies("digitize")} onTypeTable={() => startStudies("type")}
                     onFindObserved={client.data?.agents.enabled ? () => {
                       setTab("studies");
                       void run(() => send("post", "/api/v1/projects/{project_id}/evidence:research", { project_id: projectId }, undefined, { agent: "A3" }),
                                "The observed-data agent is searching; datasets appear under Every dataset as it records them.", SEARCH);
                     } : undefined}>
          <button type="button" className="menu-item" data-testid="ask-literature" disabled={running} onClick={() => void askLiterature()}
                  title="PubChem, the FDA label and ChEMBL by code, then the literature agent (when agents are on)">
            {running ? "Searching the sources…" : "Search the sources and the literature"}
          </button>
          {view.published_models.map((m) => (
            <button key={m.id} type="button" className="menu-item" data-testid={`published-model-${m.id}`} title={m.name}
                    onClick={() => void take(m.id)}>
              Take the published OSP model&apos;s values <span className="muted">· {m.name}</span>
            </button>
          ))}
        </AddDataMenu>
      )}
    >
      <div className="inputs-status" data-testid="inputs-status">
        <div className="status-counts">
          {(files.length > 0 || client.data?.agents.enabled === false) && (
            <span className="muted status-note" data-testid="status-files"
                  title={client.data?.agents.enabled === false ? "AI reading is off on this server: the files are read by code" : undefined}>
              {[files.length ? plural(files.length, "client file") : "", client.data && !client.data.agents.enabled ? "AI off" : ""]
                .filter(Boolean).join(" · ")}
            </span>
          )}
          {ready && <strong className="status-ready" data-testid="status-ready">Inputs are ready</strong>}
          {counts.missing > 0 && (
            <button type="button" className="btn small status-count" data-testid="status-missing" aria-pressed={pressed("missing")}
                    onClick={() => toggleStatus("missing")} title={STATUS_MEANS.missing}>Missing <span className="status-num">{counts.missing}</span></button>
          )}
          <button type="button" className={`btn small to-confirm-btn${counts.to_confirm ? " waiting" : ""}`} aria-pressed={pressed("to_confirm")}
                  data-testid="to-confirm" onClick={() => toggleStatus("to_confirm")} title={STATUS_MEANS.to_confirm}>
            <span>To confirm</span>
            <span className="chip" data-testid="to-confirm-count">{counts.to_confirm}</span>
          </button>
          {counts.to_decide > 0 && (
            <button type="button" className="btn small status-count" data-testid="status-decide" aria-pressed={pressed("to_decide")}
                    onClick={() => toggleStatus("to_decide")} title={STATUS_MEANS.to_decide}>To decide <span className="status-num">{counts.to_decide}</span></button>
          )}
          {counts.done > 0 && <span className="muted" data-testid="status-done">{counts.done} done</span>}
          {model.checking > 0 && <span className="muted status-note" data-testid="status-checking"
                                       title="What holds each study or product signed on the delivery is read from its card">
            checking {count(model.checking, "card")}…</span>}
          <span className="muted status-note" data-testid="status-in-model"
                title="What the model holds now: the client's data only once confirmed">
            In the model: {count(inModel.studies, "study", "studies")}{inModel.datasets !== inModel.studies ? ` (${plural(inModel.datasets, "dataset")})` : ""}
            {" "}· {plural(inModel.formulations, "formulation")} · {plural(inModel.values, "compound value")}
          </span>
          <CountsSaid ready={work.loaded && model.checking === 0 && !stale}
                      text={`${counts.missing} missing, ${counts.to_confirm} to confirm, ${counts.to_decide} to decide`} />
        </div>
        {next && ("href" in next
          ? <Link className="btn primary status-next" href={next.href} prefetch={false} data-testid="inputs-next">{next.text}</Link>
          : <button type="button" className="btn primary status-next" data-testid="inputs-next" onClick={next.go} title={next.text}>{next.text}</button>)}
      </div>
      <div className="area-bar" data-testid="area-bar">
        <Tabs label="Input areas" prefix="inputs" value={tab} onChange={setTab} tabs={tabs} className="area-tabs" />
      </div>
      {notice && <Banner tone={notice.ok ? "ok" : "err"} testId="inputs-notice">{notice.text}</Banner>}
      {running && literature.data && <LiteratureProgress r={literature.data} />}

      {tab === "todo" && (
        <TabPanel prefix="inputs" id="todo">
          <TodoTab projectId={projectId} work={model} run={run} status={status} only={only} onStatus={setStatus} onOnly={setOnly}
                   readiness={view.readiness?.content} selectionRule={view.selection_rule} onOpen={go} />
        </TabPanel>
      )}

      {tab === "compound" && (
        <TabPanel prefix="inputs" id="compound">
          {areaLine("compound")}
          {!only && literature.data?.sources && <SourcesRead run={literature.data.sources} />}
          {cardsFor("compound").length > 0 && (
            <section className="subject-cards" data-testid="compound-cards" aria-label="The client's compound values">
              <h2 className="area-section-title">The client&apos;s compound values</h2>
              {cardsFor("compound").map((s) => (
                <CompoundCard key={s.key} subject={s} env={env} open={cardOpen(s, opens(cardsFor("compound"), s))}
                              onToggle={() => toggleCard(s, opens(cardsFor("compound"), s))} />
              ))}
            </section>
          )}
          <SheetGroups projectId={projectId} groups={sheetsFor("compound").filter((g) => !only || g.state === "to_confirm")} run={run}
                       title="Sheets not linked to the compound yet" testId="compound-sheets" />
          {/* the model system (parent, metabolites; their dose fractions): a model input, so here since the console
              redesign's slice 4a (before, on the Run page); nothing when the project models one compound */}
          {!only && <SystemPanel projectId={projectId} />}
          {!only && <ValueReuse projectId={projectId} run={run} />}
          <InputRows rows={listed("compound")} todo={panelTodo("compound")} projectId={projectId} run={run} grouped
                   empty={only ? "Nothing on Compound needs you now." : "The compound's values appear here as the client's files, the literature and PubChem fill them."} />
          {!only && <AccessRequests projectId={projectId} run={run} />}</TabPanel>
      )}

      {tab === "formulations" && (
        <TabPanel prefix="inputs" id="formulations">
          {areaLine("formulations")}
          {products.length > 0 && (
            <section className="subject-cards" data-testid="product-cards" aria-label="The client's products">
              <h2 className="area-section-title">The client&apos;s products <span className="muted">({products.length})</span></h2>
              {products.map((s) => (
                <ProductCard key={s.key} subject={s} env={env} open={cardOpen(s, opens(products, s))}
                             onToggle={() => toggleCard(s, opens(products, s))}
                             profiles={profilesOf(s)} comparisons={dissolution?.comparisons ?? []} label={profileLabel}
                             problems={dissolution?.problems ?? []} release={releaseOf(s, view as unknown as InputsLike)} />
              ))}
            </section>
          )}
          <SheetGroups projectId={projectId} groups={sheetsFor("formulations").filter((g) => !only || g.state === "to_confirm")} run={run}
                       title="Sheets not linked to a product yet" testId="formulation-sheets" />
          {!only && unlinkedProfiles.length > 0 && (
            <Dissolution profiles={unlinkedProfiles} comparisons={dissolution?.comparisons ?? []} label={profileLabel} projectId={projectId}
                         run={run} product="" testId="dissolution-unlinked" problems={dissolution?.problems ?? []} />
          )}
          {!only && dissolutionNotes(dissolution?.profiles ?? [], dissolution?.problems ?? []).length > 0 && (
            <section className="card-section" data-testid="dissolution-notes">
              <h3 className="area-section-title">Notes on the dissolution data</h3>
              <ul className="flags">{dissolutionNotes(dissolution?.profiles ?? [], dissolution?.problems ?? []).map((x) => <li key={x}>{profileText(x)}</li>)}</ul>
            </section>
          )}
          {!only && <BriefList projectId={projectId} group="products" testId="inputs-products" addAt={addProduct}
                     fields={["name", "role", "dosage_form", "strength", "release", "attributes"]}
                     title="Products named in the proposal"
                     lede="Each product becomes its own formulation. Add its dissolution data; for a test against a reference, add the study that compares them." />}
          {solidRows.length > 0 && (
            <section className="card">
              <h3 className="mt-0">The formulation of each solid study</h3>
              <table>
                <tbody>
                  {solidRows.map(({ s, own }) => {
                    // its own entry of the way: the product its file names, and (round 7) another product's formulation the
                    // model would use for it; a choice of the formulation never starts on another product's for it
                    const mine = own?.each?.find((e) => normLabel(e.study) === normLabel(s.study_id));
                    return (
                      <tr key={s.study_id} data-testid={`formulation-${s.study_id}`}>
                        <td><strong>{s.study_id}</strong> <span className="muted">{valueWord(String(s.facts.formulation))}</span></td>
                        <td>{s.facts.formulation_name
                          // a study that names its formulation: the name, and while the model lacks it, what gives it (round 5)
                          ? <>{String(s.facts.formulation_name)}{own && <> {studyLever(s.study_id, own, true)}</>}</>
                          : formulations.length
                            ? <>{mine?.uses && studyLever(s.study_id, own)}
                                <FormulationChoice study={s.study_id} options={formulations} named={mine?.named} projectId={projectId} run={run} /></>
                            : studyLever(s.study_id, own)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
          )}
          <h3 className="area-section-title">Formulations in the model</h3>
          {/* a formulation is in the model once a product's dissolution profile is used as its release (OWN-10): said here */}
          <InputRows rows={listed("formulations")} todo={panelTodo("formulations")} projectId={projectId} run={run}
                     emptyTitle={only ? "Nothing else needs you here" : "No formulation in the model yet"}
                     empty={only ? "Nothing else on Products and dissolution needs you now."
                       : <>A formulation&apos;s release comes from a dissolution profile: on a product&apos;s card above, &ldquo;Use this profile
                         as the release&rdquo;. Confirming a product keeps its dissolution, but does not set the release. A solution needs
                         none.</>} />
        </TabPanel>
      )}

      {tab === "individuals" && (
        <TabPanel prefix="inputs" id="individuals">
          {areaLine("individuals")}
          {!only && <BriefList projectId={projectId} group="populations" testId="inputs-populations"
                     fields={["kind", "age_range", "sex", "ethnicity", "impairment_class", "genotype", "species"]}
                     title="The populations the proposal names"
                     lede="The populations the predictions are made for; each study below is simulated in its own individual." />}
          {panelTodo("individuals").filter((t) => t.kind !== "demographics").length > 0 && (
            <InputRows rows={[]} todo={panelTodo("individuals").filter((t) => t.kind !== "demographics")} projectId={projectId} run={run} empty="" />
          )}
          <h3 className="area-section-title">Each study&apos;s individual</h3>
          <StudyIndividuals studies={only ? studies.filter((s) => s.demographics === "missing") : studies} projectId={projectId} run={run} options={options}
                            subjects={model.subjects.filter((s) => s.kind === "study")} vocabulary={deliveryPage?.mappings[0]?.mapping_id ?? null}
                            onOpen={(_item, s) => openCard(s)} />
          {(!only || listed("individuals").length > 0) && <>
            <h3 className="area-section-title">Values set on the individual</h3>
            <InputRows rows={listed("individuals")} todo={[]} projectId={projectId} run={run}
                       empty="None yet: enzyme and transporter expression and individual values appear when a source gives them." />
          </>}
        </TabPanel>
      )}

      {tab === "settings" && (
        <TabPanel prefix="inputs" id="settings">
          {areaLine("settings")}
          <section className="settings-line" data-testid="settings-line">
            <p className="m-0">PK-Sim&apos;s default calculation methods and solver settings are used. Each study runs over its full sampling
              time. Dosing for predictions is set on Review &amp; sign.</p>
            {/* a setting that needs the person is shown without asking; otherwise "Change…" shows them */}
            {!settingsNeed && (
              <button type="button" className="btn small" aria-expanded={settingsOpen} onClick={() => setSettingsOpen(!settingsOpen)}
                      data-testid="settings-change">{settingsOpen ? "Hide the settings" : "Change…"}</button>
            )}
          </section>
          {(settingsOpen || settingsNeed) && (
            <>
              <InputRows rows={listed("settings")} todo={panelTodo("settings")} projectId={projectId} run={run}
                         empty={only ? "Nothing on Simulation settings needs you now." : "PK-Sim's default calculation methods are used: nothing to set."} />
              {used.length > 0 && (
                <section className="card" data-testid="settings-solver">
                  <h3 className="mt-0">Solver settings, per study</h3>
                  <table>
                    <tbody>
                      {used.map((s) => {
                        const solver = (s.facts.solver ?? {}) as Record<string, number>;
                        return (
                          <tr key={s.study_id}>
                            <td><strong>{s.study_id}</strong></td>
                            <td>{Object.keys(solver).length ? Object.entries(solver).map(([k, v]) => `${k} ${v}`).join(" · ")
                              : <span className="muted">PK-Sim&apos;s defaults</span>}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </section>
              )}
            </>
          )}
        </TabPanel>
      )}

      {tab === "studies" && (
        <TabPanel prefix="inputs" id="studies">{areaLine("studies")}
          <StudiesTab studies={studies} todo={panelTodo("studies")} projectId={projectId} run={run} options={options}
                      onIndividuals={toIndividual} client={client.data ?? undefined} intent={intent} only={only} env={env}
                      subjects={cardsFor("studies").filter((s) => s.kind === "study")} sheets={sheetsFor("studies")} /></TabPanel>
      )}

      {tab === "files" && (
        <TabPanel prefix="inputs" id="files">
          <ClientFilesTab projectId={projectId} client={client.data} work={model} only={only} onOnly={setOnly} run={run} act={clientAct}
                          onRetag={retag} onSaved={clientSaved} onOpen={(area) => setTab(area)} onItem={go} onOpenGroup={openGroup}
                          focus={cardFocus?.ref ? { subject: cardFocus.ref, at: cardFocus.at } : null} shown={shown} />
        </TabPanel>
      )}
    </PageShell>
    </ReachContext.Provider>
    </OpenSheetContext.Provider>
  );
}
