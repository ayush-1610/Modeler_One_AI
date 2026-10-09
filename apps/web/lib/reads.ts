// Typed server-side fetchers for the read APIs. Each returns the live data or the problem that prevented it
// (`Live<T>`); pages render the problem instead of sample data.

import { serverGet, serverRead, type Live, type Schema } from "@/lib/api";
import type { Campaign, CampaignDetail, Compound, Escalation, Project, ProjectDetail, Proposal } from "@/lib/types";

function pick<A, B>(live: Live<A>, f: (a: A) => B): Live<B> {
  return { ...live, data: live.data === null ? null : f(live.data) };
}

export async function getProjects(): Promise<Live<Project[]>> {
  return pick(await serverGet("/api/v1/projects", {}), (d) => d.projects);
}

export async function getProject(projectId: string): Promise<Live<ProjectDetail>> {
  return serverGet("/api/v1/projects/{project_id}", { project_id: projectId });
}

export async function getCompoundCpf(projectId: string, compound: string): Promise<Live<Compound>> {
  const live = await serverGet("/api/v1/projects/{project_id}/compounds/{compound}/cpf", { project_id: projectId, compound });
  return pick(live, (view) => ({
    name: view.compound,
    project: projectId,
    version: view.version,
    completeness: view.completeness,
    parameters: view.parameters,
  }));
}

// An observed study as stored for the project (D-15: a blinded external study comes without its profile).
export type StudyRow = Schema<"StudyRow">;

/** The observed clinical studies uploaded for a project (what a campaign fits and validates against). */
export async function getStudies(projectId: string): Promise<Live<StudyRow[]>> {
  return pick(await serverGet("/api/v1/projects/{project_id}/studies", { project_id: projectId }), (d) => d.studies);
}

/** Campaigns for the tenant, or just one project's when `project` is given. */
export async function getCampaigns(project?: string): Promise<Live<Campaign[]>> {
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  return pick(await serverRead<{ campaigns: Campaign[] }>(`/api/v1/campaigns${query}`), (d) => d.campaigns);
}

export async function getCampaign(campaignId: string): Promise<Live<CampaignDetail>> {
  return serverRead<CampaignDetail>(`/api/v1/campaigns/${campaignId}`);
}

export async function getEscalations(): Promise<Live<Escalation[]>> {
  return pick(await serverRead<{ escalations: Escalation[] }>("/api/v1/escalations"), (d) => d.escalations);
}

export async function getProposals(): Promise<Live<Proposal[]>> {
  return pick(await serverGet("/api/v1/proposals", {}), (d) => d.proposals);
}
