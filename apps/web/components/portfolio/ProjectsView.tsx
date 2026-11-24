"use client";

// Projects (P-03): the table by default (archive and restore, owners, steps); the cards as an option, remembered in this
// browser only.

import { useEffect, useState } from "react";

import { ProjectCards } from "@/components/portfolio/ProjectCards";
import { ProjectsTable } from "@/components/projects/ProjectsTable";
import type { Campaign, Project } from "@/lib/types";

const VIEW_KEY = "modeler-projects-view";

export function ProjectsView({ projects, campaigns, me }: { projects: Project[]; campaigns: Campaign[]; me: string | null }) {
  const [view, setView] = useState<"table" | "cards">("table");
  useEffect(() => {
    try { if (localStorage.getItem(VIEW_KEY) === "cards") setView("cards"); } catch { /* the table */ }
  }, []);
  const choose = (v: "table" | "cards") => {
    setView(v);
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* this page only */ }
  };
  return (
    <>
      <div className="view-switch mb-16" role="group" aria-label="View">
        <button type="button" aria-pressed={view === "table"} onClick={() => choose("table")} data-testid="dash-view-list">Table</button>
        <button type="button" aria-pressed={view === "cards"} onClick={() => choose("cards")} data-testid="dash-view-cards">Cards</button>
      </div>
      {view === "table" ? <ProjectsTable projects={projects} me={me} /> : <ProjectCards projects={projects} campaigns={campaigns} />}
    </>
  );
}
