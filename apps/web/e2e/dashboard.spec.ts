// The dashboard and the sidebar (plan 2026-11-06-app-design-merge §3 A): every number is read from the API, each
// project's card shows its four steps and opens the step that waits, and the side navigation is fixed (console redesign).
import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

test("the dashboard reads each project's steps, filters by them, and the side navigation is fixed", async ({ page, request }) => {
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
  await page.screenshot({ path: test.info().outputPath("dashboard.png"), fullPage: true });

  // the list view is the record: archive, restore, history
  await page.getByTestId("dash-view-list").click();
  await expect(page.getByTestId(`project-row-${projectId}`)).toBeVisible();

  // the side navigation is fixed and always open on a desktop (the console redesign, decision G1-2: no hover-open rail,
  // no pin): its links are named, and the current page is marked
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(page.getByTestId("sidebar")).toBeVisible();
  await expect(nav.getByRole("link", { name: "Projects" })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: "Start from proposal" })).toBeVisible();
  await expect(page.getByTestId("nav-pin")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("dashboard-shell.png") });

  // inside a project, the sidebar holds its own pages, History among them
  await page.goto(`/projects/${projectId}/start`);
  await expect(page.getByTestId("nav-history")).toHaveAttribute("href", `/projects/${projectId}/history`);
});
