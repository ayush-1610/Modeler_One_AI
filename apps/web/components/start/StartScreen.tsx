"use client";

// Step 1 · Start (docs/plans/2026-10-19-p0-p5-redesign.md §3.1): one screen, three blocks. The documents and the agent
// fill what they say; the person fills what they do not and corrects what is wrong. Nothing here is approved (D-27):
// the one review is the MAP signature in Review & sign. What Start still needs is the API's, beside the page.

import Link from "next/link";
import { useMemo, useState } from "react";

import { DocumentViewer } from "@/components/brief/DocumentViewer";
import { EmptyState, InlineIssue, PageShell, SidePanel } from "@/components/kit";
import { ChecklistBlock } from "@/components/start/Checklist";
import {
  ChoiceField, FieldRow, MultiField, SelectField, type OpenQuote, type Run, type Save,
} from "@/components/start/Fields";
import { DrugAndFiles } from "@/components/start/Files";
import { ProposalNotes, Questions } from "@/components/start/Notes";
import { RiskBlock } from "@/components/start/Risk";
import { send } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";
import type { StartField, StartPage } from "@/lib/start";

type Focus = { sha256: string; page: number; quote: string | null } | null;

/** The component a field is asked with: a click for a choice, ticks for several, an editor for the rest. */
function Ask({ field, onSave, onOpen, busy }: { field: StartField; onSave: Save; onOpen: OpenQuote; busy: boolean }) {
  if (field.kind === "multi") return <MultiField field={field} onSave={onSave} onOpen={onOpen} busy={busy} />;
  if (field.kind === "enum" || field.kind === "bool") {
    return <ChoiceField field={field} onSave={onSave} onOpen={onOpen} busy={busy} compact={field.options.length > 4} />;
  }
  return <FieldRow field={field} onSave={onSave} onOpen={onOpen} busy={busy} />;
}

function Scenarios({ projectId, view, onSave, run, busy }: {
  projectId: string; view: StartPage; onSave: Save; run: Run; busy: boolean;
}) {
  const [adding, setAdding] = useState(view.scenarios.length === 0);
  const [problem, setProblem] = useState<string | null>(null);
  async function remove(index: number) {
    const { problem: failed } = await run(() => send("post", "/api/v1/projects/{project_id}/brief/items:remove",
      { project_id: projectId }, { group: "scenarios", index, reason: `scenario ${index + 1} removed at Start` }));
    setProblem(failed);
  }
  return (
    <div className="scenarios" data-testid="scenarios">
      {view.scenarios.map((s) => (
        <div key={s.index} className="scenario" data-testid={`scenario-${s.index}`}>
          <span className="scenario-n">{s.index + 1}</span>
          <SelectField field={s.route} onSave={onSave} busy={busy} label="Route" />
          <SelectField field={s.food_state} onSave={onSave} busy={busy} label="Food state" />
          <span className="muted scenario-notes">{s.notes}</span>
          <button type="button" className="link-btn" disabled={busy} onClick={() => remove(s.index)}>Remove</button>
        </div>
      ))}
      {adding ? (
        <div className="scenario adding" data-testid="scenario-new">
          <span className="scenario-n">{view.new_scenario.index + 1}</span>
          <SelectField field={view.new_scenario.route} label="Route" busy={busy} onSave={async (changes, reason) => {
            const failed = await onSave(changes, reason);
            if (!failed) setAdding(false);
            return failed;
          }} />
          <span className="muted">the route first; the food state and the rest follow</span>
        </div>
      ) : (
        <button type="button" className="link-btn" disabled={busy} data-testid="add-scenario" onClick={() => setAdding(true)}>
          Add a scenario</button>
      )}
      {view.scenario_warnings.map((w) => <InlineIssue key={w}>{w}</InlineIssue>)}
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </div>
  );
}

