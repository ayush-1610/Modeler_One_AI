// Step 1 · Start (redesign §3.1; page review 1, 2026-10-27), the manual path (agents off, no provider key): what still needs
// the person is marked red on its own box, with no side panel; the steps after Start are locked until it is done. The
// question with what each application adds, the pathways as one list, nonlinearity as yes / no / not stated, the ICH M15
// model risk with its tier's criteria and an internal target no looser than the tier, a refused liposome (D-28), the
// product as one line, a route's dose edited in place. Nothing on the screen is approved (D-27).
import { expect, test } from "@playwright/test";

const PROPOSAL = [
  "# Technical proposal TP-E2E-2: PBPK model of exampleamide",
  "Objective: predict exposure after a single oral dose of 10 mg in healthy adults, fasted and fed.",
  "The client will provide the clinical PK data of study EX-101.",
].join("\n");

test("Start: each box that waits on the person is marked red, and Start cannot be left until none is", async ({ page }) => {
  await page.goto("/projects/start");
  await page.getByTestId("drug-name").fill("Exampleamide");
  await page.getByTestId("proposal-files").setInputFiles({ name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) });
  await page.getByTestId("start-project").click();

  await page.waitForURL(/\/projects\/[^/]+\/start$/);
  const startUrl = page.url();
  await expect(page.getByTestId("start-drug-name")).toHaveText("Exampleamide");
  await expect(page.getByTestId("start-read")).toHaveText("Read the proposal again");
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "needs_you");
  // no side panel: the field itself is marked, and the bar at the bottom holds Start until nothing is marked
  await expect(page.getByTestId("start-field-qoi.text")).toHaveClass(/needs-you/);
  await expect(page.getByTestId("start-field-qoi.text")).toContainText("Question of interest: not set yet");
  await expect(page.getByTestId("risk-problem")).toContainText("Model risk: not set yet (it is never assumed)");
  await expect(page.getByTestId("start-waiting")).toContainText("marked in red above");
  await expect(page.getByTestId("start-continue")).toBeDisabled();
  await expect(page.getByTestId("step-inputs-locked")).toBeVisible();
  await expect(page.getByTestId("step-review-locked")).toBeVisible();
  // reached by its address, Inputs is blocked until Start is done, and says what Start still needs (decision 7)
  await page.goto(startUrl.replace(/\/start$/, "/inputs"));
  await expect(page.getByTestId("inputs-blocked")).toContainText("Question of interest: not set yet");
  await page.getByTestId("inputs-blocked-start").click();
  await page.waitForURL(/\/start$/);

  // the question: set in place, nothing asks why; the record says who set it; each application says what it adds
  const set = async (path: string, value: string) => {
    await page.getByTestId(`edit-${path}`).click();
    await page.getByTestId(`input-${path}`).fill(value);
    await page.getByTestId(`save-${path}`).click();
    await expect(page.getByTestId(`start-field-${path}`)).toContainText(value);
  };
  await set("qoi.text", "Exposure after a single 10 mg oral dose, fasted and fed");
  await expect(page.getByTestId("start-field-qoi.text")).toContainText("set by");
  await expect(page.getByTestId("start-field-qoi.text")).not.toHaveClass(/needs-you/);
  await set("qoi.context_of_use", "Support the food-effect labelling");
  await page.getByTestId("edit-qoi.applications").click();
  await page.getByTestId("input-qoi.applications").getByLabel("APP-12 food effect").check();
  await page.getByTestId("save-qoi.applications").click();
  await expect(page.getByTestId("start-app-adds")).toContainText("food effect: + Meal composition of each fed study");
  // what only the client can send follows the applications, and downloads as the data request (decision 2b)
  await expect(page.getByTestId("request-REQ-fe.biorelevant")).toContainText("FaSSIF / FeSSIF solubility");
  await expect(page.getByTestId("request-REQ-fe.biorelevant")).toContainText("for food effect");
  const download = page.waitForEvent("download");
  await page.getByTestId("request-download").click();
  expect((await download).suggestedFilename()).toMatch(/-data-request\.xlsx$/);

  // the pathways, one list: each named pathway with its kind
  await page.getByTestId("edit-pathways").click();
  await page.getByTestId("pathway-kind-0").selectOption("hepatic_metabolism");
  await page.getByTestId("pathway-name-0").fill("UGT1A9");
  await page.getByTestId("pathway-add").click();
  await page.getByTestId("pathway-kind-1").selectOption("renal_filtration");
  await page.getByTestId("pathway-save").click();
  await expect(page.getByTestId("pathway-list")).toContainText("UGT1A9 · hepatic metabolism");
  await expect(page.getByTestId("pathway-list")).toContainText("renal filtration");
  // nonlinearity and enterohepatic recycling: yes / no / not stated
  await page.getByTestId("stated-scope.nonlinearity-no").click();
  await expect(page.getByTestId("stated-scope.nonlinearity-no")).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByTestId("stated-scope.nonlinearity-no")).toHaveAttribute("aria-pressed", "true");

  // the model risk (ICH M15 §2.1.5): different ratings admit the tiers between them, and the choice needs a reason; the
  // tier's criteria show beside it
  await page.getByTestId("risk-influence-medium").click();
  await page.getByTestId("risk-consequence-high").click();
  await expect(page.getByTestId("risk-tier-low")).toHaveCount(0);
  await page.getByTestId("risk-tier-high").click();
  await expect(page.getByTestId("risk-criteria")).toContainText("high: AUC within 1.25-fold");
  await expect(page.getByTestId("risk-save")).toBeDisabled();
  await page.getByTestId("risk-why").fill("The label claim rests on the model: a wrong fed prediction misdoses patients");
  await page.getByTestId("risk-save").click();
  await expect(page.getByTestId("risk-current")).toHaveText("Saved: high");
  await expect(page.getByTestId("risk-problem")).toHaveCount(0);
  // why each rating is what it is (ICH M15 §2.1.5): with no agent there is no draft, so the person writes both; with one,
  // its draft is confirmed or changed here (decision 1b of 2026-10-29)
  await expect(page.getByTestId("start-field-m15.influence")).toContainText("How the model is used: not written yet");
  await set("m15.influence", "The model is the main evidence for the fed label claim: no fed study of this tablet");
  await set("m15.consequence", "A wrong fed prediction would misdose patients who take the tablet with a meal");
  await expect(page.getByTestId("start-field-m15.consequence")).not.toHaveClass(/needs-you/);
  // the internal target sits under the tier, and is never looser than it (MS-01 §8: at most 20 % at high)
  await page.getByTestId("risk-target-input").fill("30");
  await page.getByTestId("risk-target-save").click();
  await expect(page.getByTestId("risk-target")).toContainText("Internal target: at most 20.0 %");
  await page.getByTestId("risk-target-input").fill("15");
  await page.getByTestId("risk-target-save").click();
  await expect(page.getByTestId("risk-target")).not.toContainText("Internal target: at most 20.0 %");

  // what is modelled (D-28): a liposome is refused before any data work, an IR tablet is built; the product reads as one
  // line once the three are supported
  await page.getByTestId("pick-modality-small_molecule").click();
  await page.getByTestId("pick-pbpk_model-full").click();
  await page.getByTestId("pick-site_of_action-systemic").click();
  await expect(page.getByTestId("gate-product-line")).toContainText("full PBPK");
  const forms = page.getByTestId("pick-formulation_types");
  await forms.getByLabel("liposome").check();
  await expect(page.getByTestId("gate-formulation_types-state")).toHaveText("not supported yet");
  await expect(page.getByTestId("gate-formulation_types-message")).toContainText("liposome: not supported yet");
  await expect(page.getByTestId("gate-formulation_types")).toContainText("Formulation types: liposome: not supported yet");
  await forms.getByLabel("liposome").uncheck();
  await forms.getByLabel("immediate-release tablet").check();
  await expect(page.getByTestId("gate-formulation_types-state")).toHaveText("supported");
  await page.getByTestId("route-add").click();
  await page.getByTestId("route-new").selectOption("oral");
  await expect(page.getByTestId("gate-routes-state")).toHaveText("supported");
  await page.getByTestId("dose-0").fill("10");
  await page.getByTestId("dose-0").blur();
  await page.reload();
  await expect(page.getByTestId("dose-0")).toHaveValue("10");

  // nothing to approve; Start is done and Inputs opens
  await expect(page.getByRole("button", { name: /approve/i })).toHaveCount(0);
  await expect(page.getByTestId("start-done")).toBeVisible();
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("step-inputs-locked")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("start.png"), fullPage: true });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.screenshot({ path: test.info().outputPath("start-dark.png"), fullPage: true });
  await page.emulateMedia({ colorScheme: "light" });
  await page.getByTestId("start-continue").click();
  await page.waitForURL(/\/inputs$/);
  await expect(page.getByTestId("inputs-start-not-done")).toHaveCount(0);
  await expect(page.getByTestId("inputs-blocked")).toHaveCount(0);
});
