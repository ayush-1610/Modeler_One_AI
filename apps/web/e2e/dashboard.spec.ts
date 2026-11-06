// The dashboard and the sidebar (plan 2026-11-06-app-design-merge §3 A): every number is read from the API, each
// project's card shows its four steps and opens the step that waits, and the sidebar collapses to a rail and back.
import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

test("the dashboard reads each project's steps, filters by them, and the sidebar collapses", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Dashboardine", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nPBPK model.") } } });
  const projectId = (await started.json()).data.project_id as string;

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  const card = page.getByTestId(`project-card-${projectId}`);
  await expect(card).toBeVisible();
  await expect(card.getByRole("list", { name: "Steps" }).getByRole("listitem")).toHaveCount(4);
  await expect(card).toHaveAttribute("href", new RegExp(`/projects/${projectId}/`));   // opens a step, not a table

  // a KPI is a filter; search narrows the cards; a search with no match says so
  await expect(page.getByTestId("kpi-projects")).toContainText(/\d+/);
  await page.getByTestId("dash-search").fill("Dashboardine");
  await expect(card).toBeVisible();
  await page.getByTestId("dash-search").fill("no-such-compound-xyz");
  await expect(page.getByText("No projects match.")).toBeVisible();
  await page.getByRole("button", { name: "Clear the filters" }).click();
  await expect(card).toBeVisible();

  await expect(page.getByTestId("dash-attention")).toBeVisible();
  await expect(page.getByTestId("dash-risk")).toBeVisible();
  for (const mode of ["light", "dark"] as const) {
    await page.evaluate((m) => document.documentElement.setAttribute("data-theme", m), mode);
    await page.screenshot({ path: test.info().outputPath(`dashboard-${mode}.png`), fullPage: true });
  }

  // the list view is the record: archive, restore, history
  await page.getByTestId("dash-view-list").click();
  await expect(page.getByTestId(`project-row-${projectId}`)).toBeVisible();

  // the sidebar collapses to a rail; the links keep their names; the choice survives a reload
  const nav = page.getByRole("navigation", { name: "Main" });
  await page.getByTestId("nav-collapse").click();
  await expect(page.getByTestId("sidebar")).toHaveClass(/collapsed/);
  await expect(nav.getByRole("link", { name: "Review inbox" })).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("sidebar")).toHaveClass(/collapsed/);
  await page.screenshot({ path: test.info().outputPath("dashboard-collapsed.png") });
  await page.getByTestId("nav-collapse").click();
  await expect(page.getByTestId("sidebar")).not.toHaveClass(/collapsed/);

  // inside a project, the sidebar holds its own pages, History among them
  await page.goto(`/projects/${projectId}/start`);
  await expect(page.getByTestId("nav-history")).toHaveAttribute("href", `/projects/${projectId}/history`);
});
