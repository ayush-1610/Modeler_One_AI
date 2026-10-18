import Link from "next/link";

import { getPhases, PHASE_ROUTES, type PhaseStatus } from "@/lib/pipeline";

const STATUS_LABEL: Record<PhaseStatus, string> = {
  NOT_STARTED: "not started",
  IN_REVIEW: "in review",
  APPROVED: "approved",
  STALE: "stale",
};

// P6 is the campaign itself: it is running (or waiting for a decision) until it completes
const RUN_LABEL: Record<PhaseStatus, string> = { ...STATUS_LABEL, IN_REVIEW: "running", APPROVED: "completed" };

/** The project's phases P0–P6 with their status (plan §15.4). A stale phase links to the reason it is stale. */
export async function PhaseRail({ projectId, current }: { projectId: string; current?: string }) {
  const live = await getPhases(projectId);
  if (!live.data) return null; // the rail is navigation; the page itself reports a read problem
  const staleCount = live.data.stale.length;
  return (
    <nav className="phase-rail" aria-label="Project phases" data-testid="phase-rail">
      {live.data.phases.map((p) => (
        <Link key={p.phase} href={PHASE_ROUTES[p.phase](projectId)}
              className={`phase ${p.status.toLowerCase()}${current === p.phase ? " current" : ""}`}
              title={`${p.phase} ${p.label}: ${(p.phase === "P6" ? RUN_LABEL : STATUS_LABEL)[p.status]}`}>
          <span className="ph-id">{p.phase}</span>
          <span className="ph-name">{p.label}</span>
          <span className="ph-status">{p.phase === "P6" ? RUN_LABEL[p.status] : STATUS_LABEL[p.status]}</span>
        </Link>
      ))}
      <Link href={`/projects/${projectId}/history`} className={`phase history${staleCount ? " has-stale" : ""}`}>
        <span className="ph-id">⟲</span>
        <span className="ph-name">History</span>
        <span className="ph-status">{staleCount ? `${staleCount} stale` : "audit"}</span>
      </Link>
    </nav>
  );
}