export function StartScreen({ projectId }: { projectId: string }) {
  const page = useResource("/api/v1/projects/{project_id}/start", { project_id: projectId },
    { poll: (d) => d.extraction_running });
  const { run, busy } = useMutation();
  const [focus, setFocus] = useState<Focus>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const view = page.data;
  const labels = useMemo(() => {
    const out = new Map<string, string>();
    if (view) {
      [...view.identity, ...view.question, ...view.risk_fields, ...view.gate_fields, ...view.scope, ...view.notes,
       ...view.note_groups.flatMap((g) => g.items.flat())].forEach((f) => out.set(f.path, f.label));
    }
    return out;
  }, [view]);

  if (page.problem) return <div className="banner err">{page.problem}</div>;
  if (!view) return <p className="muted">Loading Start…</p>;

  const save: Save = async (changes, reason) =>
    (await run(() => send("put", "/api/v1/projects/{project_id}/brief", { project_id: projectId }, { changes, reason }))).problem;
  const open: OpenQuote = (c) => setFocus({ sha256: c.doc_sha256, page: c.page, quote: c.quote });
  const done = view.state === "done";
  const gate = (path: string) => view.gate_fields.find((f) => f.path === path)!;
  const refused = view.gates.filter((g) => g.state === "not_supported");
  const lastRun = view.runs[0];

  async function extract() {
    const { data, problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief:extract", { project_id: projectId }, {}));
    setNotice(problem ?? (data?.agents ? "The agent is reading the documents; the page fills in as it finishes."
      : (data?.problem ?? "The identity was looked up; fill the rest by hand.")));
  }

  return (
    <PageShell
      wide
      eyebrow="Step 1 · Start"
      title={<span data-testid="start-title">{view.drug_name}</span>}
      lede={<>The documents fill what they state; you fill what they do not and correct what is wrong. Nothing here is
        approved: you review everything once, when you sign the plan in Review &amp; sign.</>}
      actions={
        <>
          <span className={`chip ${view.agents.enabled ? "brand" : "neutral"}`} title={view.agents.problem ?? ""}>
            {view.agents.enabled ? `agent: ${view.agents.provider} · ${view.agents.model}` : "agents off: by hand"}
          </span>
          <button type="button" className="btn" disabled={busy || view.extraction_running} onClick={extract}>
            {view.extraction_running ? "Reading the documents…" : "Read the documents again"}
          </button>
        </>
      }
      side={
        <>
          <SidePanel title={done ? "Start is complete" : "Still needed for Start"} tone={done ? "ok" : "warn"} testId="start-missing">
            {done ? (
              <p>Next: the model&apos;s inputs. <Link href={`/projects/${projectId}/inputs`}>Go to Inputs →</Link></p>
            ) : (
              <ul className="missing-list">{view.missing.map((m) => <li key={m}>{m}</li>)}</ul>
            )}
            {lastRun && (
              <p className="muted run-line">Last agent run: {lastRun.status.toLowerCase()}
                {typeof lastRun.summary.accepted === "number" &&
                  ` · ${lastRun.summary.accepted} fields filled, ${lastRun.summary.rejected} refused by the citation check`}</p>
            )}
          </SidePanel>
          {view.documents.length > 0
            ? <DocumentViewer projectId={projectId} documents={view.documents} focus={focus} />
            : <EmptyState title="No documents">The proposal and its annexes appear here, with each quote marked.</EmptyState>}
        </>
      }
    >
      {notice && <InlineIssue severity="note">{notice}</InlineIssue>}

      <section className="card start-block" aria-labelledby="start-files">
        <h2 id="start-files"><span className="block-n">1</span> The drug and the files</h2>
        <DrugAndFiles projectId={projectId} view={view} onSave={save} onOpen={open} run={run} busy={busy}
                      onShow={(sha256) => setFocus({ sha256, page: 1, quote: null })} />
      </section>

      <section className="card start-block" aria-labelledby="start-brief">
        <h2 id="start-brief"><span className="block-n">2</span> The short brief</h2>
        <div className="brief-part">
          <h3>The question</h3>
          {view.question.map((f) => <Ask key={f.path} field={f} onSave={save} onOpen={open} busy={busy} />)}
        </div>
        <div className="brief-part">
          <h3>Model risk (ICH M15)</h3>
          <RiskBlock view={view} onSave={save} onOpen={open} busy={busy} />
        </div>
        <div className="brief-part" data-testid="scope-gates">
          <h3>What the model is</h3>
          <p className="muted part-lede">The builder makes full (whole-body) PBPK models of systemic small molecules, given IV or
            orally, with dissolved, particle and Weibull formulations. Anything else is refused here, before any data work.</p>
          <ChoiceField field={gate("drug.modality")} onSave={save} onOpen={open} busy={busy} />
          <ChoiceField field={gate("scope.model_structure")} onSave={save} onOpen={open} busy={busy} />
          <ChoiceField field={gate("scope.site_of_action")} onSave={save} onOpen={open} busy={busy} />
          <MultiField field={gate("scope.formulation_types")} onSave={save} onOpen={open} busy={busy} />
          {refused.map((g) => <InlineIssue key={g.id} severity="error" testId={`refused-${g.id}`}>{g.message}</InlineIssue>)}
        </div>
        <div className="brief-part">
          <h3>Scenarios: route and food state</h3>
          <Scenarios projectId={projectId} view={view} onSave={save} run={run} busy={busy} />
        </div>
        <div className="brief-part">
          <h3>Scope</h3>
          {view.scope.map((f) => <Ask key={f.path} field={f} onSave={save} onOpen={open} busy={busy} />)}
        </div>
        <Questions projectId={projectId} view={view} label={(p) => labels.get(p) ?? p} run={run} busy={busy} />
        <ProposalNotes projectId={projectId} view={view} onSave={save} onOpen={open} run={run} busy={busy} />
      </section>

      <section className="card start-block" aria-labelledby="start-checklist">
        <h2 id="start-checklist"><span className="block-n">3</span> The data checklist</h2>
        <p className="muted part-lede">What the model needs and who provides it, derived from the brief as it changes. The
          client&apos;s items are ticked off as their files arrive.</p>
        <ChecklistBlock projectId={projectId} view={view} run={run} busy={busy} />
      </section>
    </PageShell>
  );
}
