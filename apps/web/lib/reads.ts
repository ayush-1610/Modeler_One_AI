// Typed server-side fetchers for the read APIs (GET projects / project / CPF). Each returns live data from
// the backend, or null when the API is unreachable, so pages can fall back to sample data and still render.

import { serverGet } from "@/lib/api";
import type { Compound, Project, ProjectDetail } from "@/lib/fixtures";

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
