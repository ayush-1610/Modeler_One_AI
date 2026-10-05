// The create-project flow a user runs: start from a published model, load its CPF and real studies, generate and
// sign the MAP, start the campaign and watch it on the monitor. Plus the two failure modes that used to be hidden
// behind sample data: an API that does not answer, and a campaign that is not recorded (yet).
import { expect, test } from "@playwright/test";

const TERMINAL = /completed|escalated|awaiting_signature|aborted|failed/;

test("a new project from the published Dapagliflozin model runs from the wizard to the monitor", async ({ page }) => {
  await page.goto("/projects/new");

  await page.getByTestId("template-dapagliflozin-osp").click();
  await expect(page.getByTestId("project-name")).toHaveValue(/^Dapagliflozin /);
  await page.getByTestId("create-project").click();

  // The CPF is the published model's: its fitted UGT1A9 clearance is on the page, not a made-up value.
  await expect(page.getByText("elim.hepatic.UGT1A9.clspec", { exact: true })).toBeVisible();
  await page.getByTestId("save-cpf").click();

  // 40 real clinical studies, each traceable to its publication.
  await expect(page.getByRole("heading", { name: "3 · Observed studies (40)" })).toBeVisible();
  await expect(page.getByText("boulton-2013-14c-dapagliflozin-iv", { exact: true })).toBeVisible();
  await page.getByTestId("upload-studies").click();

  await page.getByTestId("generate-map").click();
  await expect(page.getByTestId("map-ready")).toContainText("S0 → S1 → S2 → S3 → S4 → S5 → S6 → S7");
  await page.getByTestId("sign-and-start").click();

  await page.waitForURL(/\/campaigns\/[^/]+$/);
  await expect(page.getByTestId("api-problem")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Dapagliflozin" })).toBeVisible({ timeout: 60_000 });

  // The monitor refreshes itself; wait for the campaign to finish or stop for a human decision.
  await expect(page.locator(".spread .chip").first()).toHaveText(TERMINAL, { timeout: 8 * 60_000 });
  await expect(page.locator(".stage").first()).toContainText("S0");
  await expect(page.locator(".stage").first()).toContainText("passed");
  await page.screenshot({ path: test.info().outputPath("monitor.png"), fullPage: true });
  // What produced the numbers is on the page: a stub run is flagged, a PK-Sim run is not.
  if (process.env.E2E_ENGINE_COMMAND) await expect(page.getByTestId("engine-warning")).toHaveCount(0);
  else await expect(page.getByTestId("engine-warning")).toContainText("Not a PBPK result");

  // The project is listed on the home page, from the API.
  await page.goto("/");
  await expect(page.getByRole("link", { name: /^Dapagliflozin / }).first()).toBeVisible();
});

test("the wizard says the API did not answer instead of failing silently", async ({ page }) => {
  await page.route("**/api/v1/projects", (route) =>
    route.fulfill({ status: 502, contentType: "text/html", body: "<html>Bad Gateway</html>" }));
  await page.goto("/projects/new");
  await page.getByTestId("template-aciclovir-illustrative").click();
  await page.getByTestId("create-project").click();
  await expect(page.getByTestId("wizard-error")).toContainText("The API did not answer (HTTP 502)");
});

test("the wizard shows the API's own reason when it refuses a step", async ({ page }) => {
  await page.goto("/projects/new");
  await page.getByTestId("template-aciclovir-illustrative").click();
  await page.getByTestId("create-project").click();
  await page.getByTestId("save-cpf").click();
  // An empty study list is refused by the API (422); the refusal must reach the user, not vanish.
  await page.getByText("Edit as JSON").click();
  await page.locator("details textarea").fill("[]");
  await page.getByTestId("upload-studies").click();
  await expect(page.getByTestId("wizard-error")).toContainText("studies");
});

test("a campaign that is not recorded says so and never shows sample data", async ({ page }) => {
  await page.goto("/campaigns/does-not-exist");
  await expect(page.getByTestId("campaign-pending")).toBeVisible();
  await expect(page.getByText("sample data")).toHaveCount(0);
});
