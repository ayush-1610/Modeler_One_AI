// T-49: CPF v1 is assembled from accepted evidence, the studies from accepted datasets; readiness builds every planned
// simulation (software); the inputs are accepted and handed to the plan. Values and data here are software test data
// entered through the API, the way a curator would enter them by hand.
import { expect, test } from "@playwright/test";

const AUTH = { Authorization: "Bearer dev" };

test("model inputs are assembled from evidence, checked, accepted and handed to the plan", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "Inputamide", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nIV infusion study.") } },
  });
  const projectId = (await started.json()).data.project_id as string;
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();

  const values: [string, string, number | string, string | null, Record<string, string>][] = [
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
    expect((await request.post(`/api/v1/projects/${projectId}/evidence/${id}:decide`, {
      headers: AUTH, data: { state: "ACCEPTED", reason: "checked against the review" } })).ok()).toBeTruthy();
  }
  const ds = await request.post(`/api/v1/projects/${projectId}/datasets`, { headers: AUTH, data: {
    study: { study_id: "doe-iv-250", reference: "Doe 2019", n: 12, route: "iv_infusion", dose_mg: 250, infusion_time_min: 60,
             formulation: "solution", food_state: "fasted", n_timepoints: 5 },
    time_unit: "h", unit: "µmol/l", origin: "LITERATURE", source: { doi: "10.1/review", locator: "Table 3" },
    series: [{ name: "mean", statistic: "arithmetic_mean", times: [0.5, 1, 2, 4, 8], values: [20, 35, 21, 9, 2], n: 12 }] } });
  expect(ds.ok(), await ds.text()).toBeTruthy();
  const dsId = (await ds.json()).data.id as string;
  expect((await request.post(`/api/v1/projects/${projectId}/datasets/${dsId}:decide`, {
    headers: AUTH, data: { state: "ACCEPTED", reason: "table 3 checked" } })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}/inputs`);
  await page.getByTestId("assemble").click();
  await expect(page.getByTestId("ready-chip")).toHaveText("ready");
  const logp = page.getByTestId("record-phys.logp");
  await expect(logp).toContainText("Log Units");
  await expect(logp).toContainText("Publication · InVitro");
  await expect(page.getByTestId("record-elim.renal.gfr_fraction")).toContainText("GlomerularFiltration");
  await page.getByRole("button", { name: "Readiness" }).click();
  await expect(page.getByTestId("check-every planned simulation builds (software)")).toContainText("ok");
  await page.getByRole("button", { name: "Studies" }).click();
  await expect(page.getByTestId("study-doe-iv-250")).toContainText("literature");
  await page.getByTestId("accept-inputs").click();
  await expect(page.getByText("Inputs accepted (P4).")).toBeVisible();
  await page.getByTestId("publish-inputs").click();
  await expect(page.getByText("handed to the plan (1 study)")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("inputs.png"), fullPage: true });
  const studies = await request.get(`/api/v1/projects/${projectId}/studies`, { headers: AUTH });
  expect((await studies.json()).data.studies[0].origin).toBe("LITERATURE");
});
