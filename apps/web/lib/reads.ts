// Typed server-side fetchers for the read APIs. Each returns the live data or the problem that prevented it
// (`Live<T>`); pages render the problem instead of sample data.

// The reads are wrapped in React's cache(): within one server render, a page and the components in it (the step bar, the
// page's own checks) share one request per read instead of asking the API again. It never outlives the request: every
// page still reads the API afresh (serverGet stays `no-store`), so a status shown is never an earlier one (audit item 9).
import { cache } from "react";

import { narrow, serverGet, type Live, type Schema } from "@/lib/api";
import type { Campaign, CampaignDetail, Compound, Escalation, Project, ProjectDetail } from "@/lib/types";

function pick<A, B>(live: Live<A>, f: (a: A) => B): Live<B> {
  return { ...live, data: live.data === null ? null : f(live.data) };
}

export const getProjects = cache(async (): Promise<Live<Project[]>> => {
  return pick(await serverGet("/api/v1/projects", {}), (d) => d.projects);
});

export const getProject = cache(async (projectId: string): Promise<Live<ProjectDetail>> => {
  return serverGet("/api/v1/projects/{project_id}", { project_id: projectId });
});

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
export const getStudies = cache(async (projectId: string): Promise<Live<StudyRow[]>> => {
  return pick(await serverGet("/api/v1/projects/{project_id}/studies", { project_id: projectId }), (d) => d.studies);
});

/** Campaigns for the tenant, or just one project's when `project` is given. */
export const getCampaigns = cache(async (project?: string): Promise<Live<Campaign[]>> => {
  return pick(await serverGet("/api/v1/campaigns", {}, { project }), (d) => d.campaigns);
});

export const getCampaign = cache(async (campaignId: string): Promise<Live<CampaignDetail>> => {
  return pick(await serverGet("/api/v1/campaigns/{campaign_id}", { campaign_id: campaignId }), (d) => narrow<CampaignDetail>(d));
});

export const getEscalations = cache(async (): Promise<Live<Escalation[]>> => {
  return pick(await serverGet("/api/v1/escalations", {}), (d) => d.escalations.map((e) => narrow<Escalation>(e)));
});
