// The campaign page in the console (the redesign's slice 6, P-16): the fixture banner stays above everything, then one
// part at a time in tabs whose choice is in the address: the stages, the fit (the kit chart, its scale and its numbers
// as a table), the rounds, the feedback, and the S7 package as `GET /campaigns/{id}/package` answers it (reproduction,
// hashes, PK-Sim projects, the report's issues, downloads). The campaign is seeded in the API's read root: software
// test data, no engine run, and the page says so.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

const ID = "camp-tabs-e2e";

function upsert(file: string, key: string, row: Record<string, unknown>) {
  let rows: Record<string, unknown>[] = [];
  try { rows = JSON.parse(readFileSync(file, "utf-8"))[key] ?? []; } catch { /* first row */ }
  writeFileSync(file, JSON.stringify({ [key]: [...rows.filter((r) => r.id !== row.id), row] }));
}

test.beforeAll(() => {
  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  mkdirSync(root, { recursive: true });
  const round = (n: number, auc: number, verdict: string) => ({ round: n, action: n === 1 ? "baseline" : "fit CLint",
                                                                 aucGmfe: auc, cmaxGmfe: auc - 0.1, verdict });
  const stage = (s: string, label: string, status: string, rounds: unknown[] = []) => ({ stage: s, label, status, rounds, notes: [] });
  upsert(join(root, "campaigns.json"), "campaigns", {
    id: ID, project: "", compound: "Tabsamide", question: "the oral dose in adults", modelRisk: "medium",
    budgetSeconds: 28800, elapsedSeconds: 5400, currentStage: "S7", status: "COMPLETED",
    stages: [stage("S0", "Readiness", "PASSED"), stage("S1", "IV disposition", "PASSED", [round(1, 2.4, "failed"), round(2, 1.3, "passed")]),
             stage("S7", "Report and package", "PASSED")],
    gof: [{ name: "iv-250 observed", time_h: [0.5, 1, 2, 4], concentration: [12, 9.5, 6.1, 2.4], unit: "ng/mL", kind: "observed" },
          { name: "iv-250 simulated", time_h: [0.5, 1, 2, 4], concentration: [11.4, 9.1, 6.3, 2.6], unit: "ng/mL", kind: "simulated" }],
    engine: { kind: "software-fixture", command: "seeded" },
    package: {
      exportable: true, reproduction: { passes: true, compared: 4, failures: [] }, report: { md: "/nowhere/mar.md" },
      data_bundle_sha256: "ab".repeat(32), package_sha256: "cd".repeat(32), files: 12,
      report_notes: ["the confidence intervals come from the Hessian"],
      report_issues: [{ kind: "missing_figure", location: "§5.2", detail: "the S5 VPC was not drawn" }],
      pksim_projects: ["pksim/S1.pksim5"], project_notes: ["S6: nothing was simulated, so no project"],
    },
  });
});

test("one part at a time, in the address: stages, the fit, the rounds, the package", async ({ page }) => {
  await page.goto(`/campaigns/${ID}`);
  await expect(page.getByRole("heading", { name: "Tabsamide" })).toBeVisible();
  // not PBPK evidence: said above every tab, unchanged
  await expect(page.getByTestId("engine-warning")).toContainText("Not a PBPK result: this campaign ran on a software test fixture");
  await expect(page.getByTestId("campaign-facts")).toContainText("within 1.5-fold at medium model risk");
  // Stages by default; no tab promises raw run results (they wait for the multi-server deployment) or a prediction
  await expect(page.getByTestId("campaign-tab-stages")).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("campaign-stage-S1")).toContainText("passed");
  await expect(page.getByTestId("campaign-stage-S1")).toContainText("2");
  await expect(page.getByTestId("campaign-tab-runs")).toHaveCount(0);
  await expect(page.getByTestId("campaign-tab-prediction")).toHaveCount(0);

  // the fit: the kit chart, log by default, its numbers as a table
  await page.getByTestId("campaign-tab-fit").click();
  await expect(page).toHaveURL(new RegExp(`/campaigns/${ID}\\?tab=fit$`));
  const chart = page.getByTestId("gof-chart");
  await expect(chart.getByRole("img", { name: /Goodness of fit/ })).toBeVisible();
  await expect(chart.getByTestId("chart-scale-log")).toHaveAttribute("aria-pressed", "true");
  await chart.getByTestId("chart-scale-linear").click();
  await expect(chart.getByTestId("chart-scale-linear")).toHaveAttribute("aria-pressed", "true");
  await chart.getByText("The numbers as a table").click();
  await expect(chart.locator("table")).toContainText("iv-250 observed");
  await expect(chart.locator("table")).toContainText("9.5");

  // the rounds
  await page.getByTestId("campaign-tab-rounds").click();
  await expect(page.getByTestId("round-history")).toContainText("fit CLint");
  await expect(page.getByTestId("campaign-tab-rounds")).toContainText("2");

  // the package, as GET /package answers it
  await page.goto(`/campaigns/${ID}?tab=package`);
  const pkg = page.getByTestId("campaign-package");
  await expect(pkg.getByTestId("package-facts")).toContainText("reproduced · 4 tables");
  await expect(pkg.getByTestId("package-facts")).toContainText(`sha256 ${"cd".repeat(8)}`);
  await expect(pkg.getByTestId("package-pksim")).toContainText("pksim/S1.pksim5");
  await expect(pkg.getByTestId("package-pksim")).toContainText("S6: nothing was simulated, so no project");
  await expect(pkg.getByTestId("package-issues")).toContainText("the S5 VPC was not drawn");
  await expect(pkg).toContainText("the confidence intervals come from the Hessian");
  await expect(pkg.getByRole("button", { name: /Submission package/ })).toBeVisible();
  await expect(pkg.getByRole("button", { name: /Report — Markdown/ })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("package.png"), fullPage: true });

  // the feedback tab says when there is none
  await page.getByTestId("campaign-tab-feedback").click();
  await expect(page.getByTestId("feedback-none")).toContainText("S5 has not failed");
});
