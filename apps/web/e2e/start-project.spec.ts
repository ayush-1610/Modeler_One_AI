// One way in (plan 2026-11-27 step 1; the owner's D1, D2): a project starts from its proposal, read for the brief, and the
// client's file, which goes to the Data room untagged; its run starts at once and the person lands on it. Nothing is
// approved anywhere (D-27). Then Start, a value typed into its row on Inputs, and the history, opened from the Projects
// page (page review 1). Agents are off in this run (no provider key), so the brief starts from the drug name.
import { expect, test } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

const PROPOSAL = [
  "# Technical proposal TP-E2E: PBPK model of dapagliflozin",
  "Objective: predict exposure after a single oral dose of 10 mg in healthy adults.",
  "The client will provide the dissolution profiles in three media.",
].join("\n");
const CLIENT_CSV = "study_id,time_h,conc_ng_ml\nEX-101,1,30.4\n";

test("a project starts from its proposal and the client's file; the file goes to the Data room and its run starts",
  async ({ page, request }) => {
  await page.goto("/projects/start");
  await page.getByTestId("drug-name").fill("Dapagliflozin");
  await page.getByTestId("proposal-files").setInputFiles([                            // one drop zone for everything
    { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) },
    { name: "client-pk.csv", mimeType: "text/csv", buffer: Buffer.from(CLIENT_CSV) },
  ]);
  await expect(page.getByTestId("mark-proposal-proposal.md")).toBeChecked();          // named like the proposal
  await expect(page.getByTestId("mark-proposal-client-pk.csv")).not.toBeChecked();
  await expect(page.getByTestId("start-files-split")).toHaveText("1 read for the brief · 1 to the Data room");
  await expect(page.locator("select")).toHaveCount(0);                                // no tag is asked (D2)
  await page.screenshot({ path: test.info().outputPath("start-from-proposal.png"), fullPage: true });
  await page.getByTestId("start-project").click();

  // the Data room, its run started by itself (D1): the person watches the files read
  await page.waitForURL(/\/projects\/[^/]+\/dataroom$/);
  await expect(page.getByTestId("run-progress")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("start-lands-on-the-data-room.png"), fullPage: true });
  const startUrl = page.url().replace(/\/dataroom$/, "/start");
  await page.goto(startUrl);
  await expect(page.getByTestId("start-drug-name")).toHaveText("Dapagliflozin");
  await expect(page.getByTestId("start-files")).toContainText("proposal.md");          // the proposal, read for the brief
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "needs_you");
  await expect(page.getByRole("button", { name: /approve/i })).toHaveCount(0);
  const projectId = /\/projects\/([^/]+)\/start$/.exec(startUrl)![1];

  // Inputs comes after Start (page review 1, decision 7): reached by its address, it says what Start still needs
  await page.goto(startUrl.replace(/\/start$/, "/inputs"));
  await expect(page.getByTestId("inputs-blocked")).toContainText("Inputs come after Start");
  await expect(page.getByTestId("add-open-bind.fu")).toHaveCount(0);
  await finishStart(request, projectId);
  await page.reload();
  await expect(page.getByTestId("inputs-blocked")).toHaveCount(0);

  // a value typed into its row on Inputs, with its source: converted and graded by code, and in the model with nothing
  // to accept (D-27); the page opens on To do while something is missing, the row is on Compound
  await page.getByTestId("tab-compound").click();
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
  await page.goto("/projects");                                                       // the Projects table, the record view
  await page.getByTestId(`project-history-${projectId}`).click();
  await page.waitForURL(/\/history$/);
  await expect(page.getByText("hash chain verifies")).toBeVisible();           // in the header, on every tab
  await page.getByTestId("history-tab-versions").click();                     // the versions (slice 7)
  await expect(page.getByText("brief/main").first()).toBeVisible();
});

test("one drop zone: the proposal is marked with one click when its name does not say so, and a ZIP is never it",
  async ({ page }) => {
    await page.goto("/projects/start");
    await page.getByTestId("drug-name").fill("Dapagliflozin");
    await page.getByTestId("proposal-files").setInputFiles([
      { name: "TP-2026-114.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) },
      { name: "delivery.zip", mimeType: "application/zip", buffer: Buffer.from("PK\u0005\u0006" + "\u0000".repeat(18)) },
    ]);
    await expect(page.getByTestId("start-project")).toBeDisabled();
    await expect(page.getByTestId("start-where")).toHaveText("Mark the technical proposal, or describe the project in Context.");
    await expect(page.getByTestId("mark-proposal-delivery.zip")).toHaveCount(0);       // a ZIP is the client's files
    await page.getByTestId("mark-proposal-TP-2026-114.md").click();
    await expect(page.getByTestId("start-files-split")).toHaveText("1 read for the brief · 1 to the Data room");
    await expect(page.getByTestId("start-project")).toBeEnabled();
  });
