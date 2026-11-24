"use client";

// The count of Your work for the shell (top bar and side navigation), read in the browser from the same reads Your work
// uses (the project list with its steps and owners, R-N03; the campaigns; the open escalations; the person).

import { useResource } from "@/lib/hooks";
import { workItems } from "@/lib/portfolio";
import type { Campaign, Escalation, Project } from "@/lib/types";

/** How many items wait on this person; null until the reads answer (the shell then shows no number). */
export function useWorkCount(): number | null {
  const projects = useResource("/api/v1/projects", {}, { query: { with: "steps,owner" }, select: (d) => d.projects as Project[] });
  const escalations = useResource("/api/v1/escalations", {}, { poll: () => true, interval: 30_000, select: (d) => d.escalations as Escalation[] });
  const campaigns = useResource("/api/v1/campaigns", {}, { select: (d) => d.campaigns as Campaign[] });
  const me = useResource("/api/v1/me", {}, { select: (d) => ({ user_id: d.user_id, roles: d.roles }) });
  if (projects.data === null || escalations.data === null) return null;
  return workItems(projects.data, escalations.data, campaigns.data ?? [], me.data).length;
}
