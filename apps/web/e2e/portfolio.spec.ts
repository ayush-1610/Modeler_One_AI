// The portfolio's new pages (the console redesign, slice 2): Your work lists, as links, what waits on this person across
// projects and filters it; Campaigns lists every campaign of their projects; Help explains in plain words. Nothing is
// decided on these pages (the owner's decision G1-3). Campaign state is seeded software test data, no engine run.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

test("Your work lists each waiting step as a link, filters it, and the counts agree", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Workamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nPBPK model.") } } });
  const projectId = (await started.json()).data.project_id as string;

  await page.goto("/work");
  await expect(page.getByRole("heading", { name: "Your work", level: 1 })).toBeVisible();
  const row = page.getByTestId(`work-row-step-${projectId}-start`);
  await expect(row).toContainText("Confirm the brief");
  await expect(row).toContainText("To confirm");
  await expect(page.getByTestId(`work-open-step-${projectId}-start`)).toHaveAttribute("href", `/projects/${projectId}/start`);
  // the count in the top bar and in the side navigation is the list's
  const rows = await page.getByTestId("work-table").locator("tbody tr").count();
  await expect(page.getByTestId("top-work")).toContainText(String(rows));
  await expect(page.getByTestId("nav-work")).toContainText(String(rows));
  // filters: a kind with nothing of it says so; the project filter keeps this project's row
  await page.getByTestId("work-kind").selectOption("To sign");
  await expect(row).toHaveCount(0);
  await page.getByTestId("work-kind").selectOption("");
  await page.getByTestId("work-project").selectOption(projectId);
  await expect(row).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("work.png"), fullPage: true });
  await page.getByTestId(`work-open-step-${projectId}-start`).click();
  await page.waitForURL(new RegExp(`/projects/${projectId}/start$`));
});

test("Campaigns lists every campaign of the person's projects, and Help explains in plain words", async ({ page, request }) => {
  const created = await request.post("/api/v1/projects", { headers: AUTH, data: { name: `Campaignlist ${Date.now()}`, compound: "Listol" } });
  const projectId = (await created.json()).data.id as string;
  const id = `camp-list-${Date.now()}`;
  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  mkdirSync(root, { recursive: true });
  const file = join(root, "campaigns.json");
  let rows: Record<string, unknown>[] = [];
  try { rows = JSON.parse(readFileSync(file, "utf-8")).campaigns ?? []; } catch { /* first */ }
  writeFileSync(file, JSON.stringify({ campaigns: [...rows, {
    id, project: projectId, compound: "Listol", question: "exposure", modelRisk: "low", budgetSeconds: 3600, elapsedSeconds: 900,
    currentStage: "S1", status: "RUNNING", stages: [], gof: [], engine: { kind: "software-fixture", command: "seeded" } }] }));

  await page.goto("/campaigns");
  const row = page.getByTestId(`campaign-row-${id}`);
  await expect(row).toContainText("Listol");
  await expect(row).toContainText("25 %");                                 // 900 s of 3600 s
  await expect(row.getByRole("link", { name: id })).toHaveAttribute("href", `/campaigns/${id}`);
  await page.screenshot({ path: test.info().outputPath("campaigns.png"), fullPage: true });

  await page.goto("/help");
  await expect(page.getByRole("heading", { name: "Getting started" })).toBeVisible();
  await page.getByTestId("help-words").click();
  await page.waitForURL(/\/help\/words$/);
  await expect(page.getByText("Missing: no file or source gives the value yet.")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Breadcrumbs" })).toContainText("Status words");
});
