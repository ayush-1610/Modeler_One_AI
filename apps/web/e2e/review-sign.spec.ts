// Step 3 · Review & sign (redesign §3.3): the review table shows every input with its source, the filters narrow it, a
// value is set aside with a reason and the next source takes its place; credibility shows the stage split and the
// limitations the MAP will carry. The canvas, the validator and the signature are covered by model-plan.spec.ts.
import { expect, test } from "@playwright/test";

import { AUTH, projectWithInputs } from "./fixtures/inputs";

test.use({ viewport: { width: 1600, height: 1200 } });

test("the review table, an exclusion with a reason, and the credibility the MAP will carry", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Reviewamide", [
    { study_id: "iv-250", route: "iv_infusion", dose_mg: 250 }, { study_id: "po-10", route: "oral", dose_mg: 10 },
    { study_id: "po-50", route: "oral", dose_mg: 50 },
  ]);
  // a second logP source within 10 % of the first (D-32): one value, two sources
  const second = await request.post(`/api/v1/projects/${projectId}/evidence`, { headers: AUTH, data: {
    req_id: "REQ-phys.logp", target: "phys.logp", value: -1.5, unit: null, source_type: "PUBLICATION", doi: "10.1/paper",
    year: 2015, conditions: { type: "logP", pH: "7.4", method: "shake flask, measured" } } });
  expect(second.ok(), await second.text()).toBeTruthy();

  await page.goto(`/projects/${projectId}/plan`);
  // Start is not finished here, but Inputs has begun (it is done): a step that has begun is never locked
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "needs_you");
  await expect(page.getByTestId("step-inputs-locked")).toHaveCount(0);
  await expect(page.getByTestId("step-inputs").getByRole("link")).toBeVisible();
  await expect(page.getByTestId("step-run-locked")).toBeVisible();          // Run has not begun: it waits on Start
  const table = page.getByTestId("review-table");
  await expect(table.getByTestId("review-row-phys.logp")).toContainText("1 other source agrees");
  await expect(table.getByTestId("review-row-phys.logp")).toContainText("high");
  await table.getByTestId("review-filter-from_agent").click();
  await expect(table).toContainText("No input matches this filter");
  await table.getByTestId("review-filter-all").click();

  await expect(page.getByTestId("stage-S3")).toContainText("34 min");        // MS-01's 7 % of the 8 h default (D-31)
  await expect(page.getByTestId("limitations")).toContainText("healthy adult default");

  // the kept source set aside with a reason: the agreeing one takes its place, and the plan asks to be brought up to date
  await table.getByTestId("exclude-phys.logp").click();
  await expect(table.getByTestId("exclude-only-phys.logp")).toHaveCount(0);
  await table.getByTestId("exclude-reason-phys.logp").fill("the review copies the paper; keep the primary measurement");
  await table.getByTestId("exclude-confirm-phys.logp").click();
  await expect(table.getByTestId("review-row-phys.logp")).toContainText("-1.5");
  await expect(page.getByTestId("plan-stale")).toBeVisible();
  await page.getByRole("button", { name: "Bring it up to date" }).click();
  await expect(page.getByTestId("plan-stale")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("review.png"), fullPage: true });
});

