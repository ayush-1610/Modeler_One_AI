// P3: a project's members on its page. With the DEV sign-in every project is open (its `*`), so the panel says
// memberships take effect under Keycloak; the creator is still recorded. oidc-signing.spec.ts adds a colleague.
import { expect, test } from "@playwright/test";

const AUTH = { Authorization: "Bearer dev" };

test("a new project lists its creator as its member", async ({ page, request }) => {
  const created = await request.post("/api/v1/projects", { headers: AUTH, data: { name: `Members ${Date.now()}`, compound: "Memberol" } });
  expect(created.ok()).toBeTruthy();
  const projectId = (await created.json()).data.id as string;

  await page.goto(`/projects/${projectId}`);
  const panel = page.getByTestId("members-panel");
  await expect(panel).toContainText("development sign-in opens every project");
  await expect(panel.getByTestId("member-dev-user")).toContainText("Dev User");
  await expect(panel.getByRole("button", { name: "Remove" })).toBeDisabled();  // a project keeps its last member
});
