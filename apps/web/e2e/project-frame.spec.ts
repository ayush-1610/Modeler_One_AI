// A project's frame (the console redesign, slice 3): its Overview at its own address (before, the Run page), Run at
// /campaigns, and Compounds, Members and Settings as pages of their own, in the side navigation. Settings archives and
// restores with a reason; a campaign's breadcrumb sits under its project's Run. Campaign state is seeded test data.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { projectWithInputs } from "./fixtures/inputs";

test("the Overview says where the project stands; Run, Compounds, Members and Settings are pages of their own", async ({ page, request }) => {
  const id = await projectWithInputs(request, "Framamide", [{ study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }]);
  await page.goto(`/projects/${id}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Framamide");
  await expect(page.getByTestId("nav-overview")).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("overview-steps").locator("tbody tr")).toHaveCount(4);
  await expect(page.getByTestId("overview-next")).toHaveAttribute("href", new RegExp(`/projects/${id}/(start|inputs|plan|campaigns)`));
  await expect(page.getByTestId("overview-questions")).toBeVisible();
  await expect(page.getByTestId("overview-activity")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("overview.png"), fullPage: true });

  // Run: the step's own page, with the campaigns
  const run = page.getByRole("navigation", { name: "Project steps" }).getByRole("link", { name: /4 · Run/ });
  if (await run.count()) {
    await expect(run).toHaveAttribute("href", `/projects/${id}/campaigns`);
  }
  await page.goto(`/projects/${id}/campaigns`);
  await expect(page.getByRole("heading", { name: "Run", level: 1 })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Breadcrumbs" })).toContainText("Run");

  // Compounds: each compound with its role and how complete it is; it opens its CPF
  await page.getByTestId("nav-compounds").click();
  await page.waitForURL(new RegExp(`/projects/${id}/compounds$`));
  await expect(page.getByTestId("compound-row-Framamide")).toContainText("%");
  await page.getByTestId("overview-compound-Framamide").click();
  await page.waitForURL(new RegExp(`/projects/${id}/compounds/Framamide$`));
  await expect(page.getByRole("navigation", { name: "Breadcrumbs" }).getByRole("link", { name: "Compounds" })).toHaveAttribute("href", `/projects/${id}/compounds`);

  // Members: its own page
  await page.getByTestId("nav-members").click();
  await page.waitForURL(new RegExp(`/projects/${id}/members$`));
  await expect(page.getByTestId("members-panel")).toBeVisible();

  // Settings: archive with a reason, the Overview says so, and restore
  await page.getByTestId("nav-settings").click();
  await page.waitForURL(new RegExp(`/projects/${id}/settings$`));
  await expect(page.getByTestId("settings-blinding")).toContainText(/On|Off/);
  await page.getByTestId("settings-archive").click();
  await expect(page.getByTestId("settings-archive-confirm")).toBeDisabled();             // no reason, no archive
  await page.getByTestId("settings-archive-reason").fill("a test project, not client work");
  await page.getByTestId("settings-archive-confirm").click();
  await expect(page.getByTestId("project-archived-notice")).toContainText("a test project, not client work");
  await page.goto(`/projects/${id}`);
  await expect(page.getByTestId("project-archived-notice")).toBeVisible();
  await page.goto(`/projects/${id}/settings`);
  await page.getByTestId("settings-restore").click();
  await page.getByTestId("settings-archive-reason").fill("archived by mistake");
  await page.getByTestId("settings-archive-confirm").click();
  await expect(page.getByTestId("project-archived-notice")).toHaveCount(0);
});

test("a campaign's breadcrumb sits under its project's Run", async ({ page, request }) => {
  const id = await projectWithInputs(request, "Crumbamide", [{ study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }]);
  const cid = `camp-crumb-${Date.now()}`;
  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  mkdirSync(root, { recursive: true });
  const file = join(root, "campaigns.json");
  let rows: Record<string, unknown>[] = [];
  try { rows = JSON.parse(readFileSync(file, "utf-8")).campaigns ?? []; } catch { /* first */ }
  writeFileSync(file, JSON.stringify({ campaigns: [...rows, {
    id: cid, project: id, compound: "Crumbamide", question: "exposure", modelRisk: "low", budgetSeconds: 60, elapsedSeconds: 60,
    currentStage: "S7", status: "COMPLETED", stages: [], gof: [], engine: { kind: "software-fixture", command: "seeded" } }] }));
  await page.goto(`/campaigns/${cid}`);
  const crumbs = page.getByRole("navigation", { name: "Breadcrumbs" });
  await expect(crumbs.getByRole("link", { name: "Run" })).toHaveAttribute("href", `/projects/${id}/campaigns`);
  await expect(crumbs).toContainText("Crumbamide");
});
