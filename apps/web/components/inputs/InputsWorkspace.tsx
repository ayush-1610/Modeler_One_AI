"use client";

import Link from "next/link";
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
import { type ArtifactView, STEP_ROUTES } from "@/lib/pipeline";

import { AddDataMenu } from "./AddDataMenu";
import { ConfirmGroups } from "./ClientConfirm";
import { ClientFilesTab, type FilesShown } from "./ClientFilesTab";
import { StudyIndividuals } from "./IndividualsTab";
import { InputRows, type Row } from "./InputRows";
import { ORDER, type Run, type TodoItem } from "./InputsTodo";
import { AccessRequests } from "./ObservedDatasets";
import { useReadingRefresh } from "./ReadingTray";
import { type Intent, type Options, StudiesTab } from "./StudiesTab";
import { downloadTemplate, fileArea, whereShown } from "./TabFiles";
import { type Readiness, TodoTab, todoText } from "./TodoTab";
import { ValueReuse } from "./ValueReuse";

// The areas, in a bar across the top that stays in view (plan 2026-11-14 slice 1; the 2026-11-06 segmented-control
// decision): To do first, then the data domains (plan 2026-11-03 §3.2: the client's data land in their home, Products and
// dissolution, Clinical studies, Compound, never in an area of their own; the ids stay those of PK-Sim's building
// blocks), then the client's files themselves.
export type Tab = "todo" | "compound" | "formulations" | "individuals" | "settings" | "studies" | "files";
type Area = Exclude<Tab, "todo" | "files">;
const TABS: [Tab, string][] = [["todo", "To do"], ["compound", "Compound"], ["formulations", "Products and dissolution"],
                               ["studies", "Clinical studies"], ["individuals", "Populations and individuals"],
                               ["settings", "Simulation settings"], ["files", "Client files"]];
const AREAS = TABS.filter(([id]) => id !== "todo" && id !== "files") as [Area, string][];
const SOLID = ["ir_tablet", "ir_capsule", "mr", "suspension"];
// the to-do's kinds a person settles by choosing (the status word "To decide", plan 2026-11-14 §2 rule 5); a group to
// confirm is "To confirm"; every other kind is something "Missing". Slice 2 counts from the one work model instead.
const DECIDE = new Set(["conflict", "correct", "pka", "review", "formulation", "process", "unit"]);

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
 *  with "Add data", the step bar, and a bar of areas that stays in view; To do says what is still missing to run, each
 *  item opening where it is settled, and Client files holds the files, their reading and the Delivery review. Nothing is
 *  accepted here: the one review is at the MAP signature (D-27). */
