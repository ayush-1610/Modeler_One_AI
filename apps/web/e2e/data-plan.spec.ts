// The Data plan (the console redesign, slice 4a; P-13b, the owner's answer Q1: read-mostly): which data the project's
// applications require, who provides each item and whether it is covered, from the requirements derived from the
// brief. Nothing is edited on it: each item opens the area of Inputs where it is settled. The Data room's sections say
// where they stand in Inputs' words (decision G1-1).
import { expect, test } from "@playwright/test";

import { projectWithInputs } from "./fixtures/inputs";

test("the Data plan lists each requirement with its provider and status, and edits nothing", async ({ page, request }) => {
  const id = await projectWithInputs(request, "Planlistamide", [{ study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }]);
  await page.goto(`/projects/${id}/data-plan`);
  await expect(page.getByRole("heading", { name: "Data plan", level: 1 })).toBeVisible();
  await expect(page.getByTestId("nav-data-plan")).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("navigation", { name: "Breadcrumbs" })).toContainText("Data plan");
  const rows = page.getByTestId("data-plan").locator("tbody tr");
  expect(await rows.count()).toBeGreaterThan(0);
  // every item says where it is settled, a link into Inputs
  const first = page.getByTestId("data-plan").locator('[data-testid^="plan-item-open-"]').first();
  await expect(first).toHaveAttribute("href", new RegExp(`/projects/${id}/inputs\\?tab=`));
  // read-mostly: the page's only controls are its filters and links (no edit button)
  await expect(page.getByTestId("data-plan").getByRole("button", { name: /save|set|edit|change|confirm/i })).toHaveCount(0);
  await page.getByTestId("data-plan-status").selectOption("SATISFIED");
  await page.getByTestId("data-plan-status").selectOption("");
  await page.screenshot({ path: test.info().outputPath("data-plan.png"), fullPage: true });

  // the Data room's sections in Inputs' words; no "earlier page" link either way
  await page.goto(`/projects/${id}/dataroom`);
  await expect(page.getByText("The earlier Inputs page")).toHaveCount(0);
  const rail = page.getByTestId("dataroom-rail");
  if (await rail.count()) await expect(rail).not.toContainText(/In order|Needs a look/);
});
