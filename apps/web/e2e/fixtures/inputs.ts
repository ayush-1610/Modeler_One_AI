// A project with accepted model inputs (P4), built through the API the way a curator enters values by hand.
// Software test data (made-up numbers): it exercises the pipeline, never a model.
import { expect, type APIRequestContext } from "@playwright/test";

export const AUTH = { Authorization: "Bearer dev" };

type Study = { study_id: string; route: string; dose_mg: number; food_state?: string; co_medication?: string };

export async function projectWithInputs(request: APIRequestContext, drug: string, studies: Study[], { accept = true } = {}) {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: drug, extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nPBPK model.") } },
  });
  const projectId = (await started.json()).data.project_id as string;
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const values: [string, string, number, string | null, Record<string, string>][] = [
    ["REQ-phys.mw", "phys.mw", 225.2, "g/mol", {}],
    ["REQ-phys.logp", "phys.logp", -1.56, null, { type: "logP", pH: "7.4", method: "shake flask, measured" }],
    ["REQ-bind.fu", "bind.fu", 85, "%", { species: "human", matrix: "plasma", method: "ED", concentration: "1 µM" }],
    ["REQ-phys.solubility.ref", "phys.solubility.ref", 1.3, "mg/ml", { pH: "7", medium: "water" }],
    ["REQ-phys.pka", "phys.pka", 2.3, null, { type: "base", method: "potentiometric, measured" }],
    ["REQ-elim.renal", "elim.renal.gfr_fraction", 1, null, {}],
  ];
  for (const [req_id, target, value, unit, conditions] of values) {
    const r = await request.post(`/api/v1/projects/${projectId}/evidence`, {
      headers: AUTH, data: { req_id, target, value, unit, conditions, source_type: "REGULATORY_REVIEW", doi: "10.1/review", year: 2019 } });
    expect(r.ok(), await r.text()).toBeTruthy();
    const id = (await r.json()).data.id as string;
    await request.post(`/api/v1/projects/${projectId}/evidence/${id}:decide`, { headers: AUTH, data: { state: "ACCEPTED", reason: "checked" } });
  }
  for (const s of studies) {
    const ds = await request.post(`/api/v1/projects/${projectId}/datasets`, { headers: AUTH, data: {
      study: { study_id: s.study_id, reference: "Doe 2019", n: 12, route: s.route, dose_mg: s.dose_mg, formulation: "solution",
               food_state: s.food_state ?? "fasted", n_timepoints: 5, ...(s.route === "iv_infusion" ? { infusion_time_min: 60 } : {}),
               ...(s.co_medication ? { co_medication: s.co_medication } : {}) },
      time_unit: "h", unit: "µmol/l", origin: "LITERATURE", source: { doi: "10.1/review", locator: "Table 3" },
      series: [{ name: "mean", statistic: "arithmetic_mean", times: [0.5, 1, 2, 4, 8], values: [20, 35, 21, 9, 2], n: 12 }] } });
    expect(ds.ok(), await ds.text()).toBeTruthy();
    const id = (await ds.json()).data.id as string;
    await request.post(`/api/v1/projects/${projectId}/datasets/${id}:decide`, { headers: AUTH, data: { state: "ACCEPTED", reason: "checked" } });
  }
  if (accept) {
    const assembled = await request.post(`/api/v1/projects/${projectId}/inputs:assemble`, { headers: AUTH });
    expect((await assembled.json()).data.readiness.content.ready).toBeTruthy();
    expect((await request.post(`/api/v1/projects/${projectId}/inputs:accept`, { headers: AUTH, data: {} })).ok()).toBeTruthy();
  }
  return projectId;
}
