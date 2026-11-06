// What the intake agent proposes from what a proposal implies rather than states (plan 2026-11-05 §3.4, build D): the
// context of use, the formulation types and each scenario's route are shown pre-selected with the quote they rest on,
// and Start waits until a person confirms or changes each. The browser flows run with no LLM provider, so a fixture
// writes the drafts as agent A1's propose_implied would (DRAFTED, through the brief's own functions).
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const QUOTE = "a biowaiver of the 25 mg immediate-release tablet";

test("what the proposal implies is pre-selected with its quote, and Start waits on a person's word", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Impliedamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown",
             buffer: Buffer.from(`# Proposal\nPBPK modelling to support ${QUOTE}, taken by mouth.`) } } });
  const projectId = (await started.json()).data.project_id as string;
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "agent_implied.py"),
                      join(process.env.E2E_DATA_DIR!, "read-root"), projectId, QUOTE], { cwd: REPO });

  await page.goto(`/projects/${projectId}/start`);
  // the context of use: the agent's words in place, with Confirm, and Start says what it waits on
  const cou = page.getByTestId("start-field-qoi.context_of_use");
  await expect(cou).toContainText("support a biowaiver of the 25 mg strength");
  await expect(cou).toContainText("Context of use: confirm the intake agent's proposal, or change it");
  // the formulation types and the route: pre-selected, with the quote they rest on
  const forms = page.getByTestId("gate-formulation_types");
  await expect(forms.getByRole("checkbox", { name: "immediate-release tablet" })).toBeChecked();
  await expect(page.getByTestId("drafted-scope.formulation_types")).toBeVisible();
  await expect(page.getByTestId("gate-formulation_types-state")).toHaveText("to confirm");
  await expect(forms).toContainText("Formulation types: confirm the intake agent's proposal, or change it");
  await expect(page.getByTestId("route-0")).toHaveValue("oral");
  await expect(page.getByTestId("gate-routes")).toContainText("Scenario 1: route: confirm the intake agent's proposal, or change it");
  await expect(page.getByTestId("start-waiting")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("implied-drafts-to-confirm.png"), fullPage: true });

  await page.getByTestId("confirm-qoi.context_of_use").click();
  await expect(cou).not.toContainText("confirm the intake agent's proposal");
  await page.getByTestId("confirm-scope.formulation_types").click();
  await expect(page.getByTestId("drafted-scope.formulation_types")).toHaveCount(0);
  await expect(forms).not.toContainText("confirm the intake agent's proposal");
  await expect(forms.getByRole("checkbox", { name: "immediate-release tablet" })).toBeChecked();
  await expect(page.getByTestId("gate-formulation_types-state")).toHaveText("supported");
  await page.getByTestId("confirm-scenarios[0].route").click();
  await expect(page.getByTestId("drafted-scenarios[0].route")).toHaveCount(0);
  await expect(page.getByTestId("gate-routes")).not.toContainText("confirm the intake agent's proposal");
  await expect(page.getByTestId("route-0")).toHaveValue("oral");
  await page.screenshot({ path: test.info().outputPath("implied-drafts.png"), fullPage: true });
});
