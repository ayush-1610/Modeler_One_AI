"use client";

// The first screen (plan 2026-11-06-app-design-merge §3 A): what waits on a person, what is running and where each
// program stands, before the list of projects. Every number on it is read from the API; nothing here is a simulation.

import Link from "next/link";
import { useEffect, useState } from "react";

import { ProjectsTable } from "@/components/projects/ProjectsTable";
import { RiskChip } from "@/components/ui";
import type { StepRow } from "@/lib/pipeline";
import type { Project } from "@/lib/types";

type State = "needs_you" | "running" | "done" | "not_started" | "unknown";

export type DashboardProject = {
  id: string; name: string; compounds: string[]; openQuestions: number; risk: string; archived: boolean;
  steps: Pick<StepRow, "step" | "label" | "state">[];
  state: State; focus: StepRow["step"] | null; next: string; reason: string | null; href: string; running: number;
};
export type Attention = { key: string; tone: "warn" | "fail"; href: string; title: string; detail: string };

const STATE_LABEL: Record<State, string> = {
  needs_you: "Needs you", running: "Running", done: "Done", not_started: "Not started", unknown: "Steps not read",
};
const FILTERS = ["All", "Needs you", "Running", "Done", "High risk"] as const;
type Filter = (typeof FILTERS)[number];
const VIEW_KEY = "modeler-dashboard-view";

function matches(p: DashboardProject, f: Filter): boolean {
  if (f === "All") return true;
  if (f === "High risk") return p.risk === "high";
  return STATE_LABEL[p.state] === f;
}

