"use client";

// The Projects page's cards view (kept as an option, P-03): each project's four steps, what waits and its next action,
// with a search and the four filters. Every number is read from the API; nothing here is a simulation.

import Link from "next/link";
import { useState } from "react";

import { RiskBadge } from "@/components/kit/Badge";
import { nextHref, standing, STANDING_WORD, type Standing } from "@/lib/portfolio";
import type { Campaign, Project } from "@/lib/types";

const FILTERS = ["All", "Needs you", "Running", "Done", "High risk"] as const;
type Filter = (typeof FILTERS)[number];

function matches(p: Project, state: Standing, f: Filter): boolean {
  if (f === "All") return true;
  if (f === "High risk") return p.risk === "high";
  return STANDING_WORD[state] === f;
}

export function ProjectCards({ projects, campaigns }: { projects: Project[]; campaigns: Campaign[] }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("All");
  const active = projects.filter((p) => !p.archived);
  const q = query.trim().toLowerCase();
  const shown = active.filter((p) => matches(p, standing(p.steps).state, filter) && (!q || `${p.name} ${p.compounds.join(" ")}`.toLowerCase().includes(q)));
  return (
    <section className="tbl" aria-label="Projects as cards">
      <div className="tbl-tools first">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search projects or compounds"
               aria-label="Search projects or compounds" data-testid="dash-search" />
        <div className="view-switch" role="group" aria-label="Show">
          {FILTERS.map((f) => <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>{f}</button>)}
        </div>
      </div>
      {active.length === 0 ? <div className="tbl-empty">No projects yet. Create one from a client&apos;s proposal.</div>
        : shown.length === 0 ? (
          <div className="tbl-empty">No projects match. <button type="button" className="link-btn" onClick={() => { setFilter("All"); setQuery(""); }}>Clear the filters</button></div>
        ) : (
          <ul className="pcards">
            {shown.map((p) => <ProjectCard key={p.id} p={p} running={campaigns.filter((c) => c.project === p.id && c.status === "RUNNING").length} />)}
          </ul>
        )}
    </section>
  );
}

function ProjectCard({ p, running }: { p: Project; running: number }) {
  const st = standing(p.steps);
  const steps = p.steps ?? [];
  const done = steps.filter((s) => s.state === "done").length;
  return (
    <li>
      <Link href={nextHref(p)} className={`pcard ${st.state}`} data-testid={`project-card-${p.id}`}>
        <div className="pcard-head">
          <span className="pcard-mono" aria-hidden>{(p.compounds[0] ?? p.name).charAt(0).toUpperCase()}</span>
          <span className="pcard-title">
            <strong>{p.name}</strong>
            <span>{p.compounds.join(", ") || "no compound yet"} · {p.openQuestions} open question{p.openQuestions === 1 ? "" : "s"}</span>
          </span>
          <span className="pcard-count" aria-label={`${done} of 4 steps done`}>{done}/4</span>
        </div>
        {steps.length > 0 && (
          <ol className="pcard-steps" aria-label="Steps">
            {steps.map((s) => (
              <li key={s.step} className={`${s.state}${s.step === st.focus ? " focus" : ""}`} title={`${s.label}: ${s.state.replace("_", " ")}`}>
                <span className="bar" aria-hidden />
                <span className="lbl">{s.label}</span>
              </li>
            ))}
          </ol>
        )}
        {st.reason && <p className="pcard-reason">{st.reason}</p>}
        <div className="pcard-foot">
          <span className="pcard-state">{STANDING_WORD[st.state]}{running > 0 ? ` · ${running} campaign${running === 1 ? "" : "s"}` : ""}</span>
          <RiskBadge rating={p.risk} />
          <span className="pcard-next">{st.next} →</span>
        </div>
      </Link>
    </li>
  );
}
