// T-50: the P5 canvas. The plan starts as the MS-01 default; a dataset dragged onto a D3 node is checked by the
// validator before the person gives the reason; a rule-breaking move blocks the signature; warnings are acknowledged;
// the MAP is generated from the plan, signed, and the campaign starts from it.
import { expect, test } from "@playwright/test";

import { projectWithInputs } from "./fixtures/inputs";

// The canvas is large: a drag whose target is below the fold makes Playwright scroll mid-drag, and Chromium then
// starts no HTML5 drag at all. A desktop-sized viewport keeps source and target on screen, as for a person.
test.use({ viewport: { width: 1600, height: 1200 } });

test("the plan canvas: drag and drop with reasons, the live validator, approve and sign, run", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Planamide", [
    { study_id: "iv-250", route: "iv_infusion", dose_mg: 250 }, { study_id: "iv-500", route: "iv_infusion", dose_mg: 500 },
    { study_id: "po-10", route: "oral", dose_mg: 10 }, { study_id: "po-50", route: "oral", dose_mg: 50 },
    { study_id: "po-100", route: "oral", dose_mg: 100 }, { study_id: "ddi-itra", route: "oral", dose_mg: 50, co_medication: "itraconazole" },
  ]);
  await page.goto(`/projects/${projectId}/plan`);
  await expect(page.getByTestId("overall-data")).toContainText("Overall Data");
  await expect(page.getByTestId("node-S1")).toContainText("iv-250");          // the MS-01 default
  await expect(page.getByTestId("node-SUPPORTIVE")).toContainText("ddi-itra");
  await expect(page.getByTestId("diff-empty")).toBeVisible();

  // a DDI study dropped on S2 breaks MS-01 rule 4: the validator says so before anything is saved
  await page.getByTestId("overall-data").getByTestId("chip-ddi-itra").dragTo(page.getByTestId("node-S2"));
  await expect(page.getByTestId("move-errors")).toContainText("rule 4");
  await page.getByRole("button", { name: "Cancel" }).click();

  // a valid move, onto the arrow leading into S5, with its reason
  await page.getByTestId("overall-data").getByTestId("chip-po-10").dragTo(page.getByTestId("edge-S4-S5"));
  await expect(page.getByTestId("move-ok")).toBeVisible();
  await page.getByTestId("move-reason").fill("the low dose is kept to validate the dose range externally");
  await page.getByTestId("move-confirm").click();
  await expect(page.getByTestId("node-S5")).toContainText("po-10");
  await expect(page.getByTestId("diff-po-10")).toContainText("the low dose is kept");
  await expect(page.getByTestId("node-S5").getByTestId("chip-po-10")).toContainText("🔒");

  // D1: the renal pathway's parameter is freed in S1 within bounds, with the reason (a person's choice, locked)
  await page.getByRole("button", { name: "D1 · disposition" }).click();
  await expect(page.getByTestId("pathway-GlomerularFiltration")).toBeVisible();
  await page.getByTestId("fit-elim.renal.gfr_fraction").click();
  const form = page.getByTestId("fit-form-elim.renal.gfr_fraction");
  await form.getByPlaceholder("why (required)").fill("the renal share of clearance is uncertain");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("param-elim.renal.gfr_fraction")).toContainText("fitted in S1");
  await expect(page.getByTestId("diff-elim.renal.gfr_fraction")).toContainText("renal share");
  await page.getByRole("button", { name: "D3 · development and validation" }).click();
  await expect(page.getByTestId("node-S1")).toContainText("elim.renal.gfr_fraction");

  // warnings are acknowledged with a reason; then the validator is green and Approve and Sign is enabled
  const sign = page.getByTestId("approve-and-sign");
  for (let i = 0; i < 6 && !(await page.getByTestId("validator-green").isVisible()); i++) {
    const warning = page.locator("[data-testid^='violation-']").first();
    await warning.getByPlaceholder("accept it because…").fill("an accepted limitation of this test project");
    await warning.getByRole("button", { name: "Acknowledge" }).click();
    await page.waitForTimeout(300);
  }
  await expect(page.getByTestId("validator-green")).toBeVisible();
  await expect(sign).toBeEnabled();
  await page.screenshot({ path: test.info().outputPath("plan.png"), fullPage: true });
  await sign.click();
  await expect(page.getByTestId("map-signed")).toContainText("MAP v1 signed");

  // D-14: after the signature a move is a MAP deviation — recorded, then signed into MAP v2, before the run
  await page.getByTestId("overall-data").getByTestId("chip-po-10").dragTo(page.getByTestId("node-S2"));
  await expect(page.getByTestId("move-ok")).toBeVisible();
  await expect(page.getByTestId("move-deviation")).toContainText("MAP deviation");
  await page.getByTestId("move-reason").fill("the external dose range is covered by po-50; po-10 trains absorption");
  await page.getByTestId("move-confirm").click();
  await expect(page.getByTestId("deviations-pending")).toContainText("po-10");
  await expect(page.getByTestId("run-campaign")).toHaveCount(0);           // nothing runs on an unsigned deviation
  await expect(sign).toHaveText("Sign the deviation (1)");
  await sign.click();
  await expect(page.getByTestId("map-signed")).toContainText("MAP v2 signed");
  await expect(page.getByTestId("map-signed")).toContainText("supersedes");
  await page.getByTestId("run-campaign").click();
  await page.waitForURL(/\/campaigns\/[^/]+$/);
  await expect(page.getByRole("heading", { name: "Planamide" })).toBeVisible({ timeout: 60_000 });
});
