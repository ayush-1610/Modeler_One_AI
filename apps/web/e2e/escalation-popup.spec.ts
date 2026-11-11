// A campaign waiting for a decision asks for it in place (the owner's requests of 2026-10-17 and 2026-11-11: the review
// inbox is gone), scoped by the owner's decision 1 of 2026-11-11 (docs/plans/2026-11-11-frontend-audit-2.md): the dialog
// opens by itself only on the campaign's own page and its project's pages; every other page shows the corner control
// with a count, which opens the dialog anywhere; "Decide later" holds for the rest of the tab's session. The campaign
// state is seeded in the API's read root (software test data, no engine run); the signed decision itself is
// feedback.spec.ts.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type Locator } from "@playwright/test";

import { dropEscalations } from "./fixtures/escalations";

const AUTH = { Authorization: "Bearer dev" };

function upsert(file: string, key: string, row: Record<string, unknown>) {
  let rows: Record<string, unknown>[] = [];
  try { rows = JSON.parse(readFileSync(file, "utf-8"))[key] ?? []; } catch { /* first row */ }
  writeFileSync(file, JSON.stringify({ [key]: [...rows.filter((r) => r.id !== row.id), row] }));
}

async function seed(request: APIRequestContext, more = 0) {
  const name = `Popup ${Date.now()}`;
  const created = await request.post("/api/v1/projects", { headers: AUTH, data: { name, compound: "Popupol" } });
  const projectId = (await created.json()).data.id as string;
  const id = `camp-popup-${Date.now()}`;
  for (let i = 1; i <= more; i++) seedOne(projectId, `camp-popup-more${i}-${Date.now()}`);
  seedOne(projectId, id);
  return { projectId, id, name };
}

function seedOne(projectId: string, id: string) {
  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  mkdirSync(root, { recursive: true });
  const stage = (s: string, status: string) => ({ stage: s, label: s, status, rounds: [], notes: [] });
  upsert(join(root, "campaigns.json"), "campaigns", {
    id, project: projectId, compound: "Popupol", question: "exposure", modelRisk: "medium", budgetSeconds: 3600,
    elapsedSeconds: 60, currentStage: "S2", status: "ESCALATED", stages: [stage("S0", "PASSED"), stage("S2", "ESCALATED")],
    gof: [], engine: { kind: "software-fixture", command: "seeded" },
  });
  upsert(join(root, "escalations.json"), "escalations", {
    id: `${id}-S2`, campaignId: id, stage: "S2", reasonCode: "ROUNDS_EXHAUSTED", evidence: "Seeded for the pop-up test.",
    options: [{ id: "abort", label: "Stop the campaign", requiresSignature: true }],
  });
}

// The dialog asks about this campaign and stage (item 5 of the 2026-11-11 audit: the title names the project and the
// stage, the campaign's id is on its own line under it; it was "campaign <id>, stage <stage>" in the title)
async function asks(popup: Locator, id: string, stage: string) {
  await expect(popup.getByTestId("escalation-campaign")).toContainText(id);
  await expect(popup.locator(".dialog-title")).toContainText(`stage ${stage}`);
}

// the seeded decisions are never signed here: close them, or they would ask over the next specs' pages
test.afterAll(() => dropEscalations((r) => r.campaignId.startsWith("camp-popup-")));

