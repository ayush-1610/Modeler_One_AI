"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { BriefList } from "@/components/brief/BriefList";
import { type Act, Dissolution, FileTagLine, type Retag, retagCall } from "@/components/client/ClientFiles";
import type { View as ClientView } from "@/components/client/types";
import { Banner, InlineIssue, PageShell, SidePanel } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { TabPanel, Tabs } from "@/components/kit/Tabs";
import { narrow, send, type Envelope, type Narrow, type Schema } from "@/lib/api";
import { TAG_LABELS } from "@/lib/fileTags";
import { useMutation, useRefresh, useResource } from "@/lib/hooks";
import { type ArtifactView, STEP_ROUTES } from "@/lib/pipeline";

import { ConfirmGroups } from "./ClientConfirm";
import { StudyIndividuals } from "./IndividualsTab";
import { InputRows, type Row } from "./InputRows";
import { LABEL, ORDER, type Run, TITLE, type TodoItem } from "./InputsTodo";
import { AccessRequests } from "./ObservedDatasets";
import { type Options, StudiesTab } from "./StudiesTab";
import { AREA_LABEL, fileArea, FilesBar, FilesHere, whereShown } from "./TabFiles";

// The data domains down the left (plan 2026-11-03 §3.2): the client's data lands in its home (Products and dissolution,
// Clinical studies, Compound), never in an area of its own. The ids stay those of PK-Sim's building blocks.
export type Tab = "compound" | "formulations" | "individuals" | "settings" | "studies";
const TABS: [Tab, string][] = [["compound", "Compound"], ["formulations", "Products and dissolution"],
                               ["studies", "Clinical studies"], ["individuals", "Populations and individuals"],
                               ["settings", "Simulation settings"]];
const TAB_LABEL = Object.fromEntries(TABS) as Record<Tab, string>;
const SOLID = ["ir_tablet", "ir_capsule", "mr", "suspension"];

type Check = { check: string; ok: boolean; detail: string[] };
// GET /projects/{id}/inputs (InputsPage): the readiness, choices and the open items are typed here
type View = Narrow<Schema<"InputsPage">, {
  readiness: ArtifactView<{ ready: boolean; checks: Check[]; split: Record<string, string[]>; engine_dry_run: string }> | null;
  todo: TodoItem[];
}>;

function FormulationChoice({ study, options, projectId, run }: { study: string; options: string[]; projectId: string; run: Run }) {
  const [value, setValue] = useState(options[0] ?? "");
  const [reason, setReason] = useState("");
  return (
    <div className="row" style={{ gap: 4 }}>
      <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={`formulation of ${study}`}>
        {options.map((o) => <option key={o}>{o}</option>)}
      </select>
      <input placeholder="why" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 160 }} />
      <button className="btn" disabled={!reason.trim() || !value}
              onClick={() => void run(() => send("put", "/api/v1/projects/{project_id}/inputs/choices", { project_id: projectId },
                                                 { kind: "formulation", key: study, value, reason }), `${study}: ${value}.`)}>Choose</button>
    </div>
  );
}

type ClientFile = ClientView["files"][number];
type LiteratureRun = Schema<"LiteratureRun">;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The literature agent at work (plan 2026-11-05 §3.3): how long, how far into its budget, and what it found so far;
 *  in place of a red "already running". */
function LiteratureProgress({ r }: { r: LiteratureRun }) {
  const minutes = r.run ? Math.max(0, Math.round((Date.now() - new Date(r.run.started_at).getTime()) / 60000)) : null;
  return (
    <Banner tone="ok" testId="literature-progress">
      The literature agent is searching{minutes !== null ? ` (${minutes} min so far)` : ""}: turn {r.turns}
      {r.max_turns ? ` of at most ${r.max_turns}` : ""}, {plural(r.proposed, "value")} proposed so far. They flow into the rows
      when it finishes; you can keep working meanwhile.
    </Banner>
  );
}

/** What each of the client's files gave and what it is (plan 2026-11-03 §3.2, 2026-11-05 §3.1): a drawer over the page,
 *  not an area of its own; each file opens in the area of its data, and a file not placed yet says so. The Document
 *  Library holds the files themselves. */
