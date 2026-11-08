// Start pre-filled (the owner, 2026-11-06: "making sure everything is there; the user will just see through and only
// change in case the selection or pre-fills are way wrong"). With agents off, as in these browser flows, code reads the
// proposal: the question, the context of use, the applications, the dosage form and the route, each drafted with the
// sentence it rests on; a full PBPK model of systemic action pre-selected as the default. Each is confirmed in place.
// Build K (the owner, 2026-11-07): the drug's disposition the proposal states, and the ICH M15 model risk drafted by the
// rule (UNVERIFIED) when the intake agent is off, pre-selected for the person to save.
import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

const PROPOSAL = `Technical proposal: PBPK modelling support for Prefillamide Succinate ER Tablets

1. Introduction
Prefillamide Succinate Extended Release Tablets are being developed in two strengths: 50 mg and 100 mg for the Canadian market.
Two pilot bioequivalence studies in healthy volunteers (single oral dose, fasting) showed a lower Cmax for the test product.

2. Objective
The objective of this work is to develop and verify a PBPK model of prefillamide and to evaluate, through virtual bioequivalence trials, whether the test formulation is bioequivalent to the reference product.

3. Scope
The dissolution profiles of both products in 900 mL phosphate buffer solution pH 6.8 will be used as input.
The modelling results are intended to support the regulatory submission to Health Canada.

4. The drug
Prefillamide is a BCS Class I compound.
It is metabolized mainly by CYP3A4, and about 30% of a dose is excreted unchanged in urine.
Its pharmacokinetics are linear and dose-proportional between 25 and 200 mg.
`;

test("a proposal's Start fields arrive pre-filled with their quotes, each confirmed in place", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Prefillamide", extract: "true",
    files: { name: "Technical proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) } } });
  expect(started.ok(), await started.text()).toBeTruthy();
  const projectId = (await started.json()).data.project_id as string;
  await expect.poll(async () => (await (await request.get(`/api/v1/projects/${projectId}/brief`, { headers: AUTH })).json())
    .data.extraction_running, { timeout: 60_000 }).toBe(false);

  await page.goto(`/projects/${projectId}/start`);
  const question = page.getByTestId("start-field-qoi.text");
  await expect(question).toContainText("The objective of this work is to develop and verify a PBPK model");
  await expect(question).toContainText("Question of interest: confirm the draft, or change it");
  await expect(page.getByTestId("start-field-qoi.context_of_use"))
    .toContainText("The modelling results are intended to support the regulatory submission to Health Canada.");
  await expect(page.getByTestId("start-field-qoi.applications")).toContainText("virtual bioequivalence");
  await expect(page.getByTestId("gate-formulation_types").getByRole("checkbox", { name: "modified release" })).toBeChecked();
  await expect(page.getByTestId("route-0")).toHaveValue("oral");
  await expect(page.getByTestId("pick-pbpk_model-full")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("gate-pbpk_model-state")).toHaveText("to confirm");
  await expect(page.getByTestId("pick-site_of_action-systemic")).toHaveAttribute("aria-pressed", "true");
  // the drug's disposition, as the proposal states it
  await expect(page.getByTestId("start-field-drug.bcs_class")).toContainText("I");
  await expect(page.getByTestId("pathway-list")).toContainText("CYP3A4");
  await expect(page.getByTestId("pathway-list")).toContainText("renal filtration");
  await expect(page.getByTestId("stated-scope.nonlinearity-no")).toHaveAttribute("aria-pressed", "true");    // linear PK
  await expect(page.getByTestId("start-field-scope.nonlinearity")).toContainText("draft by code");
  // the model risk: the agent is off, so the ICH M15 rule drafted it (a submission alongside clinical data: medium)
  await expect(page.getByTestId("start-intake")).toContainText("The intake agent is off");
  await expect(page.getByTestId("risk-influence-medium")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("risk-consequence-medium")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("risk-influence-preselected")).toContainText("The ICH M15 rule (UNVERIFIED) suggests medium");
  await expect(page.getByTestId("start-field-m15.influence")).toContainText("supports a regulatory decision alongside the clinical data");
  await page.screenshot({ path: test.info().outputPath("start-prefilled.png"), fullPage: true });

  // the person reads through and confirms each; nothing here is left "not set"
  for (const path of ["qoi.text", "qoi.context_of_use", "qoi.applications", "scope.formulation_types", "scenarios[0].route",
                      "scope.pbpk_model", "scope.site_of_action", "drug.modality"]) {
    await page.getByTestId(`confirm-${path}`).click();
    await expect(page.getByTestId(`confirm-${path}`)).toHaveCount(0);
  }
  await expect(page.getByTestId("start-scope")).not.toContainText("confirm the draft");
  await expect(page.getByTestId("start-brief")).not.toContainText("not set yet");
  await expect(page.getByTestId("gate-product-line")).toContainText("full PBPK");          // the three gates, one line
  for (const id of ["confirm-drug.bcs_class", "confirm-pathways", "confirm-scope.nonlinearity"]) {
    await page.getByTestId(id).click();
    await expect(page.getByTestId(id)).toHaveCount(0);
  }
  await expect(page.getByTestId("stated-scope.nonlinearity-no")).toHaveAttribute("aria-pressed", "true");     // saved as no
  // the model risk: saved as pre-selected, its two reasons confirmed; then Start is done
  await page.getByTestId("risk-save").click();
  await expect(page.getByTestId("risk-current")).toHaveText("Saved: medium");
  for (const path of ["m15.influence", "m15.consequence"]) {
    await page.getByTestId(`confirm-${path}`).click();
    await expect(page.getByTestId(`confirm-${path}`)).toHaveCount(0);
  }
  await expect(page.getByTestId("start-brief")).not.toContainText("confirm the draft");
  await expect(page.getByTestId("start-done")).toBeVisible();
});

test("every draft is confirmed as shown in one step; the model risk keeps its own save", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Bulkamide", extract: "true",
    files: { name: "Technical proposal.md", mimeType: "text/markdown",
             buffer: Buffer.from(PROPOSAL.replace(/Prefillamide/g, "Bulkamide").replace(/prefillamide/g, "bulkamide")) } } });
  expect(started.ok(), await started.text()).toBeTruthy();
  const projectId = (await started.json()).data.project_id as string;
  await expect.poll(async () => (await (await request.get(`/api/v1/projects/${projectId}/brief`, { headers: AUTH })).json())
    .data.extraction_running, { timeout: 60_000 }).toBe(false);

  await page.goto(`/projects/${projectId}/start`);
  const all = page.getByTestId("start-confirm-all");
  await expect(all).toContainText(/Confirm all \d+ drafts as shown/);
  await all.click();
  await expect(all).toHaveCount(0);
  await expect(page.getByTestId("stated-scope.nonlinearity-no")).toHaveAttribute("aria-pressed", "true");   // linear: no
  await expect(page.getByTestId("start-waiting")).toContainText("3 things still need you");    // the ratings and the tier
  await page.getByTestId("risk-save").click();
  await expect(page.getByTestId("start-done")).toBeVisible();
});