// R4b (redesign §3.3, D-34): the estimation plan proposes MS-01 §2.2's default bounds and a parameter is estimated with
// them and a reason; the validation plan names what S4 and S5 judge and what follows a failure; the tier's criteria are
// shown, and an internal target stricter than the tier is set (the MAP records it and the verdicts apply it, R4d)
// while a looser one is refused by the validator.
test("the estimation plan, the validation plan and the tier's acceptance criteria", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Estimamide", [
    { study_id: "iv-250", route: "iv_infusion", dose_mg: 250 }, { study_id: "po-10", route: "oral", dose_mg: 10 },
    { study_id: "po-50", route: "oral", dose_mg: 50 },
  ]);
  expect((await request.get(`/api/v1/projects/${projectId}/plan`, { headers: AUTH })).ok()).toBeTruthy();   // built on first read
  const risk = await request.put(`/api/v1/projects/${projectId}/plan/structure`, { headers: AUTH,
    data: { key: "model_risk", value: "medium", reason: "supports a decision with clinical evidence" } });
  expect(risk.ok(), await risk.text()).toBeTruthy();

  await page.goto(`/projects/${projectId}/plan`);
  const estimation = page.getByTestId("estimation-plan");
  await expect(estimation.getByTestId("proposal-phys.logp")).toContainText("[-3.06, -0.06] linear");   // measured ± 1.5
  await expect(estimation.getByTestId("proposal-phys.logp")).toContainText("MS-01 §2.2, measured");
  await expect(estimation.getByTestId("proposal-bind.fu")).toContainText("MS-01: fixed");               // measured fu
  await estimation.getByTestId("estimate-phys.logp").click();
  const form = estimation.getByTestId("estimate-form-phys.logp");
  await expect(form.getByLabel("lower bound of phys.logp")).toHaveValue("-3.06");
  await form.getByLabel("why estimate phys.logp").fill("lipophilicity drives the partition coefficients");
  await form.getByTestId("estimate-save-phys.logp").click();
  await expect(estimation.getByTestId("estimation-row-phys.logp")).toContainText("estimated in S1");
  await estimation.getByTestId("estimation-filter-estimated").click();
  await expect(estimation.locator("[data-testid^='estimation-row-']")).toHaveCount(1);

  const validation = page.getByTestId("validation-plan");
  await expect(validation.getByTestId("validation-S4")).toContainText("never refitted");
  await expect(validation.getByTestId("validation-S5")).toContainText("MS-01 §6.6");

  const criteria = page.getByTestId("acceptance-criteria");
  await expect(criteria.getByTestId("criterion-AUC")).toContainText("within 1.5-fold");
  await expect(criteria).toContainText("at most 33.3 %");
  await criteria.getByTestId("target-input").fill("40");
  await criteria.getByTestId("target-reason").fill("the client asks for a tighter check");
  await criteria.getByTestId("target-save").click();
  await expect(page.getByText(/looser than the medium tier, which allows at most 33\.3 %/)).toBeVisible();
  await criteria.getByTestId("target-input").fill("20");
  await criteria.getByTestId("target-reason").fill("the client asks for a tighter check");
  await criteria.getByTestId("target-save").click();
  await expect(criteria.getByTestId("internal-target")).toContainText("|prediction error| ≤ 20 %, set here");
  await expect(criteria.getByTestId("target-applied")).toContainText("judges the internal groups");
  await expect(page.getByTestId("limitations")).not.toContainText("Internal target");
  await expect(page.getByText(/looser than the medium tier/)).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("estimation.png"), fullPage: true });
});

// D-37: an MS-01 candidate nobody estimates may be fitted by the diagnosis within MS-01's own default bounds; a person
// keeps one fixed with a reason, lets the diagnosis fit it again, and the MAP's limitations list the candidates.
test("the diagnosis may fit MS-01's candidates within MS-01's defaults unless a person keeps one fixed", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Defaultamide", [
    { study_id: "iv-250", route: "iv_infusion", dose_mg: 250 }, { study_id: "po-10", route: "oral", dose_mg: 10 },
    { study_id: "po-50", route: "oral", dose_mg: 50 },
  ]);
  expect((await request.get(`/api/v1/projects/${projectId}/plan`, { headers: AUTH })).ok()).toBeTruthy();   // built on first read

  await page.goto(`/projects/${projectId}/plan`);
  const estimation = page.getByTestId("estimation-plan");
  await expect(estimation.getByTestId("diagnosis-may-fit-phys.logp")).toContainText("the diagnosis may fit it in S1");
  await expect(estimation.getByTestId("estimation-row-phys.logp")).toContainText("[-3.06, -0.06] linear");
  await expect(estimation.getByTestId("diagnosis-may-fit-bind.fu")).toHaveCount(0);                 // a measured fu stays fixed
  await expect(page.getByTestId("limitations")).toContainText("phys.logp in S1 [-3.06, -0.06] linear");

  await estimation.getByTestId("fix-phys.logp").click();
  await estimation.getByLabel("why keep phys.logp fixed").fill("logP is measured; keep it as measured");
  await estimation.getByRole("button", { name: "Fix", exact: true }).click();
  await expect(estimation.getByTestId("held-fixed-phys.logp")).toBeVisible();
  await expect(estimation.getByTestId("estimation-row-phys.logp")).toContainText("logP is measured; keep it as measured");
  await expect(page.getByTestId("limitations")).not.toContainText("phys.logp in S1");

  await estimation.getByTestId("release-phys.logp").click();
  await estimation.getByLabel("why let the diagnosis fit phys.logp").fill("let the diagnosis decide");
  await estimation.getByRole("button", { name: "Let it" }).click();
  await expect(estimation.getByTestId("diagnosis-may-fit-phys.logp")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("defaults.png"), fullPage: true });
});