test("an escalation asks on its own project, shows a count elsewhere, and \"Decide later\" holds for the tab", async ({ page, request, context }) => {
  const { projectId, id, name } = await seed(request);
  const other = await request.post("/api/v1/projects", { headers: AUTH, data: { name: `Popup other ${Date.now()}`, compound: "Otherol" } });
  const otherId = (await other.json()).data.id as string;
  const popup = page.getByTestId("escalation-popup");
  const waiting = page.getByTestId("escalation-waiting");

  // (this test replaces the 2026-11-11 rule "asks on any page": decision 1 of the 2026-11-11 audit scopes it)
  // another project's pages, Start and the dashboard show the count, and no dialog takes the page (the control renders
  // only once the open escalations are placed on the page, so its presence means the dialog was not asked here)
  for (const url of [`/projects/${otherId}`, "/projects/start", "/"]) {
    await page.goto(url);
    await expect(waiting).toContainText(/\d+ decisions? waiting · Open/);
    await expect(popup).toHaveCount(0);
  }
  // the dashboard's attention item opens the campaign, no longer the review inbox
  await expect(page.getByTestId("dash-attention").locator(`a[href="/campaigns/${id}"]`)).toBeVisible();

  // the campaign's own project asks, naming the project and the stage, and saying the numbers came from a software fixture
  await page.goto(`/projects/${projectId}`);
  await asks(popup, id, "S2");
  await expect(popup.locator(".dialog-title")).toContainText(name);
  await expect(popup.getByTestId("decision-engine-warning")).toContainText("Not a PBPK result");
  await expect(popup.getByTestId("decision-missing")).toContainText("Choose a decision");
  await expect(popup.getByTestId("decision-select")).toBeVisible();      // the signed decision (feedback.spec.ts)

  // the dialog behaves as one: named by its title, focus inside, Tab kept in, Escape closes the innermost only
  const named = page.getByRole("dialog", { name: /Your decision is needed/ });
  await expect(named).toBeFocused();
  for (let i = 0; i < 12; i++) await page.keyboard.press("Tab");
  expect(await popup.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  await popup.getByTestId("decision-select").selectOption("abort");
  await popup.getByTestId("decision-sign").click();
  const confirm = page.getByTestId("decision-confirm-dialog");
  await expect(page.getByRole("dialog", { name: "Electronic signature" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(confirm).toHaveCount(0);
  await expect(popup).toBeVisible();                                        // only the signature dialog closed
  await expect(popup.getByTestId("decision-sign")).toBeFocused();          // and focus went back where it was
  await page.keyboard.press("Escape");                                      // "Decide later"
  await expect(popup).toHaveCount(0);
  await expect(waiting).toContainText("waiting · Open");                    // a way back, without a reload
  await expect(waiting).toBeFocused();                                      // and focus is on it, not lost to the page

  // "Decide later" holds for the tab's session: a reload, and a deep link to the campaign itself, show the count only
  await page.reload();
  await expect(waiting).toBeVisible();
  await expect(popup).toHaveCount(0);
  await page.goto(`/campaigns/${id}`);
  await expect(waiting).toBeVisible();
  await expect(popup).toHaveCount(0);
  // the campaign's page says what it waits for, and opens the decision again
  await expect(page.getByTestId("escalation-pending")).toContainText("Stage S2 is waiting for your signed decision: Rounds exhausted");
  await page.getByTestId("escalation-pending").getByTestId("open-decision").click();
  await asks(popup, id, "S2");
  await popup.getByTestId("escalation-later").click();
  await expect(popup).toHaveCount(0);
  // and so does its row in the project's Campaigns table
  await page.goto(`/projects/${projectId}`);
  await page.getByRole("row", { name: new RegExp(id) }).getByTestId("open-decision").click();
  await asks(popup, id, "S2");
  await popup.getByTestId("escalation-later").click();
  await page.goto(`/campaigns/${id}`);
  await expect(waiting).toBeVisible();
  // the control stays on the next page too (the sidebar's link: the layout, and what was put off, stay)
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Projects" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(waiting).toBeVisible();
  await expect(popup).toHaveCount(0);

  // the control is reached by the keyboard (it is in the tab order, right after the skip link) and opens the dialog here
  let reached = false;
  for (let i = 0; i < 10 && !reached; i++) {
    await page.keyboard.press("Tab");
    reached = await waiting.evaluate((el) => el === document.activeElement);
  }
  expect(reached).toBe(true);
  await page.keyboard.press("Enter");
  await asks(popup, id, "S2");
  await expect(waiting).toHaveCount(0);
  await popup.getByTestId("escalation-later").click();
  await expect(waiting).toBeVisible();

  // sessionStorage is per tab: a new tab on the campaign's page asks again
  const tab = await context.newPage();
  await tab.goto(`/campaigns/${id}`);
  await asks(tab.getByTestId("escalation-popup"), id, "S2");
  await tab.close();
});

test("a dialog that would open after the person has started using the page goes to the count instead", async ({ page, request }) => {
  const { projectId } = await seed(request);
  // hold the first escalations read back until the person has clicked on the page
  let release!: () => void;
  const held = new Promise<void>((r) => { release = r; });
  await page.route("**/api/v1/escalations*", async (route) => { await held; await route.continue(); });
  await page.goto(`/projects/${projectId}`);
  await page.locator("h1").first().click();                                 // a click already made when the dialog would arrive
  release();
  await expect(page.getByTestId("escalation-waiting")).toBeVisible();
  await expect(page.getByTestId("escalation-popup")).toHaveCount(0);
  await page.unroute("**/api/v1/escalations*");
  // the decision stays one click away
  await page.getByTestId("escalation-waiting").click();
  await expect(page.getByTestId("escalation-popup")).toBeVisible();
});

test("a campaign whose record cannot be read can still be decided", async ({ page }) => {
  // an escalation whose campaign the API does not know: the pop-up reads only the open escalations
  const id = `camp-popup-orphan-${Date.now()}`;
  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  upsert(join(root, "escalations.json"), "escalations", {
    id: `${id}-S3`, campaignId: id, stage: "S3", reasonCode: "ROUNDS_EXHAUSTED", evidence: "Seeded: no campaign record.",
    options: [{ id: "abort", label: "Stop the campaign", requiresSignature: true }],
  });
  await page.goto(`/campaigns/${id}`);
  await expect(page.getByTestId("campaign-pending")).toBeVisible();        // the page says the campaign is not recorded
  const popup = page.getByTestId("escalation-popup");
  await asks(popup, id, "S3");                                              // and the decision is asked all the same
  await expect(popup.getByTestId("decision-select")).toBeVisible();
  // saying that the engine its numbers came from is not known
  await expect(popup.getByTestId("decision-engine-unknown")).toBeVisible({ timeout: 30_000 });
});

test("the signing step-up opens over the decision, is named, and Escape cancels it", async ({ page, request }) => {
  const { projectId } = await seed(request);
  // the API's refusal for a signature without a recent step-up (the Keycloak sign-in itself is oidc-signing.spec.ts)
  await page.route("**/escalation:resolve", (route) => route.fulfill({
    status: 403, contentType: "application/json",
    body: JSON.stringify({ detail: { code: "STEP_UP_REQUIRED", message: "Confirm your identity to sign." } }),
  }));
  await page.goto(`/projects/${projectId}`);
  const popup = page.getByTestId("escalation-popup");
  await popup.getByTestId("decision-select").selectOption("abort");
  await popup.getByTestId("decision-sign").click();
  await page.getByTestId("decision-confirm").click();

  const stepUp = page.getByRole("dialog", { name: "Confirm your identity to sign" });
  await expect(stepUp).toBeVisible();
  await expect(stepUp).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("step-up-dialog")).toHaveCount(0);
  await expect(popup).toBeVisible();                                        // the decision was not lost
  await expect(popup).toContainText("Confirm your identity to sign.");     // and says why it was not signed
});

// Item 5 of the 2026-11-11 audit: a signed decision stays on screen with its signature until the person moves on; the
// next decision (which may be another project's) never replaces it by itself. The API's answer is stubbed here (a
// seeded campaign has nothing to resume); the signed decision itself is feedback.spec.ts.
test("a decided escalation keeps its signed result on screen until \"Next decision\" or \"Close\"", async ({ page, request }) => {
  const { projectId } = await seed(request, 1);
  await page.route("**/escalation:resolve", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    // the route answers without the envelope (lib/api.ts post)
    body: JSON.stringify({ status: "ABORTED", signature: { manifestation: "E2E Tester · Approved · 2026-11-11T00:00:00Z" } }),
  }));
  await page.goto(`/projects/${projectId}`);
  const popup = page.getByTestId("escalation-popup");
  await expect(popup).toContainText("1 more after this one");
  const first = await popup.getByTestId("escalation-campaign").locator("code").textContent();
  await popup.getByTestId("decision-select").selectOption("abort");
  await expect(popup.getByTestId("decision-missing")).toHaveCount(0);
  await popup.getByTestId("decision-sign").click();
  await page.getByTestId("decision-confirm").click();

  await expect(popup.getByTestId("decision-recorded")).toContainText("Signed: E2E Tester · Approved");
  await expect(page.getByRole("dialog", { name: /^Decision recorded/ })).toBeVisible();
  await expect(popup.getByTestId("escalation-close")).toBeFocused();       // focus on Close, never on the next decision
  await expect(popup.getByTestId("decision-select")).toHaveCount(0);
  await popup.getByTestId("escalation-next").click();                      // the next one only on this click
  await expect(page.getByRole("dialog", { name: /^Your decision is needed/ })).toBeVisible();
  await expect(popup.getByTestId("escalation-campaign")).not.toContainText(first!);
  expect(first).toMatch(/^camp-popup-/);
});

test("the decision dialog fits a phone: the title wraps and the page does not scroll sideways", async ({ page, request }) => {
  const { projectId } = await seed(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${projectId}`);
  const popup = page.getByTestId("escalation-popup");
  await expect(popup.getByTestId("decision-select")).toBeVisible();
  const box = await popup.locator(".dialog").evaluate((el) => ({
    sw: el.scrollWidth, cw: el.clientWidth, bottom: el.getBoundingClientRect().bottom, vh: window.innerHeight,
  }));
  expect(box.sw).toBeLessThanOrEqual(box.cw);                               // nothing in the dialog runs off its right edge
  expect(box.bottom).toBeLessThanOrEqual(box.vh);                           // its action row stays on the screen
  const title = await popup.locator(".dialog-title").evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth }));
  expect(title.sw).toBeLessThanOrEqual(title.cw);
  // the action row: "Decide later" and "Sign & submit" side by side, in the dialog's own row
  await expect(popup.locator(".dialog-actions").getByTestId("escalation-later")).toBeVisible();
  await expect(popup.locator(".dialog-actions").getByTestId("decision-sign")).toBeVisible();
});
