// T-49, redesign §3.2: the values and data flow in with no acceptance (D-27): CPF v1 is assembled from the evidence and
// the studies from the datasets, readiness builds every planned simulation (software), and the step hands over to Review
// & sign. Values and data here are software test data entered through the API, the way a curator would enter them.
import { expect, test } from "@playwright/test";

const AUTH = { Authorization: "Bearer dev" };

test("model inputs flow in from the evidence, are checked, and hand over to Review & sign with no acceptance", async ({ page, request }) => {
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
    expect(r.ok(), await r.text()).toBeTruthy();                      // proposed, never accepted one by one
  }
  const ds = await request.post(`/api/v1/projects/${projectId}/datasets`, { headers: AUTH, data: {
    study: { study_id: "doe-iv-250", reference: "Doe 2019", n: 12, route: "iv_infusion", dose_mg: 250, infusion_time_min: 60,
             formulation: "solution", food_state: "fasted", n_timepoints: 5 },
    time_unit: "h", unit: "µmol/l", origin: "LITERATURE", source: { doi: "10.1/review", locator: "Table 3" },
    series: [{ name: "mean", statistic: "arithmetic_mean", times: [0.5, 1, 2, 4, 8], values: [20, 35, 21, 9, 2], n: 12 }],
    demographics_choice: "healthy_adult_default" } });   // D-29: never silent
  expect(ds.ok(), await ds.text()).toBeTruthy();

  await page.goto(`/projects/${projectId}/inputs`);
  await expect(page.getByTestId("inputs-ready")).toBeVisible();              // nothing still missing, nothing to accept
  const logp = page.getByTestId("record-phys.logp");
  await expect(logp).toContainText("Log Units");
  await expect(logp).toContainText("regulatory review");
  await expect(page.getByTestId("record-elim.renal.gfr_fraction")).toContainText("GlomerularFiltration");
  await expect(page.getByTestId("check-every planned simulation builds (software)")).toContainText("ok");
  await page.getByTestId("tab-studies").click();
  await expect(page.getByTestId("study-doe-iv-250")).toContainText("literature");
  await expect(page.getByTestId("study-doe-iv-250")).toContainText("S1");               // the role the MS-01 split proposes
  await expect(page.getByRole("button", { name: /Accept|Approve|Hand to/ })).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("inputs.png"), fullPage: true });
  await page.getByRole("link", { name: "Go to Review & sign" }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/plan`));
});
