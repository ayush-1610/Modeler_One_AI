// Step 1 · Start (redesign §3.1), the manual path (agents off, no provider key): the short brief filled in place with
// no reason asked, the ICH M15 model risk within the range its ratings admit, a refused liposome (D-28), the checklist
// derived with no button, and the stepper showing Start done. Nothing on the screen is approved (D-27).
import { expect, test } from "@playwright/test";

const PROPOSAL = [
  "# Technical proposal TP-E2E-2: PBPK model of exampleamide",
  "Objective: predict exposure after a single oral dose of 10 mg in healthy adults, fasted and fed.",
  "The client will provide the clinical PK data of study EX-101.",
].join("\n");

test("Start: the short brief, the model risk, the scope gates and the checklist, with no approval", async ({ page }) => {
  await page.goto("/projects/start");
  await page.getByTestId("drug-name").fill("Exampleamide");
  await page.getByTestId("proposal-files").setInputFiles({ name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) });
  await page.getByTestId("start-project").click();

  await page.waitForURL(/\/projects\/[^/]+\/start$/);
  await expect(page.getByTestId("start-title")).toHaveText("Exampleamide");
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "needs_you");
  const waiting = page.getByTestId("start-waiting");
  await expect(waiting).toContainText("Question of interest: not set yet");
  await expect(waiting).toContainText("Model risk: not set yet (it is never assumed)");
  await expect(page.locator(".doc-page")).toContainText("single oral dose of 10 mg");

  // the question: set in place, nothing asks why; the record says who set it
  const set = async (path: string, value: string) => {
    await page.getByTestId(`edit-${path}`).click();
    await page.getByTestId(`input-${path}`).fill(value);
    await page.getByTestId(`save-${path}`).click();
    await expect(page.getByTestId(`start-field-${path}`)).toContainText(value);
  };
  await set("qoi.text", "Exposure after a single 10 mg oral dose, fasted and fed");
  await expect(page.getByTestId("start-field-qoi.text")).toContainText("set by");
  await set("qoi.context_of_use", "Support the food-effect labelling");
  await page.getByTestId("edit-qoi.applications").click();
  await page.getByTestId("input-qoi.applications").getByLabel("APP-12 food effect").check();
  await page.getByTestId("save-qoi.applications").click();
  await expect(page.getByTestId("start-field-qoi.applications")).toContainText("APP-12 food effect");

  // the model risk (ICH M15 §2.1.5): different ratings admit the tiers between them, and the choice needs a reason
  await page.getByTestId("risk-influence-medium").click();
  await page.getByTestId("risk-consequence-high").click();
  await expect(page.getByTestId("risk-tier-low")).toHaveCount(0);
  await page.getByTestId("risk-tier-high").click();
  await expect(page.getByTestId("risk-save")).toBeDisabled();
  await page.getByTestId("risk-why").fill("The label claim rests on the model: a wrong fed prediction misdoses patients");
  await page.getByTestId("risk-save").click();
  await expect(page.getByTestId("risk-current")).toHaveText("Saved: high");
  await expect(waiting).not.toContainText("Model risk");

  // what is modelled (D-28): a liposome is refused before any data work, an IR tablet is built
  await page.getByTestId("pick-modality-small_molecule").click();
  await page.getByTestId("pick-pbpk_model-full").click();
  await page.getByTestId("pick-site_of_action-systemic").click();
  const forms = page.getByTestId("pick-formulation_types");
  await forms.getByLabel("liposome").check();
  await expect(page.getByTestId("gate-formulation_types-state")).toHaveText("not supported yet");
  await expect(page.getByTestId("gate-formulation_types-message")).toContainText("liposome: not supported yet");
  await expect(waiting).toContainText("Formulation types: liposome: not supported yet");
  await forms.getByLabel("liposome").uncheck();
  await forms.getByLabel("immediate-release tablet").check();
  await expect(page.getByTestId("gate-formulation_types-state")).toHaveText("supported");
  await page.getByTestId("route-add").click();
  await page.getByTestId("route-new").selectOption("oral");
  await expect(page.getByTestId("gate-routes-state")).toHaveText("supported");

  // the checklist follows the brief, with no approval anywhere on the screen
  await expect(page.getByTestId("check-REQ-phys.logp")).toBeVisible();
  await expect(page.getByRole("button", { name: /approve/i })).toHaveCount(0);
  await expect(page.getByTestId("start-done")).toBeVisible();
  await expect(page.getByTestId("step-start")).toHaveAttribute("data-state", "done");
  await page.screenshot({ path: test.info().outputPath("start.png"), fullPage: true });
});
