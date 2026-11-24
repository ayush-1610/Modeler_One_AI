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

/** The projects with each one's four steps and its owner (`?with=steps,owner`, the redesign's R-N03): one read for Home,
 *  Your work and Projects instead of one `/steps` and one `/members` per project. */
export const getPortfolio = cache(async (): Promise<Live<Project[]>> => {
  return pick(await serverGet("/api/v1/projects", {}, { with: "steps,owner" }), (d) => d.projects);
});

/** A project's members, its owner and whether this person changes it (`you_change_it`; false: shared to read). */
export const getMembers = cache(async (projectId: string) => serverGet("/api/v1/projects/{project_id}/members", { project_id: projectId }));

/** A project's blinding: whether external-validation studies are withheld until the MAP is signed, and why. */
export const getBlinding = cache(async (projectId: string) => serverGet("/api/v1/projects/{project_id}/blinding", { project_id: projectId }));

/** Whether a project is archived, by whom, when and why: only the project list carries it (`GET /projects/{id}` does
 *  not), so it is read from there (one request, shared within the render). */
export async function getArchived(projectId: string) {
  const live = await getProjects();
  return live.data?.find((p) => p.id === projectId)?.archived ?? null;
}

/** The signed-in person: their id (to tell the projects they own) and their roles. */
export const getMe = cache(async () => serverGet("/api/v1/me", {}));

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

/** A stored record this version cannot read, named with why (one written in an earlier shape no longer fails its list). */
export type UnreadableRecord = Schema<"UnreadableRecord">;

/** The campaign list as the API answers it: the campaigns, and those it could not read. */
export const getCampaignList = cache(async (project?: string): Promise<Live<{ campaigns: Campaign[]; unreadable: UnreadableRecord[] }>> => {
  return pick(await serverGet("/api/v1/campaigns", {}, { project }), (d) => ({ campaigns: d.campaigns, unreadable: d.unreadable ?? [] }));
});

/** Campaigns for the tenant, or just one project's when `project` is given. */
export const getCampaigns = cache(async (project?: string): Promise<Live<Campaign[]>> => {
  return pick(await getCampaignList(project), (d) => d.campaigns);
});

export const getCampaign = cache(async (campaignId: string): Promise<Live<CampaignDetail>> => {
  return pick(await serverGet("/api/v1/campaigns/{campaign_id}", { campaign_id: campaignId }), (d) => narrow<CampaignDetail>(d));
});

/** A campaign's S7 package as the API answers it (`GET /campaigns/{id}/package`): reproduction, hashes, files, the PK-Sim
 *  projects and the report's issues. 404 (notFound) until S7 has run. */
export const getCampaignPackage = cache(async (campaignId: string) =>
  serverGet("/api/v1/campaigns/{campaign_id}/package", { campaign_id: campaignId }));

export const getEscalations = cache(async (): Promise<Live<Escalation[]>> => {
  return pick(await serverGet("/api/v1/escalations", {}), (d) => d.escalations.map((e) => narrow<Escalation>(e)));
});
