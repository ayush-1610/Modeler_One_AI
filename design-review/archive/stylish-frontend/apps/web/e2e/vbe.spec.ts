// T-31: the campaign monitor shows the S6 virtual bioequivalence. The campaign state is seeded in the API's read root
// (software test data, no engine run): the trials themselves are tested in the orchestrator
// (services/orchestrator/tests/test_vbe_s6.py); this flow checks that an unvalidated result says so before any number.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

const ID = "camp-vbe-e2e";

function upsert(file: string, key: string, row: Record<string, unknown>) {
  let rows: Record<string, unknown>[] = [];
  try { rows = JSON.parse(readFileSync(file, "utf-8"))[key] ?? []; } catch { /* first row */ }
  writeFileSync(file, JSON.stringify({ [key]: [...rows.filter((r) => r.id !== row.id), row] }));
}

const metric = (pos: number, gmr: number) => ({ probability_of_success: pos, gmr_median: gmr, gmr_p05: gmr - 0.04,
                                                gmr_p95: gmr + 0.04, between_subject_cv_percent: 24.5, trials: [] });

test.beforeAll(() => {
  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  mkdirSync(root, { recursive: true });
  const stage = (s: string, status: string) => ({ stage: s, label: s, status, rounds: [], notes: [] });
  upsert(join(root, "campaigns.json"), "campaigns", {
    id: ID, project: "", compound: "Vbeol", question: "generic tablet BE", modelRisk: "medium", budgetSeconds: 3600,
    elapsedSeconds: 60, currentStage: "S6", status: "RUNNING",
    stages: [stage("S0", "PASSED"), stage("S5", "PASSED"), stage("S6", "PASSED")], gof: [],
    engine: { kind: "software-fixture", command: "seeded" },
    prediction: {
      vbe: { template: "vbe-crossover", template_version: "0.2.0-draft", status: "RUN",
             formulations: { test: "Test tablet", reference: "RLD tablet" }, n_subjects: 24, n_trials_run: 100,
             n_trials_planned: 100, limits: [0.8, 1.25], limits_verified: true, pos_threshold: 0.8,
             joint_probability_of_success: 0.91, meets_threshold: true,
             metrics: { AUC_inf: metric(0.97, 1.02), C_max: metric(0.92, 1.05) },
             validation: { status: "NOT_VALIDATED", reason: "no observed BE study (REQ-vbe.be_study) was given" } },
    },
  });
});

test("an unvalidated VBE says so before its probability of success", async ({ page }) => {
  await page.goto(`/campaigns/${ID}`);
  await expect(page.getByText("Virtual bioequivalence (S6)")).toBeVisible();
  await expect(page.getByTestId("vbe-validation")).toHaveText("not validated");
  await expect(page.getByTestId("vbe-not-validated")).toContainText("does not support a bioequivalence decision");
  await expect(page.getByTestId("vbe-joint")).toHaveText("91 %");
  await expect(page.getByText("Test tablet against RLD tablet")).toBeVisible();
});
