// Typed server-side fetchers for the read APIs (GET projects / project / CPF). Each returns live data from
// the backend, or null when the API is unreachable, so pages can fall back to sample data and still render.

import { serverGet } from "@/lib/api";
import type { Campaign, CampaignDetail, Compound, Escalation, Project, ProjectDetail, Proposal } from "@/lib/fixtures";

export async function getProjects(): Promise<Project[] | null> {
  const data = await serverGet<{ projects: Project[] }>("/api/v1/projects");
  return data ? data.projects : null;
}

export async function getProject(projectId: string): Promise<ProjectDetail | null> {
  return serverGet<ProjectDetail>(`/api/v1/projects/${projectId}`);
}

type CpfView = {
  compound: string;
  version: number;
  completeness: number;
  parameters: Compound["parameters"];
};

export async function getCompoundCpf(projectId: string, compound: string): Promise<Compound | null> {
  const view = await serverGet<CpfView>(`/api/v1/projects/${projectId}/compounds/${compound}/cpf`);
  if (!view) return null;
  return {
    name: view.compound,
    project: projectId,
    version: view.version,
    completeness: view.completeness,
    parameters: view.parameters,
  };
}

export type StudyRow = {
  study_id: string;
  reference?: string;
  route: string;
  dose_mg: number;
  infusion_time_min?: number | null;
  formulation: string;
  food_state: string;
  n?: number;
  n_timepoints?: number;
  profile?: { times: number[]; values: number[]; time_unit: string; unit: string };
};

/** The observed clinical studies uploaded for a project (what a campaign fits and validates against). */
export async function getStudies(projectId: string): Promise<StudyRow[] | null> {
  const data = await serverGet<{ studies: StudyRow[] }>(`/api/v1/projects/${projectId}/studies`);
  return data ? data.studies : null;
}

/** Campaigns for the tenant, or just one project's when `project` is given. */
export async function getCampaigns(project?: string): Promise<Campaign[] | null> {
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  const data = await serverGet<{ campaigns: Campaign[] }>(`/api/v1/campaigns${query}`);
  return data ? data.campaigns : null;
}

export async function getCampaign(campaignId: string): Promise<CampaignDetail | null> {
  return serverGet<CampaignDetail>(`/api/v1/campaigns/${campaignId}`);
}

export async function getEscalations(): Promise<Escalation[] | null> {
  const data = await serverGet<{ escalations: Escalation[] }>("/api/v1/escalations");
  return data ? data.escalations : null;
}

export async function getProposals(): Promise<Proposal[] | null> {
  const data = await serverGet<{ proposals: Proposal[] }>("/api/v1/proposals");
  return data ? data.proposals : null;
}
