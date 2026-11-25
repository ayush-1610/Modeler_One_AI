// The console shell (docs/plans/2026-11-23-console-redesign-implementation.md, slice 1; design-review/DESIGN_SYSTEM.md
// §4, §7): on a desktop the side navigation is fixed and shows the project's steps; on a phone it is a menu the top bar
// opens. Every page's heading, names, width and target sizes are checked by acceptance.spec.ts (slice 10), at 1440 and
// 390 px, with the helpers of fixtures/a11y.ts this spec used to hold.
import { expect, test } from "@playwright/test";

import { projectWithInputs } from "./fixtures/inputs";

test("the shell: fixed navigation with the project's steps on a desktop, a menu on a phone", async ({ page, request }) => {
  const id = await projectWithInputs(request, "Shellamide", [{ study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }]);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${id}/inputs`);
  const steps = page.getByRole("navigation", { name: "Project steps" });
  await expect(steps).toBeVisible();
  await expect(steps.getByTestId("step-start")).toHaveAttribute("data-state", /done|needs_you|running|not_started/);
  await expect(page.getByTestId("nav-inputs")).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("navigation", { name: "Breadcrumbs" })).toContainText("Inputs");
  await expect(page.getByTestId("nav-menu")).toBeHidden();                      // no menu button on a desktop
  await page.screenshot({ path: test.info().outputPath("shell-desktop.png") });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByTestId("sidebar")).toBeHidden();                       // closed until asked for
  await page.getByTestId("nav-menu").click();
  await expect(page.getByTestId("nav-menu")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("nav-library")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("shell-phone-menu.png") });
  await page.getByTestId("nav-library").click();                               // a choice closes the menu
  await page.waitForURL(/\/library$/);
  await expect(page.getByTestId("sidebar")).toBeHidden();
});
