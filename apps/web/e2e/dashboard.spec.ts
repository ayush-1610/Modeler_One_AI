// Home and Projects (the console redesign, slice 2; earlier the dashboard of plan 2026-11-06-app-design-merge §3 A):
// every number is read from the API; the projects carry their four steps from the one list read (R-N03); Projects keeps
// the cards as an option; the side navigation is fixed.
import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

test("Home and Projects read each project's steps from the list, and the side navigation is fixed", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Dashboardine", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nPBPK model.") } } });
  const projectId = (await started.json()).data.project_id as string;

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Home", level: 1 })).toBeVisible();
  const row = page.getByTestId("home-projects").getByTestId(`project-row-${projectId}`);
  await expect(row).toBeVisible();
  await expect(row.getByRole("img", { name: /Start: .*, Data: .*, Review & sign: .*, Run: / })).toBeVisible();   // the four steps
  await expect(row.getByRole("link", { name: "Confirm the brief" })).toHaveAttribute("href", `/projects/${projectId}/start`);
  await expect(page.getByTestId("kpi-projects")).toContainText(/\d+/);
  await expect(page.getByTestId("dash-attention")).toBeVisible();
  await expect(page.getByTestId("dash-risk")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("home.png"), fullPage: true });

  // the side navigation is fixed and always open on a desktop (decision G1-2: no hover-open rail, no pin)
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(page.getByTestId("sidebar")).toBeVisible();
  await expect(nav.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: "Start from proposal" })).toBeVisible();
  await expect(page.getByTestId("nav-pin")).toHaveCount(0);

  // a counter opens the list it counts: Projects, the table by default, with each project's owner
  await page.getByTestId("kpi-projects").click();
  await page.waitForURL(/\/projects$/);
  await expect(nav.getByRole("link", { name: "Projects" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId(`project-row-${projectId}`)).toContainText("Dashboardine");
  await page.getByTestId("projects-filter").fill("no-such-compound-xyz");
  await expect(page.getByText("No row matches.")).toBeVisible();
  await page.getByRole("button", { name: "Clear the filter" }).click();
  await expect(page.getByTestId(`project-row-${projectId}`)).toBeVisible();

  // the cards stay as an option: each card shows its four steps and opens the step that waits
  await page.getByTestId("dash-view-cards").click();
  const card = page.getByTestId(`project-card-${projectId}`);
  await expect(card.getByRole("list", { name: "Steps" }).getByRole("listitem")).toHaveCount(4);
  await expect(card).toHaveAttribute("href", new RegExp(`/projects/${projectId}/`));
  await page.getByTestId("dash-search").fill("no-such-compound-xyz");
  await expect(page.getByText("No projects match.")).toBeVisible();
  await page.getByRole("button", { name: "Clear the filters" }).click();
  await expect(card).toBeVisible();
  await page.getByTestId("dash-view-list").click();                       // back to the table (remembered in this browser)

  // inside a project, the sidebar holds its own pages, History among them
  await page.goto(`/projects/${projectId}/start`);
  await expect(page.getByTestId("nav-history")).toHaveAttribute("href", `/projects/${projectId}/history`);
});
