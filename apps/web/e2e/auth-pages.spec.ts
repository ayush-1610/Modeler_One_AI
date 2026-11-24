// The pages before and after the app and the person's account (the owner, 2026-11-24: "we need to work in login page,
// and see what all other pages we need to have"), with the DEV sign-in this suite runs on. With Keycloak, the same pages
// are proved end to end in oidc-signing.spec.ts.
import { expect, test } from "@playwright/test";

test("the sign-in, signed-out and account pages say where the person stands, without the app's sidebar", async ({ page }) => {
  await page.goto("/signin?return=/projects/start");
  await expect(page.getByTestId("signin-page")).toContainText("Development sign-in");
  await expect(page.getByTestId("signin-dev")).toContainText("not a Part 11 sign-in");
  await expect(page.getByTestId("sidebar")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("signin-dev.png"), fullPage: true });
  await page.getByTestId("signin-go").click();
  await expect(page).toHaveURL(/\/projects\/start$/);

  await page.goto("/signed-out");
  await expect(page.getByTestId("signed-out-page")).toContainText("You have signed out");
  await expect(page.getByTestId("sidebar")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("signed-out.png"), fullPage: true });

  // the account page is inside the app, reached from the person's name in the sidebar
  await page.goto("/");
  await page.getByTestId("nav-account").click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByTestId("account-roles")).toContainText("Curator: creates projects and changes your own");
  await expect(page.getByTestId("account-dev")).toContainText("development sign-in");
  await page.screenshot({ path: test.info().outputPath("account-dev.png"), fullPage: true });

  // no-access needs Keycloak: with the DEV sign-in (every role) it is never shown
  await page.goto("/no-access");
  await expect(page).not.toHaveURL(/\/no-access$/);
});

test("an address with no page says so and keeps the way back", async ({ page }) => {
  await page.goto("/projects/no-such-project/no-such-page");
  await expect(page.getByTestId("page-not-found")).toContainText("There is no page here");
  await expect(page.getByTestId("sidebar")).toBeVisible();
});

test("Help is the user guide, with the steps for the AI model keys", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("nav-help").click();
  await expect(page).toHaveURL(/\/help$/);
  await expect(page.getByTestId("help-toc")).toContainText("AI model keys, end to end");
  await page.getByTestId("help-toc").getByRole("link", { name: /AI model keys/ }).click();
  const keys = page.locator(`[id="6b-ai-model-keys-end-to-end-the-server-groqcloud-nvidia"]`);
  await expect(keys).toBeInViewport();
  await expect(page.getByTestId("help-body")).toContainText("Admin → Keys → Add a key");
  await page.screenshot({ path: test.info().outputPath("help.png") });
});

test("a project's settings hold where its files may go and who it is shared with", async ({ page, request }) => {
  const made = await request.post("/api/v1/projects", { headers: { Authorization: "Bearer dev" },
                                                        data: { name: "Settings Demo", compound: "Settamide" } });
  const projectId = (await made.json()).data.id as string;
  await page.goto(`/projects/${projectId}`);
  await page.getByTestId("nav-settings").click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/settings$`));
  await expect(page.getByTestId("files-go-said")).toContainText("In-house only");
  await expect(page.getByTestId("settings-members")).toBeVisible();          // who it is shared with; managed on Members
  await expect(page.getByTestId("settings-members-link")).toHaveAttribute("href", `/projects/${projectId}/members`);
  await page.screenshot({ path: test.info().outputPath("settings.png"), fullPage: true });
});
