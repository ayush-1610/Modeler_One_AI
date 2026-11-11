// The dashboard and the sidebar (plan 2026-11-06-app-design-merge §3 A): every number is read from the API, each
// project's card shows its four steps and opens the step that waits, and the sidebar is a rail that opens on hover and can be pinned.
import { expect, test } from "@playwright/test";

import { dropEscalations, seedReadRoot } from "./fixtures/escalations";
import { AUTH } from "./fixtures/inputs";

test("the dashboard reads each project's steps, filters by them, and the sidebar opens and pins", async ({ page, request }) => {
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

  // the sidebar is a rail that opens over the page on hover and can be pinned open; the pin survives a reload
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(page.getByTestId("sidebar")).not.toHaveClass(/open/);
  // named on the rail too (this was the "Review inbox" link, removed 2026-11-11; escalation-popup.spec.ts checks that an
  // escalation's attention item opens its campaign)
  await expect(nav.getByRole("link", { name: "Start from proposal" })).toBeVisible();
  await page.getByTestId("sidebar").hover();
  await expect(page.getByTestId("sidebar")).toHaveClass(/open/);
  await page.getByTestId("nav-pin").click();
  await page.mouse.move(900, 600);
  await expect(page.getByTestId("sidebar")).toHaveClass(/pinned/);
  await page.reload();
  await expect(page.getByTestId("sidebar")).toHaveClass(/pinned/);
  await page.screenshot({ path: test.info().outputPath("dashboard-pinned.png") });
  await page.getByTestId("nav-pin").click();
  await page.mouse.move(900, 600);
  await expect(page.getByTestId("sidebar")).not.toHaveClass(/pinned/);

  // inside a project, the sidebar holds its own pages, History among them
  await page.goto(`/projects/${projectId}/start`);
  await expect(page.getByTestId("nav-history")).toHaveAttribute("href", `/projects/${projectId}/history`);
});

// Decision 1 of 2026-11-11: the dashboard is not a campaign's own page, so an open escalation never opens its dialog
// here by itself; the corner control counts it, and opens the dialog on this page (software test data in the read root).
test("the dashboard counts a waiting decision and never opens its dialog by itself", async ({ page, request }) => {
  const name = `Dash decision ${Date.now()}`;
  const created = await request.post("/api/v1/projects", { headers: AUTH, data: { name, compound: "Dashol" } });
  const projectId = (await created.json()).data.id as string;
  const id = `camp-dash-${Date.now()}`;
  const stage = (s: string, status: string) => ({ stage: s, label: s, status, rounds: [], notes: [] });
  seedReadRoot("campaigns", {
    id, project: projectId, compound: "Dashol", question: "exposure", modelRisk: "medium", budgetSeconds: 3600,
    elapsedSeconds: 60, currentStage: "S2", status: "ESCALATED", stages: [stage("S0", "PASSED"), stage("S2", "ESCALATED")],
    gof: [], engine: { kind: "software-fixture", command: "seeded" },
  });
  seedReadRoot("escalations", {
    id: `${id}-S2`, campaignId: id, stage: "S2", reasonCode: "ROUNDS_EXHAUSTED", evidence: "Seeded for the dashboard test.",
    options: [{ id: "abort", label: "Stop the campaign", requiresSignature: true }],
  });
  try {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
    const waiting = page.getByTestId("escalation-waiting");
    await expect(waiting).toContainText(/\d+ decisions? waiting · Open/);
    await expect(page.getByTestId("escalation-popup")).toHaveCount(0);
    // the project's next action is the decision, on the campaign's page, and it is listed once in "Needs your attention",
    // by the escalation, in words (item 5 of the 2026-11-11 audit)
    const card = page.getByTestId(`project-card-${projectId}`);
    await expect(card).toContainText("Make the decision");
    await expect(card).toHaveAttribute("href", `/campaigns/${id}`);
    const listed = page.getByTestId("dash-attention").getByRole("link").filter({ hasText: name });
    await expect(listed).toHaveCount(1);
    await expect(listed).toContainText("Rounds exhausted");
    await waiting.click();
    await expect(page.getByTestId("escalation-popup")).toBeVisible();     // still decidable from here
  } finally {
    dropEscalations((r) => r.campaignId === id);
  }
});
