// Step 1 · Start (redesign §3.1): a project starts from its proposal and the client's files in one upload, and Start
// is filled by hand. Agents are off in this run (no provider key), so this is the manual path: no "why" is asked except
// for the model risk, the scope gates refuse what the builder cannot model, and Start is done with no approval (D-27).
import { expect, test } from "@playwright/test";

const PROPOSAL = [
  "# Technical proposal TP-E2E: PBPK model of dapagliflozin",
  "Objective: predict exposure after a single oral dose of 10 mg in healthy adults.",
  "The client will provide the dissolution profiles in three media.",
].join("\n");

test("a project starts from its proposal and Start is filled by hand, with no approval", async ({ page }) => {
  await page.goto("/projects/start");
  await page.getByTestId("drug-name").fill("Dapagliflozin");
  await page.getByTestId("proposal-files").setInputFiles([
    { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) },
    { name: "client-pk.csv", mimeType: "text/csv", buffer: Buffer.from("study_id,time_h,conc_ng_ml\nEX-101,1,30.4\n") },
  ]);
  await expect(page.getByLabel("What client-pk.csv is")).toHaveValue("client");     // the client's files go to Inputs
  await page.getByTestId("start-project").click();

  await page.waitForURL(/\/projects\/[^/]+\/start$/);
  await expect(page.getByTestId("start-title")).toHaveText("Dapagliflozin");
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "needs_you");
  await expect(page.locator(".doc-page")).toContainText("single oral dose of 10 mg");
  await expect(page.getByTestId("client-files")).toContainText("client-pk.csv");
  await expect(page.getByTestId("start-missing")).toContainText("Model risk: not set yet");   // never assumed

  // the question, by hand: no "why" is asked
  for (const [path, text] of [["qoi.text", "Effect of a meal on AUC and Cmax of the 10 mg IR tablet"],
                              ["qoi.context_of_use", "Supports the food-effect discussion; does not replace the study"]]) {
    await page.getByTestId(`edit-${path}`).click();
    await page.getByTestId(`field-${path}`).locator("textarea").fill(text);
    await page.getByTestId(`field-${path}`).getByTestId("edit-save").click();
    await expect(page.getByTestId(`field-${path}`)).toContainText("edited");
  }
  await page.getByTestId("tick-qoi.applications-APP-01 model build and verification").locator("input").check();
  await page.getByTestId("save-qoi.applications").click();

  // ICH M15: the two ratings bound the model risk, which is set with its reasons
  await page.getByTestId("choose-m15.influence_rating-medium").click();
  await page.getByTestId("choose-m15.consequence_rating-medium").click();
  await expect(page.getByTestId("risk-bound")).toContainText("gives a model risk of medium");
  await expect(page.getByTestId("risk-set")).toBeDisabled();
  await page.getByTestId("risk-reasons").fill("supports, does not replace, the clinical study");
  await page.getByTestId("risk-set").click();
  await expect(page.getByTestId("field-acceptance.tier")).toContainText("supports, does not replace");

  // the scope gates (D-28): what the builder cannot model is refused here
  await page.getByTestId("choose-drug.modality-small_molecule").click();
  await page.getByTestId("choose-scope.model_structure-minimal_pbpk").click();
  await expect(page.getByTestId("refused-scope.model_structure")).toContainText("Not supported yet: Minimal PBPK");
  await page.getByTestId("choose-scope.model_structure-full_pbpk").click();
  await expect(page.getByTestId("refused-scope.model_structure")).toHaveCount(0);
  await page.getByTestId("choose-scope.site_of_action-systemic").click();
  await page.getByTestId("tick-scope.formulation_types-ir_solid").locator("input").check();
  await page.getByTestId("save-scope.formulation_types").click();
  await page.getByTestId("scenario-new").locator("select").selectOption("oral");
  await page.getByTestId("select-scenarios[0].food_state").selectOption("fasted");

  await expect(page.getByTestId("start-missing")).toContainText("Start is complete");
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "done");   // the brief was never approved
  await expect(page.getByTestId("req-REQ-phys.logp")).toContainText("Lipophilicity");    // the checklist, derived
  await page.screenshot({ path: test.info().outputPath("start.png"), fullPage: true });

  // a proposal note, kept for the report
  await page.getByTestId("proposal-notes").locator("summary").first().click();
  await page.getByTestId("note-add-proj.title").click();
  await page.getByTestId("field-proj.title").locator("input").fill("Dapagliflozin food-effect PBPK");
  await page.getByTestId("field-proj.title").getByTestId("edit-save").click();
  await expect(page.getByTestId("field-proj.title")).toContainText("Dapagliflozin food-effect PBPK");

  // P2, manual path: a value entered with its source, graded by code, accepted with a reason.
  const startUrl = page.url();
  await page.goto(startUrl.replace(/\/start$/, "/evidence"));
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

  await page.goto(startUrl.replace(/\/start$/, "/history"));
  await expect(page.getByText("brief/main").first()).toBeVisible();
  await expect(page.getByText("hash chain verifies")).toBeVisible();
});

test("an old link to the brief lands on Start", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: { Authorization: "Bearer dev" },
    multipart: { drug_name: "Exampleamide", extract: "false", context: "A redirect check." },
  });
  expect(started.ok()).toBeTruthy();
  const { project_id: projectId } = (await started.json()).data;
  await page.goto(`/projects/${projectId}/brief`);
  await page.waitForURL(new RegExp(`/projects/${projectId}/start$`));
  await expect(page.getByTestId("start-title")).toHaveText("Exampleamide");
});
