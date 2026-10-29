// One upload (map rows p0-files, p3-upload): a project starts from its proposal and the client's file, and lands on
// Start with both files listed and nothing approved anywhere (D-27). Then a value typed into its row on Inputs, and the
// history, opened from the Projects page (page review 1). Agents are off in this run (no provider key), so the brief starts
// from the drug name: the manual path.
import { expect, test } from "@playwright/test";

const PROPOSAL = [
  "# Technical proposal TP-E2E: PBPK model of dapagliflozin",
  "Objective: predict exposure after a single oral dose of 10 mg in healthy adults.",
  "The client will provide the dissolution profiles in three media.",
].join("\n");
const CLIENT_CSV = "study_id,time_h,conc_ng_ml\nEX-101,1,30.4\n";

test("a project starts from its proposal and the client's file in one upload, with no approval", async ({ page }) => {
  await page.goto("/projects/start");
  await page.getByTestId("drug-name").fill("Dapagliflozin");
  await page.getByTestId("proposal-files").setInputFiles([
    { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) },
    { name: "client-pk.csv", mimeType: "text/csv", buffer: Buffer.from(CLIENT_CSV) },
  ]);
  await expect(page.getByLabel("What client-pk.csv is")).toHaveValue("client");
  await page.getByTestId("start-project").click();

  await page.waitForURL(/\/projects\/[^/]+\/start$/);
  await expect(page.getByTestId("start-drug-name")).toHaveText("Dapagliflozin");
  await expect(page.getByTestId("start-files")).toContainText("proposal.md");
  await expect(page.getByTestId("start-files")).toContainText("client-pk.csv");
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "needs_you");
  await expect(page.getByRole("button", { name: /approve/i })).toHaveCount(0);
  const startUrl = page.url();
  const projectId = /\/projects\/([^/]+)\/start$/.exec(startUrl)![1];

  // a value typed into its row on Inputs, with its source: converted and graded by code, and in the model with nothing
  // to accept (D-27)
  await page.goto(startUrl.replace(/\/start$/, "/inputs"));
  await page.getByTestId("add-open-bind.fu").click();
  const fu = page.getByTestId("add-bind.fu");
  await fu.getByLabel("value for bind.fu").fill("9");
  await fu.getByLabel("unit for bind.fu").fill("%");
  await fu.getByLabel("source type for bind.fu").selectOption("REGULATORY_REVIEW");
  await fu.getByLabel("link for bind.fu").fill("10.1000/example-review");
  await fu.getByRole("button", { name: "Add" }).click();
  await expect(page.getByTestId("record-bind.fu")).toContainText("0.09");
  await expect(page.getByRole("button", { name: /^accept/i })).toHaveCount(0);

  // the history is opened from the Projects page (page review 1), no longer from the step bar
  await page.goto("/");
  await page.getByTestId(`project-history-${projectId}`).click();
  await page.waitForURL(/\/history$/);
  await expect(page.getByText("brief/main").first()).toBeVisible();
  await expect(page.getByText("hash chain verifies")).toBeVisible();
});
