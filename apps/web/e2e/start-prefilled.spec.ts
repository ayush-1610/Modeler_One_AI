// Start pre-filled (the owner, 2026-11-06: "making sure everything is there; the user will just see through and only
// change in case the selection or pre-fills are way wrong"). With agents off, as in these browser flows, code reads the
// proposal: the question, the context of use, the applications, the dosage form and the route, each drafted with the
// sentence it rests on; a full PBPK model of systemic action pre-selected as the default. Each is confirmed in place.
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
  await expect(question).toContainText("Question of interest: confirm the intake agent's proposal, or change it");
  await expect(page.getByTestId("start-field-qoi.context_of_use"))
    .toContainText("The modelling results are intended to support the regulatory submission to Health Canada.");
  await expect(page.getByTestId("start-field-qoi.applications")).toContainText("virtual bioequivalence");
  await expect(page.getByTestId("gate-formulation_types").getByRole("checkbox", { name: "modified release" })).toBeChecked();
  await expect(page.getByTestId("route-0")).toHaveValue("oral");
  await expect(page.getByTestId("pick-pbpk_model-full")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("gate-pbpk_model-state")).toHaveText("to confirm");
  await expect(page.getByTestId("pick-site_of_action-systemic")).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({ path: test.info().outputPath("start-prefilled.png"), fullPage: true });

  // the person reads through and confirms each; nothing here is left "not set"
  for (const path of ["qoi.text", "qoi.context_of_use", "qoi.applications", "scope.formulation_types", "scenarios[0].route",
                      "scope.pbpk_model", "scope.site_of_action"]) {
    await page.getByTestId(`confirm-${path}`).click();
    await expect(page.getByTestId(`confirm-${path}`)).toHaveCount(0);
  }
  await expect(page.getByTestId("start-scope")).not.toContainText("confirm the intake agent's proposal");
  await expect(page.getByTestId("start-brief")).not.toContainText("not set yet");
  await expect(page.getByTestId("gate-pbpk_model-state")).toHaveText("supported");
});
