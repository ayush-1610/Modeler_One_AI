// One upload (map rows p0-files, p3-upload): a project starts from its proposal and the client's file, and lands on
// Start with both files listed and nothing approved anywhere (D-27). Then a value typed into its row on Inputs, and the
// history, opened from the Projects page (page review 1). Agents are off in this run (no provider key), so the brief starts
// from the drug name: the manual path.
import { expect, test } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

const PROPOSAL = [
  "# Technical proposal TP-E2E: PBPK model of dapagliflozin",
  "Objective: predict exposure after a single oral dose of 10 mg in healthy adults.",
  "The client will provide the dissolution profiles in three media.",
].join("\n");
const CLIENT_CSV = "study_id,time_h,conc_ng_ml\nEX-101,1,30.4\n";

test("a project starts from its proposal and the client's file in one upload, with no approval", async ({ page, request }) => {
  await page.goto("/projects/start");
  await page.getByTestId("drug-name").fill("Dapagliflozin");
  await page.getByTestId("proposal-files").setInputFiles([
    { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) },
    { name: "client-pk.csv", mimeType: "text/csv", buffer: Buffer.from(CLIENT_CSV) },
  ]);
  await expect(page.getByLabel("What client-pk.csv is")).toHaveValue("clinical");      // the tag read from the name
  await expect(page.getByLabel("What proposal.md is")).toHaveValue("proposal");
  await page.getByTestId("start-project").click();

  await page.waitForURL(/\/projects\/[^/]+\/start$/);
  await expect(page.getByTestId("start-drug-name")).toHaveText("Dapagliflozin");
  await expect(page.getByTestId("start-files")).toContainText("proposal.md");
  await expect(page.getByTestId("start-files")).toContainText("client-pk.csv");
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "needs_you");
  await expect(page.getByRole("button", { name: /approve/i })).toHaveCount(0);
  const startUrl = page.url();
  const projectId = /\/projects\/([^/]+)\/start$/.exec(startUrl)![1];

  // Inputs comes after Start (page review 1, decision 7): reached by its address, it says what Start still needs
  await page.goto(startUrl.replace(/\/start$/, "/inputs"));
  await expect(page.getByTestId("inputs-blocked")).toContainText("Inputs come after Start");
  await expect(page.getByTestId("add-open-bind.fu")).toHaveCount(0);
  await finishStart(request, projectId);
  await page.reload();
  await expect(page.getByTestId("inputs-blocked")).toHaveCount(0);

  // a value typed into its row on Inputs, with its source: converted and graded by code, and in the model with nothing
  // to accept (D-27)
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

test("each file is tagged at upload, and a tag the content contradicts is proposed and decided in one click",
  async ({ page }) => {
    // plan 2026-11-03 §3.1 (the owner, 2026-11-03): tags on the "Start from proposal" page; a hint, not a fact; no reason
    await page.goto("/projects/start");
    await page.getByTestId("drug-name").fill("Tagamide");
    await page.getByTestId("proposal-files").setInputFiles([
      { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) },
      { name: "Data_Q3_final.csv", mimeType: "text/csv",
        buffer: Buffer.from("Subject,Time (h),Conc (ng/mL)\n101-001,1,39.8\n101-001,2,50.1\n") },
      { name: "EXZ-101_dosing.csv", mimeType: "text/csv", buffer: Buffer.from("arm,dose_mg\nA,10\n") },
    ]);
    await expect(page.getByLabel("What Data_Q3_final.csv is")).toHaveValue("other");       // the name says nothing
    await expect(page.getByLabel("What EXZ-101_dosing.csv is")).toHaveValue("clinical");
    await expect(page.getByLabel("Which study EXZ-101_dosing.csv belongs to")).toHaveValue("EXZ-101");
    await page.screenshot({ path: test.info().outputPath("start-from-proposal-tags.png"), fullPage: true });
    await page.getByTestId("start-project").click();

    const proposal = page.getByTestId("tag-proposal-Data_Q3_final.csv");
    await expect(proposal).toContainText("The content suggests “Clinical study”");
    await expect(proposal).toContainText("Subject");                                      // what prompted it, quoted
    await page.screenshot({ path: test.info().outputPath("start-tag-proposal.png"), fullPage: true });
    await page.getByTestId("tag-use-Data_Q3_final.csv").click();
    await expect(proposal).toContainText("Tag now “Clinical study”");
    await page.getByTestId("start-continue").click();
    await page.waitForURL(/\/projects\/[^/]+\/start$/);

    await page.getByTestId("nav-library").click();
    await expect(page.getByTestId("library-tag-select-Data_Q3_final.csv")).toHaveValue("clinical");
    await page.getByTestId("library-tag-select-EXZ-101_dosing.csv").selectOption("formulation");   // option D: any time
    await expect(page.getByTestId("library-tag-select-EXZ-101_dosing.csv")).toHaveValue("formulation");
  });
