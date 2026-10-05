// P0 → P1: start a project from a technical proposal, land on the brief, edit a field with a reason. Agents are off in
// this run (no provider key), so the brief starts from the drug name and is filled by hand: the manual path.
import { expect, test } from "@playwright/test";

const PROPOSAL = [
  "# Technical proposal TP-E2E: PBPK model of dapagliflozin",
  "Objective: predict exposure after a single oral dose of 10 mg in healthy adults.",
  "The client will provide the dissolution profiles in three media.",
].join("\n");

test("a project starts from its technical proposal and the brief is edited with a reason", async ({ page }) => {
  await page.goto("/projects/start");
  await page.getByTestId("drug-name").fill("Dapagliflozin");
  await page.getByTestId("proposal-files").setInputFiles({
    name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL),
  });
  await page.getByTestId("start-project").click();

  await page.waitForURL(/\/projects\/[^/]+\/brief$/);
  await expect(page.getByTestId("brief-title")).toHaveText("Project Brief · Dapagliflozin");
  await expect(page.getByTestId("phase-rail")).toBeVisible();
  await expect(page.locator(".doc-page")).toContainText("single oral dose of 10 mg");
  await expect(page.getByTestId("field-drug.name")).toContainText("entered");

  await page.getByTestId("edit-proj.title").click();
  await page.getByTestId("field-editor").locator("input[type=text]").first().fill("Dapagliflozin food-effect PBPK");
  await page.getByTestId("edit-note").fill("title from the proposal header");
  await page.getByTestId("edit-save").click();
  await expect(page.getByTestId("field-proj.title")).toContainText("Dapagliflozin food-effect PBPK");
  await expect(page.getByTestId("field-proj.title")).toContainText("edited");
  await expect(page.getByTestId("brief-version")).toContainText("title from the proposal header");
  await page.screenshot({ path: test.info().outputPath("brief.png"), fullPage: true });

  await page.goto(page.url().replace(/\/brief$/, "/history"));
  await expect(page.getByText("brief/main").first()).toBeVisible();
  await expect(page.getByText("hash chain verifies")).toBeVisible();
});
