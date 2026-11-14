// The platform owner's console (docs/plans/2026-11-10-admin-console.md) is for the realm role modeler-admin only. The
// development sign-in does not hold it, so it sees no link to the console and, at every console address, the app's own
// 404 — not the console's head, its tabs or a refusal naming the role — so the console is not disclosed. The API's 403
// is unchanged and is checked in services/api/tests/test_admin_api.py, with the console's own answers.
// (Changed 2026-11-11, audit item 12: this test used to expect the "platform's owner only" refusal card, which is gone.)
import { expect, test } from "@playwright/test";

test("a person who is not the platform's owner gets no console link and finds no page at its address", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("dash-new-project")).toBeVisible();
  await expect(page.getByTestId("signed-in").or(page.getByTestId("dev-sign-in"))).toBeVisible();
  await expect(page.getByTestId("nav-admin")).toHaveCount(0);

  for (const address of ["/admin", "/admin/usage", "/admin/companies/dev-tenant", "/admin/limits", "/admin/people", "/admin/models", "/admin/keys",
                         "/admin/pipeline"]) {
    await page.goto(address);
    // The page's content, not response.status(): the root loading boundary streams, so a 404 may arrive as HTTP 200.
    await expect(page.getByTestId("page-not-found")).toContainText("There is no page here");
    await expect(page.getByTestId("admin-hero")).toHaveCount(0);
    await expect(page.getByTestId("admin-tabs")).toHaveCount(0);
    await expect(page.getByText("Admin console")).toHaveCount(0);
    await expect(page.getByTestId("admin-companies")).toHaveCount(0);
    await expect(page.getByTestId("usage-runs")).toHaveCount(0);
    await expect(page.getByTestId("admin-keys")).toHaveCount(0);
    await expect(page.getByTestId("admin-agents")).toHaveCount(0);
    await expect(page.getByTestId("admin-limits")).toHaveCount(0);
    await expect(page.getByTestId("limit-warnings")).toHaveCount(0);
    await expect(page.getByTestId("pipeline-health")).toHaveCount(0);
  }
});