export function Dashboard({ projects, attention, runningCampaigns, tableProjects }: {
  projects: DashboardProject[]; attention: Attention[]; runningCampaigns: number; tableProjects: Project[];
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("All");
  const [view, setView] = useState<"cards" | "list">("cards");
  useEffect(() => {
    try { if (localStorage.getItem(VIEW_KEY) === "list") setView("list"); } catch { /* cards */ }
  }, []);
  const choose = (v: "cards" | "list") => {
    setView(v);
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* this page only */ }
  };

  const active = projects.filter((p) => !p.archived);
  const compounds = new Set(active.flatMap((p) => p.compounds)).size;
  const needs = active.filter((p) => p.state === "needs_you").length;
  const questions = active.reduce((n, p) => n + p.openQuestions, 0);
  const q = query.trim().toLowerCase();
  const shown = active.filter((p) => matches(p, filter) && (!q || `${p.name} ${p.compounds.join(" ")}`.toLowerCase().includes(q)));
  const risks = (["high", "medium", "low"] as const).map((r) => ({ r, n: active.filter((p) => p.risk === r).length })).filter((x) => x.n);
  const unrated = active.length - risks.reduce((n, x) => n + x.n, 0);

  const kpis = [
    { label: "Projects", value: active.length, sub: `across ${compounds} compound${compounds === 1 ? "" : "s"}`, go: () => { setFilter("All"); setQuery(""); }, tone: "" },
    { label: "Running now", value: runningCampaigns, sub: "campaigns in progress", go: () => setFilter("Running"), tone: "sim" },
    { label: "Needs you", value: needs, sub: "projects waiting on a person", go: () => setFilter("Needs you"), tone: "warn" },
    { label: "Open questions", value: questions, sub: "of interest, across programs", go: () => setFilter("All"), tone: "" },
  ];

  return (
    <div className="dash">
      <section className="hero" aria-labelledby="dash-title">
        <div className="hero-copy">
          <span className="eyebrow">Modeler One</span>
          <h1 id="dash-title">Dashboard</h1>
          <p className="lede">Every PBPK program on the Open Systems Pharmacology Suite: where each stands, what waits on you,
            and what is running.</p>
        </div>
        <div className="hero-actions">
          <Link className="btn primary" href="/projects/start" data-testid="dash-new-project">+ New project</Link>
        </div>
      </section>

      <div className="kpis" role="group" aria-label="At a glance">
        {kpis.map((k) => (
          <button key={k.label} type="button" className={`kpi ${k.tone}`} onClick={k.go} data-testid={`kpi-${k.label.toLowerCase().replace(/ /g, "-")}`}>
            <span className="kpi-label">{k.label}</span>
            <span className="kpi-value">{k.value}</span>
            <span className="kpi-sub">{k.sub}</span>
          </button>
        ))}
      </div>

      <div className="dash-body">
        <section className="dash-projects" aria-label="Projects">
          <div className="dash-tools">
            {view === "cards" && <>
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search projects or compounds"
                   aria-label="Search projects or compounds" data-testid="dash-search" />
            <div className="dash-seg" role="group" aria-label="Show">
              {FILTERS.map((f) => (
                <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>{f}</button>
              ))}
            </div>
            </>}
            <div className="dash-seg view" role="group" aria-label="View">
              <button type="button" aria-pressed={view === "cards"} onClick={() => choose("cards")} data-testid="dash-view-cards">Cards</button>
              <button type="button" aria-pressed={view === "list"} onClick={() => choose("list")} data-testid="dash-view-list">List</button>
            </div>
          </div>

          {view === "list" ? (
            // the record view: archive and restore with a reason, and each project's history (page review 1)
            <div className="card"><ProjectsTable projects={tableProjects} /></div>
          ) : active.length === 0 ? (
            <p className="muted">No projects yet. Use <strong>+ New project</strong> to start one from its proposal and the client&apos;s files.</p>
          ) : shown.length === 0 ? (
            <p className="muted">No projects match. <button type="button" className="link-btn" onClick={() => { setFilter("All"); setQuery(""); }}>Clear the filters</button></p>
          ) : (
            <ul className="pcards">
              {shown.map((p) => <ProjectCard key={p.id} p={p} />)}
            </ul>
          )}
        </section>

        <aside className="dash-side">
          <section className="dash-panel" aria-labelledby="attention-title" data-testid="dash-attention">
            <h2 id="attention-title">Needs your attention</h2>
            <p className="muted">Signatures, decisions and steps waiting on a person.</p>
            {attention.length === 0 ? (
              <p className="dash-clear">Nothing waits on you.</p>
            ) : (
              <ul className="attention">
                {attention.slice(0, 8).map((a) => (
                  <li key={a.key}>
                    <Link href={a.href} className={a.tone}>
                      <span className="attention-dot" aria-hidden />
                      <span className="attention-text">{a.title}<span>{a.detail}</span></span>
                      <span aria-hidden>›</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            {attention.length > 8 && <p className="muted" style={{ margin: "8px 0 0" }}>and {attention.length - 8} more</p>}
          </section>

          <section className="dash-panel" aria-labelledby="risk-title" data-testid="dash-risk">
            <h2 id="risk-title">Risk across programs</h2>
            {active.length === 0 ? <p className="muted">No programs yet.</p> : (
              <>
                <div className="riskbar" aria-hidden>
                  {risks.map((x) => <span key={x.r} className={x.r} style={{ flexGrow: x.n }} />)}
                  {unrated > 0 && <span className="unrated" style={{ flexGrow: unrated }} />}
                </div>
                <ul className="risk-legend">
                  {risks.map((x) => <li key={x.r}><RiskChip rating={x.r} /> {x.n}</li>)}
                  {unrated > 0 && <li><RiskChip rating={null} /> {unrated}</li>}
                </ul>
              </>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}

function ProjectCard({ p }: { p: DashboardProject }) {
  const done = p.steps.filter((s) => s.state === "done").length;
  return (
    <li>
      <Link href={p.href} className={`pcard ${p.state}`} data-testid={`project-card-${p.id}`}>
        <div className="pcard-head">
          <span className="pcard-mono" aria-hidden>{(p.compounds[0] ?? p.name).charAt(0).toUpperCase()}</span>
          <span className="pcard-title">
            <strong>{p.name}</strong>
            <span>{p.compounds.join(", ") || "no compound yet"} · {p.openQuestions} open question{p.openQuestions === 1 ? "" : "s"}</span>
          </span>
          <span className="pcard-count" aria-label={`${done} of 4 steps done`}>{done}/4</span>
        </div>
        {p.steps.length > 0 && (
          <ol className="pcard-steps" aria-label="Steps">
            {p.steps.map((s) => (
              <li key={s.step} className={`${s.state}${s.step === p.focus ? " focus" : ""}`} title={`${s.label}: ${s.state.replace("_", " ")}`}>
                <span className="bar" aria-hidden />
                <span className="lbl">{s.label}</span>
              </li>
            ))}
          </ol>
        )}
        {p.reason && <p className="pcard-reason">{p.reason}</p>}
        <div className="pcard-foot">
          <span className="pcard-state">{STATE_LABEL[p.state]}{p.running > 0 ? ` · ${p.running} campaign${p.running === 1 ? "" : "s"}` : ""}</span>
          <RiskChip rating={p.risk} />
          <span className="pcard-next">{p.next} →</span>
        </div>
      </Link>
    </li>
  );
}
