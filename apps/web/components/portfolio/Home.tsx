"use client";

// Home (P-01, the console redesign's slice 2): what waits on this person, what is running, and where each program
// stands, on one screen. Counters open the list they count; Your work and the projects are links. Nothing is decided
// here (the owner's decision G1-3). Every number is read from the API; nothing here is a simulation.

import Link from "next/link";
import type { ReactNode } from "react";

import { Hero } from "@/components/kit";
import { Table } from "@/components/kit/Table";
import { ProjectsTable } from "@/components/projects/ProjectsTable";
import { RiskChip, StatusChip } from "@/components/ui";
import { standing, type WorkItem } from "@/lib/portfolio";
import type { Campaign, Project } from "@/lib/types";
import { WorkKindChip } from "@/components/portfolio/Work";

export function Home({ projects, campaigns, work, me, notice }: {
  projects: Project[];
  /** null: the campaigns could not be read (the counter says so, never 0). */
  campaigns: Campaign[] | null;
  work: WorkItem[];
  me: string | null;
  notice?: ReactNode;
}) {
  const active = projects.filter((p) => !p.archived);
  const compounds = new Set(active.flatMap((p) => p.compounds)).size;
  const needs = active.filter((p) => standing(p.steps).state === "needs_you").length;
  const questions = active.reduce((n, p) => n + p.openQuestions, 0);
  const running = campaigns ? campaigns.filter((c) => c.status === "RUNNING").length : null;
  const risks = (["high", "medium", "low"] as const).map((r) => ({ r, n: active.filter((p) => p.risk === r).length }));
  const unrated = active.length - risks.reduce((n, x) => n + x.n, 0);
  const names = new Map(projects.map((p) => [p.id, p.name]));

  const counters = [
    { id: "kpi-projects", label: "Projects", value: active.length, sub: `across ${compounds} compound${compounds === 1 ? "" : "s"}`, href: "/projects", tone: "" },
    { id: "kpi-running-now", label: "Running now", value: running, sub: running === null ? "could not be read" : "campaigns in progress", href: "/campaigns", tone: "accent" },
    { id: "kpi-needs-you", label: "Waiting on a person", value: needs, sub: "projects with a step that needs someone", href: "/work", tone: "warn" },
    { id: "kpi-open-questions", label: "Open questions", value: questions, sub: "of interest, across programs", href: "/projects", tone: "" },
  ];

  return (
    <>
      <Hero title="Home" testId="dash-hero" lede="What waits on you, what is running, and where each program stands."
            actions={<Link className="btn primary" href="/projects/start" data-testid="dash-new-project">Create project</Link>} />
      {notice}
      <nav className="counters" aria-label="At a glance">
        {counters.map((c) => (
          <Link key={c.id} href={c.href} className={`counter ${c.tone}`} data-testid={c.id}>
            <span className="counter-label">{c.label}</span>
            <span className="counter-value" title={c.value === null ? "could not be read" : undefined}>{c.value === null ? "—" : c.value}</span>
            <span className="counter-sub">{c.sub}</span>
          </Link>
        ))}
      </nav>

      <div className="home-cols">
        <div>
          <Table title="Your work" count={work.length} testId="dash-attention" rows={work.slice(0, 5)} rowKey={(w) => w.key}
                 actions={<Link href="/work">View all</Link>}
                 columns={[
                   { key: "what", label: "Item", render: (w) => <Link href={w.href}>{w.what}</Link> },
                   { key: "project", label: "Project", render: (w) => w.projectName ?? <span className="muted">Campaign not recorded yet</span> },
                   { key: "kind", label: "Status", render: (w) => <WorkKindChip kind={w.kind} /> },
                 ]}
                 empty="Nothing waits on you." />
          <ProjectsTable projects={active} me={me} limit={8} testId="home-projects"
                         actions={<Link href="/projects" data-testid="home-all-projects">All projects</Link>} />
        </div>
        <div>
          <section className="panel" aria-labelledby="risk-title" data-testid="dash-risk">
            <div className="panel-head"><h2 id="risk-title">Risk across programs</h2></div>
            <div className="panel-body">
              {active.length === 0 ? <p className="muted m-0">No programs yet.</p> : (
                <ul className="list-plain">
                  {risks.map((x) => <li key={x.r}><RiskChip rating={x.r} /> {x.n}</li>)}
                  {unrated > 0 && <li><RiskChip rating={null} /> {unrated}</li>}
                </ul>
              )}
            </div>
          </section>
          <section className="panel" aria-labelledby="recent-title" data-testid="home-campaigns">
            <div className="panel-head"><h2 id="recent-title">Recent campaigns</h2><span className="grow" /><Link href="/campaigns">All campaigns</Link></div>
            <div className="panel-body">
              {campaigns === null ? <p className="muted m-0">The campaigns could not be read.</p>
                : campaigns.length === 0 ? <p className="muted m-0">No campaign has run yet.</p> : (
                  <ul className="list-plain">
                    {campaigns.slice(-5).reverse().map((c) => (
                      <li key={c.id}>
                        <Link href={`/campaigns/${encodeURIComponent(c.id)}`}><code>{c.id}</code></Link> <StatusChip status={c.status} />
                        <span className="muted fs-12">{names.get(c.project) ?? c.project} · {c.currentStage}</span>
                      </li>
                    ))}
                  </ul>
                )}
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
