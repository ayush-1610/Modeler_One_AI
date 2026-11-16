// D-15: with blinding on, an external study's values are withheld on the Inputs step's Studies tab until the MAP is signed; a
// curator reveals one dataset for a check with a reason. Software test data (made-up numbers), never a model.
import { expect, test } from "@playwright/test";

import { projectWithInputs } from "./fixtures/inputs";

test("external values are blinded until the MAP is signed, and revealed for a check with a reason", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Blindamide", [
    { study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }, { study_id: "po-10", route: "oral", dose_mg: 10 },
    { study_id: "po-50", route: "oral", dose_mg: 50 }, { study_id: "po-100", route: "oral", dose_mg: 100 },
  ]);
  await page.goto(`/projects/${projectId}/plan`);
  const panel = page.getByTestId("blinding");
  await expect(panel).toContainText("Off");
  await panel.getByPlaceholder("reason (MIDD lead)").fill("ICH M15 §4.1: the plan is fixed before the external data are seen");
  await panel.getByTestId("blinding-toggle").click();
  await expect(panel).toContainText(/On — \d+ external stud/);

  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  const blinded = page.locator("[data-testid^='blinded-']").first();
  // why, in the words every withheld study is said in (round 5: "blinded until the MAP is signed" said nothing of why)
  await expect(blinded).toContainText("Its values are blinded until the plan is signed, because the plan places it in S5 (external validation)");
  const testId = (await blinded.getAttribute("data-testid"))!;
  const card = page.getByTestId(testId.replace("blinded-", "dataset-"));
  // no values on the page: what the dataset holds is said (its analyte, its series' statistic: final review round 6, so
  // two datasets of a study read apart), never a series' points
  await expect(card.locator(".series")).toHaveCount(0);
  await expect(card).not.toContainText("35");
  await blinded.getByPlaceholder("why it must be seen now (required)").fill("check the transcription against the table");
  await blinded.getByRole("button", { name: "Reveal for this check" }).click();
  await expect(page.getByTestId(testId)).toHaveCount(0);
  await expect(card.locator(".series").first()).toBeVisible();              // revealed for this check only
  await expect(card).toContainText("35");
  await page.screenshot({ path: test.info().outputPath("blinding.png"), fullPage: true });
});
