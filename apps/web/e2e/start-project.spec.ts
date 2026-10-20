// One upload (map rows p0-files, p3-upload): a project starts from its proposal and the client's file, and lands on
// Start with the viewer on the proposal. The checklist's provider is changed in place, the full brief takes an edit with
// no "why", and nothing is approved anywhere (D-27). Then the P2 manual path and the history. Agents are off in this run
// (no provider key), so the brief starts from the drug name: the manual path.
import { expect, test } from "@playwright/test";

const PROPOSAL = [
  "# Technical proposal TP-E2E: PBPK model of dapagliflozin",
  "Objective: predict exposure after a single oral dose of 10 mg in healthy adults.",
  "The client will provide the dissolution profiles in three media.",
].join("\n");
// stored by content hash, this file sorts before the proposal: the viewer must still open on the proposal
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
  await expect(page.getByTestId("start-title")).toHaveText("Dapagliflozin");
  await expect(page.locator(".doc-page")).toContainText("single oral dose of 10 mg");
  // the project's own background reading (PubChem, the structure check) ends before the flow goes on
  await expect(page.getByTestId("start-read")).toHaveText("Read the documents again", { timeout: 120_000 });
  await expect(page.getByTestId("start-files")).toContainText("client-pk.csv");
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "needs_you");
  await expect(page.getByRole("button", { name: /approve/i })).toHaveCount(0);
  await page.getByTestId("provider-REQ-phys.logp").selectOption("CLIENT");
  await expect(page.getByTestId("cross-check-REQ-phys.logp")).toBeVisible();

  // the full brief keeps every field: an edit with no "why", and nothing to approve
  const startUrl = page.url();
  await page.goto(startUrl.replace(/\/start$/, "/brief"));
  await expect(page.getByTestId("brief-title")).toHaveText("Project Brief · Dapagliflozin");
  await expect(page.getByRole("button", { name: /approve/i })).toHaveCount(0);
  await expect(page.getByTestId("tab-data-plan")).toHaveCount(0);
  await page.getByTestId("edit-proj.title").click();
  await page.getByTestId("field-editor").locator("input[type=text]").first().fill("Dapagliflozin food-effect PBPK");
  await page.getByTestId("edit-save").click();
  await expect(page.getByTestId("field-proj.title")).toContainText("Dapagliflozin food-effect PBPK");
  await expect(page.getByTestId("field-proj.title")).toContainText("edited");
  await page.screenshot({ path: test.info().outputPath("brief.png"), fullPage: true });
  const briefUrl = page.url();

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
