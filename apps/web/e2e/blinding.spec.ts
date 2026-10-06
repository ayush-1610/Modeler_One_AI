// D-15: with blinding on, an external study's values are withheld on the evidence page until the MAP is signed; a
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

  await page.goto(`/projects/${projectId}/evidence?tab=observed`);
  const blinded = page.locator("[data-testid^='blinded-']").first();
  await expect(blinded).toContainText("blinded until the MAP is signed");
  const testId = (await blinded.getAttribute("data-testid"))!;
  const card = page.getByTestId(testId.replace("blinded-", "dataset-"));
  await expect(card).not.toContainText("arithmetic mean");                  // no values on the page
  await blinded.getByPlaceholder("why it must be seen now (required)").fill("check the transcription against the table");
  await blinded.getByRole("button", { name: "Reveal for this check" }).click();
  await expect(page.getByTestId(testId)).toHaveCount(0);
  await expect(card).toContainText("arithmetic mean");                       // revealed for this check only
  await expect(card).toContainText("35");
  await page.screenshot({ path: test.info().outputPath("blinding.png"), fullPage: true });
});