export function InputsWorkspace({ projectId, initialTab, steps }: { projectId: string; initialTab?: Tab; steps?: ReactNode }) {
  const page = useResource("/api/v1/projects/{project_id}/inputs", { project_id: projectId }, { select: (d) => narrow<View>(d) });
  const client = useResource("/api/v1/projects/{project_id}/client-data", { project_id: projectId },
    { select: (d) => narrow<ClientView>(d), poll: (d) => d.running });
  const mutation = useMutation();
  // an explicit ?tab= wins; otherwise the page opens on To do while anything is still missing, else on Compound
  const [chosen, setTab] = useState<Tab | null>(TABS.some(([id]) => id === initialTab) ? initialTab! : null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [onlyToConfirm, setOnlyToConfirm] = useState(false);
  const [intent, setIntent] = useState<Intent | null>(null);
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
  const delivery = useDeliveryRefresh(projectId);
  useReadingRefresh(projectId);
  const assembled = useRef(false);
  const searching = useRef(false);
  const view = page.data;

  // the area the page opened on is kept once the inputs are read, so a list that empties does not move the page
  useEffect(() => {
    if (chosen === null && view) setTab(view.todo.length ? "todo" : "compound");
  }, [chosen, view]);
  // a link to another area of this page (Add data's "See each file on Inputs") changes ?tab= without a new page
  useEffect(() => {
    if (initialTab && TABS.some(([id]) => id === initialTab)) setTab(initialTab);
  }, [initialTab]);

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

  const head = { tone: "inputs" as const, steps, eyebrow: "Step 2 of 4", title: "Inputs", noReveal: true,
                 lede: "Fill in what the model needs and confirm the client's data." };
  if (page.problem || !view) {
    return (
      <PageShell {...head}>
        {page.problem ? <div className="banner err">{page.problem}</div> : <p className="muted">Loading the inputs…</p>}
      </PageShell>
    );
  }

  const tab: Tab = chosen ?? (view.todo.length ? "todo" : "compound");
  const todo = [...view.todo].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
  // the client's data, by the domain it lands in (plan 2026-11-03 §3.3); "To confirm" shows only what waits for you
  const toConfirm = review.data?.to_confirm ?? 0;
  const groups = review.data?.groups ?? [];
  const groupsFor = (t: Tab) => groups.filter((g) => g.tab === t && (!onlyToConfirm || g.state === "to_confirm"));
  const confirmHere = (t: Tab) => (
    <>
      <ConfirmGroups projectId={projectId} groups={groupsFor(t)} run={run} />
      {onlyToConfirm && groupsFor(t).length === 0 && <p className="muted" data-testid="nothing-to-confirm">Nothing from the client
        waits for you in this area.</p>}
    </>
  );
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

  function open(t: TodoItem) {
    setOnlyToConfirm(false);
    setTab((t.tab ?? "compound") as Tab);
    // a group to confirm is settled on its own card; every other item on its row in the area's list
    const id = t.kind === "confirm" ? `group-${t.target}` : `todo-${t.kind}-${t.target}`;
    window.setTimeout(() => document.getElementById(id)?.scrollIntoView({ block: t.kind === "confirm" ? "start" : "center", behavior: "smooth" }), 50);
  }
  // a block of the Delivery review, in Client files (it is read once the area shows it)
  function openFiles(block: string) {
    setOnlyToConfirm(false);
    setTab("files");
    let tries = 0;
    const find = () => {
      const el = document.querySelector(`[data-testid="${block}"]`);
      if (el) el.scrollIntoView({ block: "start", behavior: "smooth" });
      else if (++tries < 20) window.setTimeout(find, 100);
    };
    window.setTimeout(find, 50);
  }
  // a tool the head's "Add data" opens on Clinical studies
  function startStudies(what: Intent["what"]) {
    setOnlyToConfirm(false);
    setTab("studies");
    setIntent({ what, at: Date.now() });
  }

  // "To confirm" filters the areas; pressed on To do or Client files, it opens the first area with something to confirm
  function toggleToConfirm() {
    const on = !onlyToConfirm;
    setOnlyToConfirm(on);
    if (on && (tab === "todo" || tab === "files")) {
      setTab(AREAS.find(([id]) => groups.some((g) => g.tab === id && g.state === "to_confirm"))?.[0] ?? "studies");
    }
  }

  // the status line (plan 2026-11-14 §2; slice 1): the to-do by status word, "To confirm", the delivery's open work, and
  // the page's one primary button, "Next". The delivery's table layouts and values with no study come first while a
  // study or product still confirms on the delivery (they hold its signature); otherwise the to-do's order holds.
  const missing = todo.filter((t) => t.kind !== "confirm" && !DECIDE.has(t.kind)).length;
  const decide = todo.filter((t) => DECIDE.has(t.kind)).length;
  const layouts = delivery?.enabled ? delivery.mappings.length : 0;
  const unlinked = delivery?.enabled ? delivery.totals.values_unassigned : 0;
  const holds = Boolean(delivery?.enabled && delivery.subjects.some((s) => s.confirm_on === "delivery" && !s.confirmation?.current));
  const ready = !todo.length && Boolean(view.readiness?.content?.ready);
  const groupTitle = (id: string) => groups.find((g) => g.id === id)?.title;
  const next: { text: string; go: () => void } | { text: string; href: string } | null =
    holds && layouts ? { text: `Next: Check how ${plural(layouts, "table")} ${layouts === 1 ? "is" : "are"} read`, go: () => openFiles("delivery-mappings") }
      : holds && unlinked ? { text: `Next: Link ${plural(unlinked, "value")} to a study or product`, go: () => openFiles("delivery-unassigned") }
        : todo.length ? { text: `Next: ${todoText(todo[0], groupTitle)}`, go: () => open(todo[0]) }
          : ready ? { text: "Next: Review & sign", href: STEP_ROUTES.review(projectId) } : null;
  const showTodo = () => { setOnlyToConfirm(false); setTab("todo"); };

  const tabs = TABS.map(([id, label]) => (
    id === "todo" ? { id, label, count: todo.length, countLabel: "to do", testId: "tab-todo" }
      : id === "files" ? { id, label, count: files.length, countLabel: files.length === 1 ? "file" : "files", testId: "tab-files",
                           badge: unplaced > 0 ? <span className="chip medium" data-testid="files-unplaced"
                                                       title="files not filed under an area yet: say what each is">{unplaced} to place</span> : null }
        : { id, label, count: forTab(id).length, testId: `tab-${id}` }
  ));

  return (
    <PageShell {...head}
      actions={(
        <AddDataMenu projectId={projectId} run={run}
                     onTemplate={() => void downloadTemplate(client.data?.template).then((p) => { if (p) setNotice({ ok: false, text: p }); })}
                     onDigitize={() => startStudies("digitize")} onTypeTable={() => startStudies("type")}
                     onFindObserved={client.data?.agents.enabled ? () => {
                       setOnlyToConfirm(false);
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
          {files.length > 0 && <span className="muted">{plural(files.length, "client file")}</span>}
          {ready && <strong className="status-ready" data-testid="status-ready">Inputs are ready</strong>}
          {missing > 0 && (
            <button type="button" className="btn small status-count" data-testid="status-missing" onClick={showTodo}
                    title="What the model still needs, listed in To do">Missing <span className="status-num">{missing}</span></button>
          )}
          {decide > 0 && (
            <button type="button" className="btn small status-count" data-testid="status-decide" onClick={showTodo}
                    title="Choices only a person can make, listed in To do">To decide <span className="status-num">{decide}</span></button>
          )}
          <button type="button" className={`btn small to-confirm-btn${toConfirm ? " waiting" : ""}`} aria-pressed={onlyToConfirm}
                  data-testid="to-confirm" onClick={toggleToConfirm} title="Show only the client's data that waits for your confirmation">
            <span>{onlyToConfirm ? "Showing what to confirm" : "To confirm"}</span>
            <span className="chip" data-testid="to-confirm-count">{toConfirm}</span>
          </button>
          {(layouts > 0 || unlinked > 0) && (
            <button type="button" className="link-btn" data-testid="status-delivery" onClick={() => openFiles("delivery-section")}>
              Delivery review: {[layouts ? `${plural(layouts, "table layout")} to check` : "", unlinked ? `${plural(unlinked, "value")} with no study` : ""]
                .filter(Boolean).join(" · ")}
            </button>
          )}
          <span className="sr-only" aria-live="polite">{`${missing} missing, ${decide} to decide, ${toConfirm} to confirm`}</span>
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
          <TodoTab projectId={projectId} todo={todo} areas={AREAS.map(([id, label]) => ({ id, label }))}
                   groupTitle={groupTitle} readiness={view.readiness?.content}
                   selectionRule={view.selection_rule} onOpen={open} />
        </TabPanel>
      )}

      {tab === "compound" && (
        <TabPanel prefix="inputs" id="compound">
          {!onlyToConfirm && literature.data?.sources && <SourcesRead run={literature.data.sources} />}{confirmHere("compound")}
          {!onlyToConfirm && <><ValueReuse projectId={projectId} run={run} />
          <InputRows rows={rows("compound")} todo={panelTodo("compound")} projectId={projectId} run={run} grouped
                   empty="The compound's values appear here as the client's files, the literature and PubChem fill them." />
          <AccessRequests projectId={projectId} run={run} /></>}</TabPanel>
      )}

      {tab === "formulations" && (
        <TabPanel prefix="inputs" id="formulations">{confirmHere("formulations")}
          {!onlyToConfirm && <>
          <BriefList projectId={projectId} group="products" testId="inputs-products"
                     fields={["name", "role", "dosage_form", "strength", "release", "attributes"]}
                     title="The products the proposal names"
                     lede="Each product is built as its own formulation; the data plan asks for its dissolution and, for a test and its reference, the study that compares them." />
          <InputRows rows={rows("formulations")} todo={panelTodo("formulations")} projectId={projectId} run={run}
                     empty="No formulation yet: a solution needs none; a tablet's release comes from its dissolution profile or the literature." />
          {used.some((s) => SOLID.includes(String(s.facts.formulation))) && (
            <section className="card">
              <h3 className="mt-0">The formulation of each solid study</h3>
              <table>
                <tbody>
                  {used.filter((s) => SOLID.includes(String(s.facts.formulation))).map((s) => (
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
          </>}
        </TabPanel>
      )}

      {tab === "individuals" && (
        <TabPanel prefix="inputs" id="individuals">
          <BriefList projectId={projectId} group="populations" testId="inputs-populations"
                     fields={["kind", "age_range", "sex", "ethnicity", "impairment_class", "genotype", "species"]}
                     title="The populations the proposal names"
                     lede="The populations the predictions are made for; each study below is simulated in its own individual." />
          {panelTodo("individuals").filter((t) => t.kind !== "demographics").length > 0 && (
            <InputRows rows={[]} todo={panelTodo("individuals").filter((t) => t.kind !== "demographics")} projectId={projectId} run={run} empty="" />
          )}
          <h3>Each study&apos;s individual</h3>
          <StudyIndividuals studies={studies} projectId={projectId} run={run} options={options} />
          <h3>Values set on the individual</h3>
          <InputRows rows={rows("individuals")} todo={[]} projectId={projectId} run={run}
                     empty="None: enzyme and transporter expression and individual values appear here when a source gives them." />
        </TabPanel>
      )}

      {tab === "settings" && (
        <TabPanel prefix="inputs" id="settings">
          <InputRows rows={rows("settings")} todo={panelTodo("settings")} projectId={projectId} run={run}
                     empty="The calculation methods are PK-Sim's defaults unless the published model sets them." />
          <section className="card">
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
          </section>
        </TabPanel>
      )}

      {tab === "studies" && (
        <TabPanel prefix="inputs" id="studies">{confirmHere("studies")}{!onlyToConfirm && <StudiesTab studies={studies} todo={panelTodo("studies")} projectId={projectId} run={run} options={options}
                    onIndividuals={() => setTab("individuals")} client={client.data ?? undefined} intent={intent} />}</TabPanel>
      )}

      {tab === "files" && (
        <TabPanel prefix="inputs" id="files">
          <ClientFilesTab projectId={projectId} client={client.data} run={run} act={clientAct} onRetag={retag} onSaved={clientSaved}
                          onOpen={(area) => { setOnlyToConfirm(false); setTab(area); }} shown={shown} />
        </TabPanel>
      )}
    </PageShell>
  );
}
