// Typed server-side fetchers for the read APIs. Each returns the live data or the problem that prevented it
// (`Live<T>`); pages render the problem instead of sample data.

import { serverRead, type Live } from "@/lib/api";
import type { Campaign, CampaignDetail, Compound, Escalation, Project, ProjectDetail, Proposal } from "@/lib/types";

function pick<A, B>(live: Live<A>, f: (a: A) => B): Live<B> {
  return { ...live, data: live.data === null ? null : f(live.data) };
}

export async function getProjects(): Promise<Live<Project[]>> {
  return pick(await serverRead<{ projects: Project[] }>("/api/v1/projects"), (d) => d.projects);
}

export async function getProject(projectId: string): Promise<Live<ProjectDetail>> {
  return serverRead<ProjectDetail>(`/api/v1/projects/${projectId}`);
}

type CpfView = {
  compound: string;
  version: number;
  completeness: number;
  parameters: Compound["parameters"];
};

export async function getCompoundCpf(projectId: string, compound: string): Promise<Live<Compound>> {
  const live = await serverRead<CpfView>(`/api/v1/projects/${projectId}/compounds/${compound}/cpf`);
  return pick(live, (view) => ({
    name: view.compound,
    project: projectId,
    version: view.version,
    completeness: view.completeness,
    parameters: view.parameters,
  }));
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
export async function getStudies(projectId: string): Promise<Live<StudyRow[]>> {
  return pick(await serverRead<{ studies: StudyRow[] }>(`/api/v1/projects/${projectId}/studies`), (d) => d.studies);
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
  return pick(await serverRead<{ proposals: Proposal[] }>("/api/v1/proposals"), (d) => d.proposals);
}
