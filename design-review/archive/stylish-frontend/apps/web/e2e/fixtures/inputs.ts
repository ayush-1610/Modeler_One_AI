// A project with ready model inputs, built through the API the way a curator enters values by hand.
// Software test data (made-up numbers): it exercises the pipeline, never a model.
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const AUTH = { Authorization: "Bearer dev" };

type Study = { study_id: string; route: string; dose_mg: number; food_state?: string; co_medication?: string };
type BriefChange = { path: string; value: unknown; unit?: string };

// What Start needs before Inputs opens (page review 1, decision 7): the question and its applications, the ICH M15 model
// risk with why each rating is what it is, and what is modelled. Entered by a person, as on the Start screen.
export const START_DONE: BriefChange[] = [
  { path: "qoi.text", value: "Exposure after the doses studied" },
  { path: "qoi.context_of_use", value: "Software test project: exercises the pipeline, never a model" },
  { path: "qoi.applications", value: ["APP-01 model build and verification"] },
  { path: "m15.influence_rating", value: "medium" }, { path: "m15.consequence_rating", value: "medium" },
  { path: "acceptance.tier", value: "medium" },
  { path: "m15.influence", value: "The model supports the decision alongside the clinical data" },
  { path: "m15.consequence", value: "A wrong prediction would be caught by the next clinical study" },
  { path: "drug.modality", value: "small_molecule" }, { path: "scope.pbpk_model", value: "full" },
  { path: "scope.site_of_action", value: "systemic" }, { path: "scope.formulation_types", value: ["solution", "ir_tablet"] },
  { path: "scenarios[0].route", value: "oral" },
];

/** The requests the page sends about the project while `act` runs and the page settles: `METHOD route` for the API (the
 *  escalations bell's own polls left out), `server render <path>` for a part drawn on the server again, `prefetch <path>`
 *  for Next's prefetch of a page a link leads to; paths with the project's id as `<p>`. */
export async function requestsDuring(page: Page, projectId: string, act: () => Promise<void>, settle = 1500): Promise<string[]> {
  const seen: string[] = [];
  const hear = (r: { method(): string; url(): string; headers(): Record<string, string> }) => {
    const url = r.url();
    if (url.includes("_rsc=")) {
      const path = new URL(url).pathname.replace(`/projects/${projectId}`, "/projects/<p>");
      seen.push(r.headers()["next-router-prefetch"] ? `prefetch ${path}` : `server render ${path}`);
    } else if (url.includes("/api/v1/") && !/\/api\/v1\/escalations(\?|$)/.test(url)) {
      seen.push(`${r.method()} ${url.replace(/^.*\/api\/v1\/(projects\/[^/?]+\/)?/, "")}`);
    }
  };
  page.on("request", hear);
  await act();
  await page.waitForTimeout(settle);
  page.off("request", hear);
  return seen;
}

/** The sidebar's links (Projects, Start from proposal, the library, the history): prefetched again by Next whenever the
 *  page is drawn again on the server. Every other link of Inputs is not prefetched (final review round 4). */
export const SIDEBAR_PREFETCH = /^prefetch \/(projects\/(start|<p>\/(library|history)))?$/;

/** In Client files, open a file's row on its sheets and their reading (plan 2026-11-14 slice 1), unless it is open. */
export async function openFile(page: Page, name: string) {
  const toggle = page.getByTestId(`file-toggle-${name}`);
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  await expect(page.getByTestId(`client-file-${name}`)).toBeVisible();
}

/** Start done through the API, as a person would on the Start screen, so Inputs opens (page review 1, decision 7). */
export async function finishStart(request: APIRequestContext, projectId: string, extra: BriefChange[] = []) {
  const done = await request.put(`/api/v1/projects/${projectId}/brief`, { headers: AUTH,
    data: { changes: [...START_DONE, ...extra].map((c) => ({ ...c, status: "EDITED" })) } });
  expect(done.ok(), await done.text()).toBeTruthy();
  const steps = await request.get(`/api/v1/projects/${projectId}/steps`, { headers: AUTH });
  const start = ((await steps.json()).data.steps as { step: string; state: string; reasons: string[] }[]).find((s) => s.step === "start");
  expect(start?.state, start?.reasons.join("; ")).toBe("done");
}

export async function projectWithInputs(request: APIRequestContext, drug: string, studies: Study[],
                                        { assemble = true, brief = [] as BriefChange[] } = {}) {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: drug, extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nPBPK model.") } },
  });
  const projectId = (await started.json()).data.project_id as string;
  if (brief.length) {      // the brief's fields a flow needs, entered by a person before the data plan is derived
    const edited = await request.put(`/api/v1/projects/${projectId}/brief`, { headers: AUTH,
      data: { changes: brief.map((c) => ({ ...c, status: "EDITED" })) } });
    expect(edited.ok(), await edited.text()).toBeTruthy();
  }
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
      series: [{ name: "mean", statistic: "arithmetic_mean", times: [0.5, 1, 2, 4, 8], values: [20, 35, 21, 9, 2], n: 12 }],
      demographics_choice: "healthy_adult_default" } });   // D-29: never silent
    expect(ds.ok(), await ds.text()).toBeTruthy();
    const id = (await ds.json()).data.id as string;
    await request.post(`/api/v1/projects/${projectId}/datasets/${id}:decide`, { headers: AUTH, data: { state: "ACCEPTED", reason: "checked" } });
  }
  if (assemble) {     // ready inputs are what the plan reads; nothing is accepted (D-27)
    const assembled = await request.post(`/api/v1/projects/${projectId}/inputs:assemble`, { headers: AUTH });
    expect((await assembled.json()).data.readiness.content.ready).toBeTruthy();
  }
  return projectId;
}
