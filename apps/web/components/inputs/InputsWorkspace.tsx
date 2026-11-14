"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { BriefList } from "@/components/brief/BriefList";
import { type Act, Dissolution, type Retag, retagCall } from "@/components/client/ClientFiles";
import { useDeliveryRefresh } from "@/components/delivery/DeliverySection";
import type { View as ClientView } from "@/components/client/types";
import { Banner, InlineIssue, PageShell } from "@/components/kit";
import { TabPanel, Tabs } from "@/components/kit/Tabs";
import { narrow, send, type Envelope, type Narrow, type Schema } from "@/lib/api";
import { TAG_LABELS } from "@/lib/fileTags";
import { useMutation, useRefresh, useResource } from "@/lib/hooks";
import { areaHead, nextText, onDelivery, statusSummary, type WorkItem } from "@/lib/inputsWork";
import { type ArtifactView, STEP_ROUTES } from "@/lib/pipeline";
import { AREA_NAME, STATUS_MEANS, plural as count } from "@/lib/words";

import { AddDataMenu } from "./AddDataMenu";
import { ConfirmGroups } from "./ClientConfirm";
import { ClientFilesTab, type FilesShown } from "./ClientFilesTab";
import { StudyIndividuals } from "./IndividualsTab";
import { InputRows, type Row } from "./InputRows";
import type { Run, TodoItem } from "./InputsTodo";
import { AccessRequests } from "./ObservedDatasets";
import { useReadingRefresh } from "./ReadingTray";
import { type Intent, type Options, StudiesTab } from "./StudiesTab";
import { downloadTemplate, fileArea, whereShown } from "./TabFiles";
import { type Readiness, type StatusFilter, TodoTab } from "./TodoTab";
import { useInputsWork } from "./useInputsWork";
import { ValueReuse } from "./ValueReuse";

// The areas, in a bar across the top that stays in view (plan 2026-11-14 slice 1; the 2026-11-06 segmented-control
// decision): To do first, then the data domains (plan 2026-11-03 §3.2: the client's data land in their home, Products and
// dissolution, Clinical studies, Compound, never in an area of their own; the ids stay those of PK-Sim's building
// blocks), then the client's files themselves.
export type Tab = "todo" | "compound" | "formulations" | "individuals" | "settings" | "studies" | "files";
const TABS: [Tab, string][] = (["todo", "compound", "formulations", "studies", "individuals", "settings", "files"] as Tab[])
  .map((id) => [id, AREA_NAME[id]]);
const SOLID = ["ir_tablet", "ir_capsule", "mr", "suspension"];
const STATUSES: StatusFilter[] = ["missing", "to_confirm", "to_decide"];
const isTab = (t: string | undefined): t is Tab => TABS.some(([id]) => id === t);
const isStatus = (s: string | undefined): StatusFilter => (STATUSES.includes(s as StatusFilter) ? s as StatusFilter : null);

// GET /projects/{id}/inputs (InputsPage): the readiness, choices and the open items are typed here
type View = Narrow<Schema<"InputsPage">, {
  readiness: ArtifactView<Readiness & { split: Record<string, string[]> }> | null;
  todo: TodoItem[];
}>;

