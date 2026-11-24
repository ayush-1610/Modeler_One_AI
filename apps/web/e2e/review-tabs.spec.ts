// Review & sign in the console (the redesign's slice 5, P-14): one part of the review at a time, the tab in the address
// (a reload or a shared link opens it; an old link to a section, #review-…, opens its tab), the keyboard moving between
// tabs; and a study a person placed given back to the MS-01 default (`:unlock`), its dry run saying first what that
// changes. Software test data only: nothing here is a simulation.
import { expect, test } from "@playwright/test";

import { AUTH, projectWithInputs } from "./fixtures/inputs";

test("one tab at a time in the address, and a placed study back to the MS-01 default", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Tabamide", [
    { study_id: "iv-250", route: "iv_infusion", dose_mg: 250 }, { study_id: "po-10", route: "oral", dose_mg: 10 },
    { study_id: "po-50", route: "oral", dose_mg: 50 },
  ]);
  const api = `/api/v1/projects/${projectId}`;
  expect((await request.get(`${api}/plan`, { headers: AUTH })).ok()).toBeTruthy();                  // built on first read
  const moved = await request.put(`${api}/plan/placements/po-50`, { headers: AUTH,
    data: { role: "SUPPORTIVE", reason: "kept as context while its assay is checked" } });
  expect(moved.ok(), await moved.text()).toBeTruthy();

  // the tab from the address; the others are not drawn
  await page.goto(`/projects/${projectId}/plan?tab=credibility`);
  await expect(page.getByTestId("review-tab-credibility")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("credibility")).toBeVisible();
  await expect(page.getByTestId("overall-data")).toHaveCount(0);
  await expect(page.getByTestId("plan-signature")).toBeVisible();              // the signature stays above every tab
  // the arrow keys move between tabs, and the address follows
  await page.getByTestId("review-tab-credibility").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("review-tab-validator")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("review-tab-validator")).toBeFocused();
  await expect(page).toHaveURL(/\/plan\?tab=validator$/);
  await expect(page.getByTestId("diff-po-50")).toContainText("kept as context while its assay is checked");
  // an old link to a section opens its tab
  await page.goto(`/projects/${projectId}/plan#review-validator`);
  await expect(page.getByTestId("review-tab-validator")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("diff-po-50")).toBeVisible();

  // back to the MS-01 default, from the studies table: what it changes first, then put back
  await page.getByTestId("review-tab-studies").click();
  await expect(page.getByTestId("node-SUPPORTIVE")).toContainText("po-50");
  await expect(page.getByTestId("unlock-po-10")).toHaveCount(0);               // only a study a person placed offers it
  await page.getByTestId("unlock-po-50").click();
  const dialog = page.getByTestId("unlock-dialog");
  await expect(dialog.getByTestId("change-what")).toContainText("po-50 from supportive to S");
  await expect(dialog.getByTestId("unlock-deviation")).toHaveCount(0);         // no MAP is signed yet
  await page.screenshot({ path: test.info().outputPath("unlock.png") });
  await dialog.getByTestId("unlock-confirm").click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId("node-SUPPORTIVE")).not.toContainText("po-50");
  await expect(page.getByTestId("unlock-po-50")).toHaveCount(0);
  await page.getByTestId("review-tab-validator").click();
  await expect(page.getByTestId("diff-empty")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("review-tabs.png"), fullPage: true });
});
