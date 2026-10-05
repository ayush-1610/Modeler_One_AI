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

  // The data plan is derived from the brief (a draft until the brief is approved), with the feasibility beside it.
  const briefUrl = page.url();
  await page.getByTestId("tab-data-plan").click();
  await page.getByRole("button", { name: "Derive from the brief" }).click();
  await expect(page.getByTestId("req-REQ-phys.logp")).toContainText("Lipophilicity");
  await expect(page.getByRole("button", { name: "Approve data plan" })).toBeDisabled();
  await page.getByTestId("tab-feasibility").click();
  await expect(page.getByTestId("feasibility")).toContainText("undetermined");

  // P2, manual path: a value entered with its source, graded by code, accepted with a reason.
  await page.goto(briefUrl.replace(/\/brief.*$/, "/evidence"));
  await expect(page.getByTestId("coverage-REQ-bind.fu")).toHaveText("not found");
  const fu = page.locator(".card", { has: page.getByTestId("coverage-REQ-bind.fu") });
  await fu.getByRole("button", { name: "Add a value" }).click();
  await fu.getByPlaceholder("value", { exact: true }).fill("9");
  await fu.getByPlaceholder("unit as stated").fill("%");
  await fu.getByPlaceholder("DOI / PMID / URL").fill("10.1000/example-review");
  await fu.getByPlaceholder("conditions: species=human; method=equilibrium dialysis").fill("species=human; matrix=plasma; method=ED; drug concentration=1 µM");
  await fu.getByRole("button", { name: "Add value" }).click();
  await expect(fu.locator(".evidence")).toContainText("→ 0.09000");
  await fu.getByPlaceholder("reason (required)").fill("primary measurement");
  await fu.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByTestId("coverage-REQ-bind.fu")).toHaveText("accepted");

  await page.goto(briefUrl.replace(/\/brief.*$/, "/history"));
  await expect(page.getByText("brief/main").first()).toBeVisible();
  await expect(page.getByText("hash chain verifies")).toBeVisible();
});
