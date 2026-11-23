// The intake agent's suggested M15 ratings: pre-selected with the reason until the person saves (the owner, 2026-11-05,
// reversing 2026-11-02's "shown only after rating"); saving keeps a suggestion as the person's rating. Of the tiers two
// different ratings admit, the stricter is pre-selected with the agent's reason, and the internal target's default,
// 10 %, applies without saving (the owner, 2026-11-06). Once saved, the same rating is noted, and a different one is flagged and
// settles on one, the suggestion taken or the person's rating kept with a reason. The browser flows run with no LLM provider, so a fixture
// writes the suggestion as agent A1 would (DRAFTED, through the brief's own functions).
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");

test("a suggested rating is pre-selected with its reason, and a difference settles on one", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Suggestamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nDose selection support.") } } });
  const projectId = (await started.json()).data.project_id as string;
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "agent_suggestion.py"),
                      join(process.env.E2E_DATA_DIR!, "read-root"), projectId, "medium", "high"], { cwd: REPO });

  await page.goto(`/projects/${projectId}/start`);
  // before the person saves: the suggestions pre-selected, each said to be the agent's
  await expect(page.getByTestId("risk-influence-medium")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("risk-consequence-high")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("risk-influence-preselected")).toContainText("The intake agent suggests medium; save");
  await expect(page.getByTestId("risk-consequence-preselected")).toContainText("The intake agent suggests high; save");
  await expect(page.getByTestId("risk-influence-differs")).toHaveCount(0);
  // the ratings admit medium and high: the stricter is pre-selected (the owner, 2026-11-06)
  await expect(page.getByTestId("risk-tier-high")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("risk-tier-preselected")).toContainText("the stricter of the tiers these ratings admit");

  // the person picks another influence and keeps the suggested consequence
  await page.getByTestId("risk-influence-high").click();
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

test("the stricter tier comes with the agent's reason, and the internal target's default applies without saving",
  async ({ page, request }) => {
    const reason = "A wrong dose would reach patients on the model's word alone, so the stricter risk, high, applies";
    const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
      drug_name: "Strictamide", extract: "false",
      files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nDose selection support.") } } });
    const projectId = (await started.json()).data.project_id as string;
    execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "agent_suggestion.py"),
                        join(process.env.E2E_DATA_DIR!, "read-root"), projectId, "medium", "high", reason], { cwd: REPO });

    await page.goto(`/projects/${projectId}/start`);
    await expect(page.getByTestId("risk-tier-high")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("risk-tier-preselected")).toContainText("with the intake agent's reason below");
    await expect(page.getByTestId("risk-why")).toHaveValue(reason);
    await expect(page.getByTestId("risk-why-drafted")).toBeVisible();
    await expect(page.getByTestId("risk-target-input")).toHaveValue("10");
    await expect(page.getByTestId("risk-target-default")).toContainText("applies once the model risk is saved");
    await expect(page.getByTestId("risk-problem")).toContainText("Model risk: not set yet");     // offered, not saved
    await page.getByTestId("start-risk").screenshot({ path: test.info().outputPath("m15-preselected.png") });

    // saved as offered: the ratings, the stricter tier and the agent's reason become the person's
    await page.getByTestId("risk-save").click();
    await expect(page.getByTestId("risk-current")).toHaveText("Saved: high");
    await expect(page.getByTestId("risk-why")).toHaveValue(reason);
    await expect(page.getByTestId("risk-why-drafted")).toHaveCount(0);
    await expect(page.getByTestId("risk-tier-preselected")).toHaveCount(0);
    await expect(page.getByTestId("risk-problem")).toHaveCount(0);
    // the default applies without saving; emptied, there is none; and it comes back
    await expect(page.getByTestId("risk-target-default")).toContainText("applied; change it, or empty it for none");
    await expect(page.getByTestId("risk-target-save")).toBeDisabled();
    await page.getByTestId("risk-target-input").fill("");
    await page.getByTestId("risk-target-save").click();
    await expect(page.getByTestId("risk-target-none")).toContainText("none: the tier's limits alone");
    await page.getByTestId("risk-target-use-default").click();
    await expect(page.getByTestId("risk-target-default")).toContainText("applied");
    await expect(page.getByTestId("risk-target-input")).toHaveValue("10");
  });
