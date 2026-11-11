// The platform owner's console (docs/plans/2026-11-10-admin-console.md) is for the realm role modeler-admin only. The
// development sign-in does not hold it, so it sees no link to the console and, at its address, the API's refusal
// shown as such, never the companies' data. (The console's own answers are checked in services/api/tests/test_admin_api.py.)
import { expect, test } from "@playwright/test";

test("a person who is not the platform's owner gets no console link and is refused at its address", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("dash-new-project")).toBeVisible();
  await expect(page.getByTestId("signed-in").or(page.getByTestId("dev-sign-in"))).toBeVisible();
  await expect(page.getByTestId("nav-admin")).toHaveCount(0);

  for (const address of ["/admin", "/admin/usage", "/admin/companies/dev-tenant", "/admin/limits", "/admin/models", "/admin/keys"]) {
    await page.goto(address);
    await expect(page.getByTestId("admin-refused")).toContainText("platform's owner only");
    await expect(page.getByTestId("admin-companies")).toHaveCount(0);
    await expect(page.getByTestId("usage-runs")).toHaveCount(0);
    await expect(page.getByTestId("admin-keys")).toHaveCount(0);
    await expect(page.getByTestId("admin-agents")).toHaveCount(0);
    await expect(page.getByTestId("admin-limits")).toHaveCount(0);
    await expect(page.getByTestId("limit-warnings")).toHaveCount(0);
  }
});