function FilesDrawer({ projectId, files, onClose, onRetag, onOpen }: {
  projectId: string; files: ClientFile[]; onClose: () => void; onRetag: Retag; onOpen: (area: Tab, file: ClientFile) => void;
}) {
  const gave = (f: ClientFile) => {
    const parts = [
      f.template ? "the client-data template, read cell by cell" : "",
      f.datasets?.length ? `${f.datasets.length} dataset${f.datasets.length === 1 ? "" : "s"}` : "",
      f.evidence?.length ? `${f.evidence.length} value${f.evidence.length === 1 ? "" : "s"}` : "",
      f.dissolution?.length || f.mappings?.some((m) => m.dissolution_records) ? "dissolution data" : "",
      f.triage?.length && !f.template ? `${f.triage.length} sheet${f.triage.length === 1 ? "" : "s"} sorted` : "",
    ].filter(Boolean);
    return parts.length ? parts.join(" · ") : "stored; nothing read from it yet";
  };
  return (
    <Dialog title="The client's files" size="peek" onClose={onClose} testId="inputs-files-drawer" dismiss>
      <p className="muted peek-where">What each file gave this project. The files themselves are in the{" "}
        <Link href={`/projects/${encodeURIComponent(projectId)}/library`}>Document Library</Link>.</p>
      <div className="peek-body">
        {files.length === 0 ? <p className="muted">No client file yet: add them with “+ Add data”.</p> : (
          <ul className="files-drawer">
            {files.map((f) => (
              <li key={f.id} data-testid={`inputs-file-${f.file}`}>
                <div className="spread">
                  <span className="peek-file">{f.file}</span>
                  {fileArea(f) ? (
                    <button type="button" className="link-btn" data-testid={`open-file-${f.file}`}
                            onClick={() => onOpen(fileArea(f) as Tab, f)}>Open on {AREA_LABEL[fileArea(f)!]}</button>
                  ) : <span className="chip medium">not placed: say what it is</span>}
                </div>
                <span className="muted">{gave(f)}</span>
                <FileTagLine file={f} onRetag={onRetag} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="dialog-actions"><button type="button" className="btn" onClick={onClose}>Close</button></div>
    </Dialog>
  );
}

/** Step 2 · Inputs (redesign §3.2): one workspace in PK-Sim's building blocks. Values flow in from every source not
 *  excluded and the source-selection rule keeps one per input (D-32); the side list says what is still missing to run,
 *  and each item opens where it is settled. Nothing is accepted here: the one review is at the MAP signature (D-27). */
export function InputsWorkspace({ projectId, initialTab = "compound" }: { projectId: string; initialTab?: Tab }) {
  const page = useResource("/api/v1/projects/{project_id}/inputs", { project_id: projectId }, { select: (d) => narrow<View>(d) });
  const client = useResource("/api/v1/projects/{project_id}/client-data", { project_id: projectId },
    { select: (d) => narrow<ClientView>(d), poll: (d) => d.running });
  const mutation = useMutation();
  const [tab, setTab] = useState<Tab>(TABS.some(([id]) => id === initialTab) ? initialTab : "compound");
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [onlyToConfirm, setOnlyToConfirm] = useState(false);
  const review = useResource("/api/v1/projects/{project_id}/client-review", { project_id: projectId });
  const literature = useResource("/api/v1/projects/{project_id}/literature-run", { project_id: projectId },
    { poll: (d) => d.running, interval: 5000 });
  const refresh = useRefresh();
  const assembled = useRef(false);
  const searching = useRef(false);
  const view = page.data;

  const run: Run = async <T,>(fn: () => Promise<Envelope<T>>, ok: string) => {
    const { problem } = await mutation.run(fn);
    setNotice(problem ? { ok: false, text: problem } : ok ? { ok: true, text: ok } : null);
    return problem;
  };

  // a file's tag places it in the area of its data (plan 2026-11-05 §3.1): changed, the file moves there
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
                              "The literature agent is searching; its values flow into the rows when it finishes.");
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

  if (page.problem) return <div className="banner err">{page.problem}</div>;
  if (!view) return <p className="muted">Loading the inputs…</p>;

  const todo = [...view.todo].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
  // the client's data, by the domain it lands in (plan 2026-11-03 §3.3); "To confirm" shows only what waits for you
  const toConfirm = review.data?.to_confirm ?? 0;
  const groupsFor = (t: Tab) => (review.data?.groups ?? []).filter((g) => g.tab === t && (!onlyToConfirm || g.state === "to_confirm"));
  const confirmHere = (t: Tab) => (
    <>
      <ConfirmGroups projectId={projectId} groups={groupsFor(t)} run={run} />
      {onlyToConfirm && groupsFor(t).length === 0 && <p className="muted" data-testid="nothing-to-confirm">Nothing from the client
        waits for you in this area.</p>}
    </>
  );
  const forTab = (t: Tab) => todo.filter((i) => (i.tab ?? "compound") === t);
  // a group to confirm is settled on its own card, above the panel: listed on the side, not twice in the panel
  const panelTodo = (t: Tab) => forTab(t).filter((i) => i.kind !== "confirm");
  const rows = (t: Tab) => (view.compound as Row[]).filter((r) => r.tab === t);
  const readiness = view.readiness?.content;
  const options = view.study_options as Options;
  const studies = view.studies;
  const used = studies.filter((s) => !s.excluded);
  const formulations = view.compound.filter((r) => /^form\.[^.]+\.type$/.test(r.id) && r.state === "kept").map((r) => r.id.split(".")[1]);
  const unplaced = (client.data?.files ?? []).filter((f) => !fileArea(f)).length;
  const bar = (t: "compound" | "formulations" | "studies") => !onlyToConfirm && (
    <FilesBar tab={t} projectId={projectId} client={client.data ?? undefined} run={run} />
  );
  const filesHere = (t: "compound" | "formulations") => !onlyToConfirm && (
    <FilesHere tab={t} projectId={projectId} client={client.data ?? undefined} act={clientAct} onRetag={retag} onSaved={clientSaved} />
  );

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
    setTab((t.tab ?? "compound") as Tab);
    window.setTimeout(() => document.getElementById(`todo-${t.kind}-${t.target}`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 50);
  }

  return (
    <PageShell
      eyebrow="Step 2 of 4"
      title="Inputs"
      lede={<>Every value not excluded flows in; where sources give several, one is kept by source and grade and the others
        stay listed for the review. Values are never averaged. <span className="muted">({view.selection_rule})</span></>}
      actions={(
        <>
          {view.published_models.map((m) => (
            <button key={m.id} type="button" className="btn" data-testid={`published-model-${m.id}`} title={m.name}
                    onClick={() => void take(m.id)}>
              Take the published OSP model&apos;s values
            </button>
          ))}
          <button type="button" className="btn" data-testid="ask-literature" disabled={running} onClick={() => void askLiterature()}>
            {running ? "The literature agent is searching…" : "Ask the literature for what is missing"}
          </button>
        </>
      )}
    >
      {notice && <Banner tone={notice.ok ? "ok" : "err"} testId="inputs-notice">{notice.text}</Banner>}
      {running && literature.data && <LiteratureProgress r={literature.data} />}
      <div className="inputs-layout">
      <Tabs label="Input areas" prefix="inputs" value={tab} onChange={setTab} vertical
            tabs={TABS.map(([id, label]) => ({ id, label, count: forTab(id).length, testId: `tab-${id}` }))}>
        <button type="button" className={`btn rail-confirm${toConfirm ? " waiting" : ""}`} aria-pressed={onlyToConfirm}
                data-testid="to-confirm" onClick={() => setOnlyToConfirm(!onlyToConfirm)}>
          <span>{onlyToConfirm ? "Showing what to confirm" : "To confirm"}</span>
          <span className="chip" data-testid="to-confirm-count">{toConfirm}</span>
        </button>
        <button type="button" className="btn rail-files" onClick={() => setDrawer(true)} data-testid="inputs-files"
                aria-haspopup="dialog">
          <span>The client&apos;s files</span>
          <span className="row" style={{ gap: 4 }}>
            {unplaced > 0 && <span className="chip medium" data-testid="files-unplaced" title="files no area shows yet: say what each is">
              {unplaced} to place</span>}
            <span className="chip neutral">{client.data?.files.length ?? 0}</span>
          </span>
        </button>
        <div className="rail-side">
          {todo.length > 0 ? (
            <SidePanel title={`Still missing to run (${todo.length})`} tone="warn" testId="still-missing">
              <ul className="missing-list">
                {todo.map((t, i) => (
                  <li key={`${t.kind}-${t.target}-${i}`}>
                    <button type="button" className="link-btn" onClick={() => open(t)} data-testid={`missing-${t.kind}-${t.target}`}>
                      {TITLE[t.kind]}{t.kind === "confirm" ? ` · ${(review.data?.groups ?? []).find((g) => g.id === t.target)?.title ?? t.target}`
                        : t.kind !== "datasets" && t.kind !== "check" ? ` · ${LABEL[t.target] ?? t.target}` : ""}
                    </button>
                    <span className="muted"> · {TAB_LABEL[(t.tab ?? "compound") as Tab]}</span>
                  </li>
                ))}
              </ul>
            </SidePanel>
          ) : readiness?.ready ? (
            <SidePanel title="Inputs are ready" tone="ok" testId="inputs-ready">
              <p style={{ margin: "0 0 8px" }}>Everything S0 needs is here, and every planned simulation builds.</p>
              <Link className="btn primary" href={STEP_ROUTES.review(projectId)}>Go to Review &amp; sign</Link>
            </SidePanel>
          ) : (
            <SidePanel title="Assembling" testId="assembling"><p style={{ margin: 0 }}>The inputs are being put together.</p></SidePanel>
          )}
          {readiness && (
            <SidePanel title="Readiness">
              <ul className="checks" data-testid="readiness">
                {readiness.checks.map((c) => (
                  <li key={c.check} data-testid={`check-${c.check}`}>
                    <span className={`chip ${c.ok ? "low" : "high"}`}>{c.ok ? "ok" : "open"}</span> {c.check}
                  </li>
                ))}
              </ul>
              <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>PK-Sim dry run: {readiness.engine_dry_run}</p>
            </SidePanel>
          )}
          <SidePanel title="Where values come from">
            <p style={{ margin: 0, fontSize: 13 }}>The client&apos;s files and figures, the literature agent, PubChem and the
              published OSP model of the drug. Where several give a value, the client&apos;s comes first, then the literature by grade.</p>
          </SidePanel>
        </div>
      </Tabs>
      <div className="inputs-area">

      {tab === "compound" && (
        <TabPanel prefix="inputs" id="compound">{bar("compound")}{confirmHere("compound")}
          {!onlyToConfirm && <><InputRows rows={rows("compound")} todo={panelTodo("compound")} projectId={projectId} run={run} grouped
                   empty="The compound's values appear here as the client's files, the literature and PubChem fill them." />
          <AccessRequests projectId={projectId} run={run} /></>}{filesHere("compound")}</TabPanel>
      )}

      {tab === "formulations" && (
        <TabPanel prefix="inputs" id="formulations">{bar("formulations")}{confirmHere("formulations")}
          {!onlyToConfirm && <>
          <BriefList projectId={projectId} group="products" testId="inputs-products"
                     fields={["name", "role", "dosage_form", "strength", "release", "attributes"]}
                     title="The products the proposal names"
                     lede="Each product is built as its own formulation; the data plan asks for its dissolution and, for a test and its reference, the study that compares them." />
          <InputRows rows={rows("formulations")} todo={panelTodo("formulations")} projectId={projectId} run={run}
                     empty="No formulation yet: a solution needs none; a tablet's release comes from its dissolution profile or the literature." />
          {used.some((s) => SOLID.includes(String(s.facts.formulation))) && (
            <section className="card">
              <h3 style={{ marginTop: 0 }}>The formulation of each solid study</h3>
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
          </>}{filesHere("formulations")}
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
            <h3 style={{ marginTop: 0 }}>Solver settings</h3>
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
        <TabPanel prefix="inputs" id="studies">{bar("studies")}{confirmHere("studies")}{!onlyToConfirm && <StudiesTab studies={studies} todo={panelTodo("studies")} projectId={projectId} run={run} options={options}
                    onIndividuals={() => setTab("individuals")} client={client.data ?? undefined} onRetag={retag}
                    onSaved={(m) => setNotice({ ok: true, text: m })} />}</TabPanel>
      )}
      </div>
      </div>
      {drawer && <FilesDrawer projectId={projectId} files={client.data?.files ?? []} onClose={() => setDrawer(false)} onRetag={retag}
                              onOpen={(area, f) => {
                                setDrawer(false);
                                setOnlyToConfirm(false);
                                setTab(area);
                                window.setTimeout(() => document.getElementById(`client-file-${f.id}`)?.scrollIntoView({ block: "start", behavior: "smooth" }), 80);
                              }} />}
    </PageShell>
  );
}
