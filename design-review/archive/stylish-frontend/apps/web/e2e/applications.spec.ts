// R4c (redesign §3.3): the VBE crossover's inputs are set on Review & sign, never defaulted, with what is still missing
// shown; every other application of the brief says what the campaign does with it, and one S6 cannot run yet is
// acknowledged into the MAP's limitations. Software test data: it exercises the page, never a model.
import { expect, test } from "@playwright/test";

import { AUTH, projectWithInputs } from "./fixtures/inputs";

test.use({ viewport: { width: 1600, height: 1200 } });

test("the VBE panel and the applications the campaign cannot run yet", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Applicamide", [
    { study_id: "iv-250", route: "iv_infusion", dose_mg: 250 }, { study_id: "po-10", route: "oral", dose_mg: 10 },
    { study_id: "po-50", route: "oral", dose_mg: 50 },
  ], { brief: [
    { path: "qoi.applications", value: ["APP-03 enzyme DDI", "APP-12 food effect", "APP-14 virtual bioequivalence"] },
    { path: "scenarios[0].route", value: "oral" },
    { path: "scenarios[0].dose", value: 10, unit: "mg" },
    { path: "scenarios[0].regimen", value: "MD, 10 mg twice daily" },
  ] });
  expect((await request.get(`/api/v1/projects/${projectId}/plan`, { headers: AUTH })).ok()).toBeTruthy();   // built on first read
  const risk = await request.put(`/api/v1/projects/${projectId}/plan/structure`, { headers: AUTH,
    data: { key: "model_risk", value: "medium", reason: "supports a decision with clinical evidence" } });
  expect(risk.ok(), await risk.text()).toBeTruthy();

  await page.goto(`/projects/${projectId}/plan`);
  const section = page.getByTestId("review-applications");
  await expect(section.getByTestId("application-APP-14")).toContainText("runs at S6");
  await expect(section.getByTestId("application-APP-12")).toContainText("partly supported");
  await expect(section.getByTestId("application-APP-03")).toContainText("not supported yet");
  await expect(section.getByTestId("scenario-0")).toContainText("regimen: MD, 10 mg twice daily");
  await expect(section.getByTestId("scenario-0")).toContainText("not simulated yet");

  // the VBE design: nothing defaulted; without an observed BE study the result will not be validated (F-304)
  const vbe = section.getByTestId("vbe-panel");
  await expect(vbe.getByTestId("vbe-problems")).toContainText("Virtual trials: not given");
  await expect(vbe.getByTestId("vbe-not-validated-warning")).toBeVisible();
  await vbe.getByTestId("vbe-n_subjects").fill("24");
  await vbe.getByTestId("vbe-n_trials").fill("100");
  await vbe.getByTestId("vbe-seed").fill("7");
  await vbe.getByTestId("vbe-pos_threshold").fill("0.8");
  await vbe.getByTestId("vbe-variability-add").click();
  const row = vbe.getByTestId("vbe-variability-0");
  await row.getByLabel("parameter 1").fill("Organism|Lumen|Stomach|Gastric emptying time");
  await row.getByLabel("CV 1").fill("30");
  await row.getByLabel("source 1").fill("a cited crossover study");
  await vbe.getByTestId("vbe-reason").fill("the BE question of the proposal");
  await vbe.getByTestId("vbe-save").click();
  // what is left are the TEST and reference products, which this CPF does not define yet (Inputs, Formulations tab)
  await expect(vbe.getByTestId("vbe-problems")).not.toContainText("Virtual trials");
  await expect(vbe.getByTestId("vbe-problems").locator("li")).toHaveCount(2);
  await expect(vbe.getByTestId("vbe-problems")).toContainText("TEST formulation (a CPF formulation, form.{name}.*): not given");
  await expect(vbe.getByTestId("vbe-n_trials")).toHaveValue("100");

  // an application S6 cannot run yet, acknowledged: the MAP names it among its limitations
  await section.getByLabel("acknowledge APP-03").fill("the DDI question is answered by a separate clinical study");
  await section.getByTestId("acknowledge-APP-03").click();
  await expect(section.getByTestId("application-APP-03")).toContainText("acknowledged: the DDI question");
  await expect(page.getByTestId("limitations")).toContainText("APP-03 enzyme DDI: not supported yet");
  await page.screenshot({ path: test.info().outputPath("applications.png"), fullPage: true });
});