function FormulationChoice({ study, options, projectId, run }: { study: string; options: string[]; projectId: string; run: Run }) {
  const [value, setValue] = useState(options[0] ?? "");
  const [reason, setReason] = useState("");
  return (
    <div className="row gap-4">
      <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={`formulation of ${study}`}>
        {options.map((o) => <option key={o}>{o}</option>)}
      </select>
      <input placeholder="why" value={reason} onChange={(e) => setReason(e.target.value)} className="w-160" />
      <button className="btn" disabled={!reason.trim() || !value}
              onClick={() => void run(() => send("put", "/api/v1/projects/{project_id}/inputs/choices", { project_id: projectId },
                                                 { kind: "formulation", key: study, value, reason }), `${study}: ${value}.`)}>Choose</button>
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

/** Step 2 · Inputs (redesign §3.2): one workspace in PK-Sim's building blocks. Values flow in from every source not
 *  excluded and the source-selection rule keeps one per input (D-32). The frame (plan 2026-11-14 slice 1): a compact head
 *  with "Add data", the step bar, and a bar of areas that stays in view; To do lists the one list of work (slice 2,
 *  lib/inputsWork.ts), each item opening where it is settled, and Client files holds the files, their reading and the
 *  delivery. Every count on the page is read from that one list. The area and To do's filters are in the URL
 *  (`?tab=…&only=1&status=…`). Nothing is accepted here: the one review is at the MAP signature (D-27). */
export function InputsWorkspace({ projectId, initialTab, initialOnly, initialStatus, steps }: {
  projectId: string; initialTab?: string; initialOnly?: boolean; initialStatus?: string; steps?: ReactNode;
}) {
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
  // the card a To do row or "Next" opened: a sheet-form group in its area, a delivery subject in Client files
  const [groupFocus, setGroupFocus] = useState<{ group: string; at: number } | null>(null);
  const [subjectFocus, setSubjectFocus] = useState<{ subject: string; at: number } | null>(null);
  // the client files opened on their sheets, and the last sheet form saved, held while another area is shown
  const [filesOpen, setFilesOpen] = useState<ReadonlySet<string>>(new Set());
  const [lastSheet, rememberSheet] = useState<FilesShown["memory"]["last"]>(null);
  const shown: FilesShown = {
    open: filesOpen, memory: { last: lastSheet, remember: rememberSheet },
    toggle: (id) => setFilesOpen((was) => {
      const next = new Set(was);
      if (!next.delete(id)) next.add(id);
      return next;
    }),
  };
  const review = useResource("/api/v1/projects/{project_id}/client-review", { project_id: projectId });
  const literature = useResource("/api/v1/projects/{project_id}/literature-run", { project_id: projectId },
    { poll: (d) => d.running, interval: 5000 });
  const refresh = useRefresh();
  // a file read by code or by the agent brings values onto the cards, whichever area is open
  useDeliveryRefresh(projectId);
  useReadingRefresh(projectId);
  const assembled = useRef(false);
  const searching = useRef(false);
  const view = page.data;

  // the area the page opened on is kept once the work is read, so a list that empties does not move the page
  useEffect(() => {
    if (chosen === null && view && work.loaded) setChosen(model.counts.open ? "todo" : "compound");
  }, [chosen, view, work.loaded, model.counts.open]);
  // a link to another area of this page (Add data's "See each file on Inputs") changes the area and the filters without a
  // new page; the URL this page writes itself says what the page already shows
  const urlTab = url.get("tab") ?? undefined, urlOnly = url.get("only") === "1", urlStatus = url.get("status") ?? undefined;
  useEffect(() => { if (isTab(urlTab)) setChosen(urlTab); }, [urlTab]);
  useEffect(() => { setOnlyState(urlOnly); }, [urlOnly]);
  useEffect(() => { setStatusState(isStatus(urlStatus)); }, [urlStatus]);

  const run: Run = async <T,>(fn: () => Promise<Envelope<T>>, ok: string) => {
    const { problem } = await mutation.run(fn);
    setNotice(problem ? { ok: false, text: problem } : ok ? { ok: true, text: ok } : null);
    return problem;
  };

  // a file's tag files it under the area of its data (plan 2026-11-05 §3.1): changed, the file moves there
  const retag: Retag = (file, kind) => run(retagCall(projectId, file, kind),
                                           `${file.file}: ${TAG_LABELS[kind].toLowerCase()}, ${whereShown(kind)}.`);
  const clientAct: Act = (fn) => run(fn, "");
  const clientSaved = async (m: string) => setNotice({ ok: true, text: m });

  // the literature agent's end is said once, with what it found, when the page saw it searching
  const running = literature.data?.running ?? false;
  useEffect(() => {
    if (running) searching.current = true;
    else if (searching.current && literature.data) {
      searching.current = false;
      setNotice({ ok: true, text: `The literature agent finished: ${plural(literature.data.proposed, "value")} proposed, in the rows below.` });
      void refresh();
    }
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  async function askLiterature() {
    const problem = await run(() => send("post", "/api/v1/projects/{project_id}/evidence:research", { project_id: projectId }),
                              "PubChem, the FDA label and ChEMBL are being read; then the literature agent searches what is still missing.");
    if (problem && /already in progress/.test(problem)) {   // started elsewhere: its progress is shown, not a refusal
      setNotice(null);
      await refresh();
    }
  }

  // the inputs follow every change on the server; a page opened after a change upstream (the brief) assembles them once
  const stale = view && (!view.readiness || view.readiness.status === "STALE");
  useEffect(() => {
    if (!stale || assembled.current) return;
    assembled.current = true;
    // in the background: it reports only a problem, so it never wipes the message of what the person just did
    void mutation.run(() => send("post", "/api/v1/projects/{project_id}/inputs:assemble", { project_id: projectId }))
      .then(({ problem }) => { if (problem) setNotice({ ok: false, text: problem }); });
  }, [stale]); // eslint-disable-line react-hooks/exhaustive-deps

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
  // the client's data, by the domain it lands in (plan 2026-11-03 §3.3)
  const groups = review.data?.groups ?? [];
  const groupsFor = (t: Tab) => groups.filter((g) => g.tab === t && (!only || g.state === "to_confirm"));
  // a sheet-form card of a study or product also signed on the delivery: both paths stay open (plan §2.2.1), and the
  // card says so
  const onBoth = new Set(model.subjects.filter((s) => s.path === "delivery" && !s.done).flatMap((s) => s.groups.map((g) => g.id)));
  const confirmHere = (t: Tab) => <ConfirmGroups projectId={projectId} groups={groupsFor(t)} run={run} focus={groupFocus} onDelivery={onBoth} />;
  const forTab = (t: Tab) => todo.filter((i) => (i.tab ?? "compound") === t);
  // a group to confirm is settled on its own card, above the panel: listed in To do, not twice in the panel
  const panelTodo = (t: Tab) => forTab(t).filter((i) => i.kind !== "confirm");
  // a row to fill ("empty": a model input the data plan owns with no value yet) is shown by slice 5 of the task-first
  // plan; until then each tab lists what it listed
  const rows = (t: Tab) => (view.compound as Row[]).filter((r) => r.tab === t && r.state !== "empty");
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
                                                            { project_id: projectId }, { template_id: templateId }));
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
  const setTab = (t: Tab) => { setChosen(t); sync(t, only, t === "todo" ? status : null); if (t !== "todo") setStatusState(null); };
  const setOnly = (o: boolean) => { setOnlyState(o); sync(tab, o, status); };
  const setStatus = (s: StatusFilter) => { setStatusState(s); setChosen("todo"); sync("todo", only, s); };
  // a status-line count opens To do narrowed to its word; pressed again, To do shows every item
  const toggleStatus = (s: Exclude<StatusFilter, null>) => setStatus(tab === "todo" && status === s ? null : s);

  /** Bring an element of the area just opened into view (it is drawn once the area shows it), and mark it a moment. */
  function bringIntoView(testId: string) {
    let tries = 0;
    const find = () => {
      const el = document.querySelector<HTMLElement>(`[data-testid="${CSS.escape(testId)}"]`);
      if (!el) { if (++tries < 30) window.setTimeout(find, 100); return; }
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      el.classList.add("just-opened");
      window.setTimeout(() => el.classList.remove("just-opened"), 1600);
    };
    window.setTimeout(find, 50);
  }
  /** Open where a work item is settled: its area, its card (a sheet-form group, a delivery subject) or its file's row. */
  function go(item: WorkItem) {
    const w = item.where;
    setTab(w.tab);
    const at = Date.now();
    if (w.subject) setSubjectFocus({ subject: w.subject, at });
    if (w.file && !filesOpen.has(w.file)) setFilesOpen((was) => new Set([...was, w.file!]));
    const group = item.issue?.group ?? (w.anchor?.startsWith("group-") ? w.anchor.slice("group-".length) : null);
    if (group) setGroupFocus({ group, at });
    if (w.anchor) bringIntoView(w.anchor);
  }
  const openGroup = (group: string, t: Tab) => { setTab(t); setGroupFocus({ group, at: Date.now() }); bringIntoView(`group-${group}`); };
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
  // each area's one line: what it holds and what is open in it, counted from the same list as its badge; the cards of
  // its studies or products signed on the delivery, which open in Client files until they move into their area (slice
  // 3), named with what is open on each; "Only what needs me" (in the URL, as on To do and Client files) leaves out
  // what is done and what is there to read (the proposal's lists, the sources read, every dataset)
  const areaLine = (t: Exclude<Tab, "todo" | "files">) => {
    const there = onDelivery(model, t);
    return (
      <>
        <div className="area-head-row">
          <p className="area-head" data-testid={`area-head-${t}`}>{areaHead(model, t)}</p>
          <label className="only-mine">
            <input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} data-testid={`only-${t}`} />
            Only what needs me
          </label>
        </div>
        {there.length > 0 && (
          <p className="area-elsewhere muted" data-testid={`area-elsewhere-${t}`}>
            {count(there.length, t === "studies" ? "study is" : "product is", t === "studies" ? "studies are" : "products are")} signed on the
            delivery: {there.length === 1 ? "its card is" : "their cards are"} in Client files for now, counted here.{" "}
            {there.map(({ subject, open, confirm }, i) => (
              <span key={subject.key}>
                {i > 0 && " · "}
                <button type="button" className="link-btn" data-testid={`area-elsewhere-${t}-${subject.row!.subject}`}
                        onClick={() => confirm && go(confirm)}>{subject.label}</button>
                {open.length > 0 && <span> ({statusSummary(open)})</span>}
              </span>
            ))}
          </p>
        )}
      </>
    );
  };

  return (
    <PageShell {...head}
      actions={(
        <AddDataMenu projectId={projectId} run={run}
                     onTemplate={() => void downloadTemplate(client.data?.template).then((p) => { if (p) setNotice({ ok: false, text: p }); })}
                     onDigitize={() => startStudies("digitize")} onTypeTable={() => startStudies("type")}
                     onFindObserved={client.data?.agents.enabled ? () => {
                       setTab("studies");
                       void run(() => send("post", "/api/v1/projects/{project_id}/evidence:research", { project_id: projectId }, undefined, { agent: "A3" }),
                                "The observed-data agent is searching; datasets appear under Every dataset as it records them.");
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
            In the model: {count(inModel.studies, "study", "studies")} · {plural(inModel.formulations, "formulation")} · {plural(inModel.values, "compound value")}
          </span>
          <span className="sr-only" aria-live="polite">{`${counts.missing} missing, ${counts.to_confirm} to confirm, ${counts.to_decide} to decide`}</span>
        </div>
        {next && ("href" in next
          ? <Link className="btn primary status-next" href={next.href} data-testid="inputs-next">{next.text}</Link>
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
          {!only && literature.data?.sources && <SourcesRead run={literature.data.sources} />}{confirmHere("compound")}
          {!only && <ValueReuse projectId={projectId} run={run} />}
          <InputRows rows={listed("compound")} todo={panelTodo("compound")} projectId={projectId} run={run} grouped
                   empty={only ? "Nothing on Compound needs you now." : "The compound's values appear here as the client's files, the literature and PubChem fill them."} />
          {!only && <AccessRequests projectId={projectId} run={run} />}</TabPanel>
      )}

      {tab === "formulations" && (
        <TabPanel prefix="inputs" id="formulations">{areaLine("formulations")}{confirmHere("formulations")}
          <>
          {!only && <BriefList projectId={projectId} group="products" testId="inputs-products"
                     fields={["name", "role", "dosage_form", "strength", "release", "attributes"]}
                     title="The products the proposal names"
                     lede="Each product is built as its own formulation; the data plan asks for its dissolution and, for a test and its reference, the study that compares them." />}
          <InputRows rows={listed("formulations")} todo={panelTodo("formulations")} projectId={projectId} run={run}
                     empty={only ? "Nothing else on Products and dissolution needs you now." : "No formulation yet: a solution needs none; a tablet's release comes from its dissolution profile or the literature."} />
          {used.some((s) => SOLID.includes(String(s.facts.formulation)) && (!only || !s.facts.formulation_name)) && (
            <section className="card">
              <h3 className="mt-0">The formulation of each solid study</h3>
              <table>
                <tbody>
                  {used.filter((s) => SOLID.includes(String(s.facts.formulation)) && (!only || !s.facts.formulation_name)).map((s) => (
                    <tr key={s.study_id} data-testid={`formulation-${s.study_id}`}>
                      <td><strong>{s.study_id}</strong> <span className="muted">{String(s.facts.formulation).replace("_", " ")}</span></td>
                      <td>{s.facts.formulation_name ? String(s.facts.formulation_name)
                        : formulations.length ? <FormulationChoice study={s.study_id} options={formulations} projectId={projectId} run={run} />
                          : <span className="muted">no formulation in the model yet</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
          {client.data && client.data.dissolution.profiles.length > 0 && (
            <Dissolution projectId={projectId} d={client.data.dissolution}
                         act={async (fn) => run(fn, "The release model is proposed; its values flow into the formulation.")} />
          )}
          </>
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
          {!only && <>
          <h3>Each study&apos;s individual</h3>
          <StudyIndividuals studies={studies} projectId={projectId} run={run} options={options} />
          <h3>Values set on the individual</h3>
          <InputRows rows={listed("individuals")} todo={[]} projectId={projectId} run={run}
                     empty="None: enzyme and transporter expression and individual values appear here when a source gives them." />
          </>}
          {only && listed("individuals").length > 0 && <InputRows rows={listed("individuals")} todo={[]} projectId={projectId} run={run} empty="" />}
        </TabPanel>
      )}

      {tab === "settings" && (
        <TabPanel prefix="inputs" id="settings">
          {areaLine("settings")}
          <InputRows rows={listed("settings")} todo={panelTodo("settings")} projectId={projectId} run={run}
                     empty={only ? "Nothing on Simulation settings needs you now." : "The calculation methods are PK-Sim's defaults unless the published model sets them."} />
          {!only && <section className="card">
            <h3 className="mt-0">Solver settings</h3>
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
            <InlineIssue severity="note">Each study is simulated over its whole sampled window. Prediction regimens are applications,
              set on Review &amp; sign.</InlineIssue>
          </section>}
        </TabPanel>
      )}

      {tab === "studies" && (
        <TabPanel prefix="inputs" id="studies">{areaLine("studies")}{confirmHere("studies")}<StudiesTab studies={studies} todo={panelTodo("studies")} projectId={projectId} run={run} options={options}
                    onIndividuals={() => setTab("individuals")} client={client.data ?? undefined} intent={intent} only={only} /></TabPanel>
      )}

      {tab === "files" && (
        <TabPanel prefix="inputs" id="files">
          <ClientFilesTab projectId={projectId} client={client.data} work={model} only={only} onOnly={setOnly} run={run} act={clientAct}
                          onRetag={retag} onSaved={clientSaved} onOpen={(area) => setTab(area)} onItem={go} onOpenGroup={openGroup}
                          focus={subjectFocus} shown={shown} />
        </TabPanel>
      )}
    </PageShell>
  );
}
