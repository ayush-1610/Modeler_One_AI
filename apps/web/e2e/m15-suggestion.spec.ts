// The intake agent's suggested M15 ratings (the owner, 2026-11-02): not preselected and not shown until the person has
// saved their own rating; then the same rating is noted, and a different one is flagged and settles on one, the
// suggestion taken or the person's rating kept with a reason. The browser flows run with no LLM provider, so a fixture
// writes the suggestion as agent A1 would (DRAFTED, through the brief's own functions).
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");

test("a suggested rating shows once the person has rated, and a difference settles on one", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Suggestamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nDose selection support.") } } });
  const projectId = (await started.json()).data.project_id as string;
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "agent_suggestion.py"),
                      join(process.env.E2E_DATA_DIR!, "read-root"), projectId, "medium", "high"], { cwd: REPO });

  await page.goto(`/projects/${projectId}/start`);
  // before the person rates: nothing preselected, and the suggestion is not shown
  await expect(page.getByTestId("risk-influence-suggestion-hidden")).toBeVisible();
  for (const r of ["low", "medium", "high"]) {
    await expect(page.getByTestId(`risk-influence-${r}`)).toHaveAttribute("aria-pressed", "false");
  }
  await expect(page.getByTestId("risk-influence-differs")).toHaveCount(0);

  await page.getByTestId("risk-influence-high").click();
  await page.getByTestId("risk-consequence-high").click();
  await page.getByTestId("risk-save").click();
  await expect(page.getByTestId("risk-current")).toHaveText("Saved: high");
  // the same rating is noted; a different one is flagged, and Start waits on it
  await expect(page.getByTestId("risk-consequence-agrees")).toContainText("the same: high");
  const differs = page.getByTestId("risk-influence-differs");
  await expect(differs).toContainText("You rated high; the intake agent suggested medium.");
  await expect(differs).toContainText("Take the suggestion, or keep your rating and say why");
  await expect(page.getByTestId("start-waiting")).toBeVisible();

  // taken: the suggestion is picked, and saved with its tier like any rating
  await page.getByTestId("risk-influence-take").click();
  await expect(page.getByTestId("risk-influence-medium")).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("risk-tier-high").click();
  await page.getByTestId("risk-why").fill("A wrong dose would harm patients, whatever the model's share of the evidence");
  await page.getByTestId("risk-save").click();
  await expect(page.getByTestId("risk-influence-agrees")).toContainText("the same: medium");

  // kept: the person keeps a different rating and says why
  await page.getByTestId("risk-consequence-medium").click();
  await page.getByTestId("risk-tier-medium").click();
  await page.getByTestId("risk-save").click();
  await expect(page.getByTestId("risk-consequence-differs")).toContainText("the intake agent suggested high");
  await expect(page.getByTestId("risk-consequence-keep")).toBeDisabled();
  await page.getByTestId("risk-consequence-reason").fill("The dose is also confirmed in a clinical study before use");
  await page.getByTestId("risk-consequence-keep").click();
  await expect(page.getByTestId("risk-consequence-kept"))
    .toHaveText("Kept medium: The dose is also confirmed in a clinical study before use");
  await expect(page.getByTestId("risk-consequence-differs")).not.toHaveClass(/needs-you/);
  await page.screenshot({ path: test.info().outputPath("m15-suggestion.png"), fullPage: true });
});
