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
