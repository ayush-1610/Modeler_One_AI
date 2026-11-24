// A viewer opens Review & sign (redesign review R-S03): the page reads the plan through `plan:view`, a reader's route,
// instead of `GET /plan`, which is a writer's and answered a viewer with 403; and it offers no signature. The DEV
// sign-in holds every role, so the browser is given a viewer's answer to `/api/v1/me`, the API's own word on the roles
// the page reads; the plan routes themselves are the real API's.
import { expect, test } from "@playwright/test";

import { projectWithInputs } from "./fixtures/inputs";

test("a viewer reads the model plan and is offered no signature", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Viewamide", [
    { study_id: "iv-250", route: "iv_infusion", dose_mg: 250 }, { study_id: "po-50", route: "oral", dose_mg: 50 },
  ]);
  // a curator opens the page first: GET /plan makes the MS-01 default plan
  await page.goto(`/projects/${projectId}/plan`);
  await expect(page.getByTestId("node-S1")).toContainText("iv-250");

  await page.route("**/api/v1/me", async (route) => {
    const real = await (await route.fetch()).json();
    await route.fulfill({ json: { ...real, data: { ...real.data, roles: ["modeler-viewer"], admin: false } } });
  });
  const reads: string[] = [];
  page.on("request", (r) => { if (/\/api\/v1\/projects\/[^/]+\/plan(:view)?(\?|$)/.test(r.url())) reads.push(new URL(r.url()).pathname); });
  await page.goto(`/projects/${projectId}/plan`);

  await expect(page.getByTestId("plan-read-only")).toContainText("You can read this plan");
  await expect(page.getByTestId("node-S1")).toContainText("iv-250");        // the plan itself, read
  await expect(page.getByTestId("approve-and-sign")).toHaveCount(0);        // no signature offered
  // every tab reads the plan and offers no control that would only be refused (the console redesign's slice 5)
  await expect(page.getByTestId("overall-data").getByTestId("chip-po-50")).toHaveAttribute("draggable", "false");
  await expect(page.getByTestId("review-studies")).toBeVisible();
  await expect(page.locator("[data-testid^='leave-out-'], [data-testid^='unlock-']")).toHaveCount(0);
  await expect(page.getByTestId("blinding-toggle")).toHaveCount(0);
  await page.getByTestId("review-tab-inputs").click();
  await expect(page.getByTestId("review-table")).toBeVisible();
  await expect(page.locator("[data-testid^='exclude-']")).toHaveCount(0);
  await page.getByTestId("review-tab-estimation").click();
  await expect(page.getByTestId("estimation-plan")).toBeVisible();
  await expect(page.locator("[data-testid^='estimate-'], [data-testid^='fix-'], [data-testid='group-add']")).toHaveCount(0);
  await page.getByTestId("review-tab-credibility").click();
  await expect(page.getByTestId("risk-and-budget")).toContainText("Time budget");
  await expect(page.getByTestId("risk-and-budget").locator("select, input, button")).toHaveCount(0);
  await expect(page.getByTestId("target-save")).toHaveCount(0);
  await page.getByTestId("review-tab-validator").click();
  await expect(page.getByTestId("validator")).toBeVisible();
  await expect(page.getByTestId("validator").getByRole("button")).toHaveCount(0);
  await expect(page).toHaveURL(/\/plan\?tab=validator$/);
  expect(reads.length).toBeGreaterThan(0);
  expect(reads.every((p) => p.endsWith("/plan:view"))).toBe(true);           // never the writer's GET /plan
});
