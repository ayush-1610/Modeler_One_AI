// T-55: a failed external validation (S5) waits for a signed feedback decision. The campaign state is seeded in the
// API's read root (software test data, no engine run): the learn → re-run path itself is tested in the orchestrator
// (services/orchestrator/tests/test_feedback.py); this flow checks what the reviewer sees and signs.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

const ID = "camp-feedback-e2e";

function upsert(file: string, key: string, row: Record<string, unknown>) {
  let rows: Record<string, unknown>[] = [];
  try { rows = JSON.parse(readFileSync(file, "utf-8"))[key] ?? []; } catch { /* first row */ }
  writeFileSync(file, JSON.stringify({ [key]: [...rows.filter((r) => r.id !== row.id), row] }));
}

const diagnosis = {
  cycle: 1,
  failing: [{ study_id: "fed-1", class: "PO-FED", group: "fed", failed: ["AUC", "Cmax"], ratio: { AUC: 2.6, Cmax: 2.6 },
              direction: "over-predicted", learn_stage: "S3", differences: ["fed, and no fed study trains the model"],
              influences: [{ parameter: "phys.solubility.ref", auc: null, cmax: null }] }],
  classes: { "PO-FED": { failing: ["fed-1"], unspent: [], cycles: 0,
                         learn: { possible: false, reason: "external validation of PO-FED not achievable: no other external PO-FED study is left to confirm a learned model" } } },
  notAchievable: ["external validation of PO-FED not achievable: no other external PO-FED study is left to confirm a learned model"],
  notes: [],
};

test.beforeAll(() => {
  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  mkdirSync(root, { recursive: true });
  const stage = (s: string, status: string) => ({ stage: s, label: s, status, rounds: [], notes: [] });
  upsert(join(root, "campaigns.json"), "campaigns", {
    id: ID, project: "", compound: "Feedbackol", question: "fed exposure", modelRisk: "medium", budgetSeconds: 3600,
    elapsedSeconds: 60, currentStage: "S5", status: "ESCALATED", cycle: 1, feedback: [], feedbackPending: diagnosis,
    stages: [stage("S0", "PASSED"), stage("S1", "PASSED"), stage("S5", "ESCALATED"), stage("S6", "PENDING")],
    gof: [], engine: { kind: "software-fixture", command: "seeded" },
    resume: {
      request: { campaign_id: ID, tenant_id: "dev", compound: "Feedbackol", map_id: "m", cpf_uri: "file:///none/cpf.json",
                 cpf_sha256: "a".repeat(64), stages: ["S0", "S1", "S5", "S6"] },
      cpf_uri: "file:///none/cpf.json", cpf_sha256: "a".repeat(64), completed_stages: ["S0", "S1"],
      escalated_stage: "S5", feedback: diagnosis,
    },
  });
  upsert(join(root, "escalations.json"), "escalations", {
    id: `${ID}-S5`, campaignId: ID, stage: "S5", reasonCode: "EXTERNAL_VALIDATION_FAILED",
    evidence: "External validation failed (cycle 1): fed-1 (PO-FED): AUC, Cmax over-predicted.", feedback: diagnosis,
    options: [
      { id: "accept_best", label: "Record a limitation and continue (restrict the context of use, MS-01 §6.6)", requiresSignature: true },
      { id: "learn", label: "Learn: move the failing studies to the internal set", requiresSignature: true,
        disabled: diagnosis.notAchievable[0] },
      { id: "new_evidence", label: "New evidence: replace one parameter by a measured value", requiresSignature: true },
      { id: "abort", label: "Stop the campaign", requiresSignature: true },
    ],
  });
});

test("an S5 failure: the diagnosis, learn not achievable, a signed limitation", async ({ page }) => {
  await page.goto(`/campaigns/${ID}`);
  await expect(page.getByTestId("feedback-pending")).toBeVisible();
  await expect(page.getByTestId("feedback-diagnosis")).toContainText("fed, and no fed study trains the model");

  await page.goto("/review");
  const card = page.locator(".card", { hasText: `campaign ${ID}, stage S5` });
  await expect(card.getByTestId("feedback-diagnosis")).toContainText("over-predicted");
  await expect(card.getByTestId("decision-select").locator("option[value=learn]")).toBeDisabled();
  await expect(card).toContainText("not achievable");
  await card.screenshot({ path: test.info().outputPath("feedback-decision.png") });
  await card.getByTestId("decision-select").selectOption("new_evidence");
  await expect(card.getByTestId("decision-sign")).toBeDisabled();          // the measured value and its source first
  await card.getByTestId("decision-select").selectOption("accept_best");
  await card.locator("textarea").first().fill("fed claims are withdrawn from the context of use");
  await card.getByTestId("decision-sign").click();
  await page.getByTestId("decision-confirm").click();
  // the inbox refreshes: the S5 decision is gone and the S4/S5 evaluation now waits for its signature
  await expect(page.getByRole("heading", { name: `Escalation — campaign ${ID}, stage S6` })).toBeVisible();
  await expect(page.getByRole("heading", { name: `Escalation — campaign ${ID}, stage S5` })).toHaveCount(0);

  await page.goto(`/campaigns/${ID}`);
  await expect(page.getByTestId("feedback-timeline")).toContainText("limitation");
  await expect(page.getByTestId("feedback-pending")).toHaveCount(0);
  await expect(page.locator(".spread .chip").first()).toHaveText(/awaiting_signature/, { timeout: 30_000 });
  await page.screenshot({ path: test.info().outputPath("feedback.png"), fullPage: true });
});
