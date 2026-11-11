// A campaign waiting for a decision asks for it in place (the owner's requests of 2026-10-17 and 2026-11-11: the review
// inbox is gone), scoped by the owner's decision 1 of 2026-11-11 (docs/plans/2026-11-11-frontend-audit-2.md): the dialog
// opens by itself only on the campaign's own page and its project's pages; every other page shows the corner control
// with a count, which opens the dialog anywhere; "Decide later" holds for the rest of the tab's session. The campaign
// state is seeded in the API's read root (software test data, no engine run); the signed decision itself is
// feedback.spec.ts.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { dropEscalations } from "./fixtures/escalations";

const AUTH = { Authorization: "Bearer dev" };

function upsert(file: string, key: string, row: Record<string, unknown>) {
  let rows: Record<string, unknown>[] = [];
  try { rows = JSON.parse(readFileSync(file, "utf-8"))[key] ?? []; } catch { /* first row */ }
  writeFileSync(file, JSON.stringify({ [key]: [...rows.filter((r) => r.id !== row.id), row] }));
}

async function seed(request: APIRequestContext) {
  const created = await request.post("/api/v1/projects", { headers: AUTH, data: { name: `Popup ${Date.now()}`, compound: "Popupol" } });
  const projectId = (await created.json()).data.id as string;
  const id = `camp-popup-${Date.now()}`;
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
  return { projectId, id };
}

// the seeded decisions are never signed here: close them, or they would ask over the next specs' pages
test.afterAll(() => dropEscalations((r) => r.campaignId.startsWith("camp-popup-")));

test("an escalation asks on its own project, shows a count elsewhere, and \"Decide later\" holds for the tab", async ({ page, request, context }) => {
  const { projectId, id } = await seed(request);
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

  // the campaign's own project asks
  await page.goto(`/projects/${projectId}`);
  await expect(popup).toContainText(`campaign ${id}, stage S2`);
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
  await expect(popup).toContainText(`campaign ${id}, stage S2`);
  await expect(waiting).toHaveCount(0);
  await popup.getByTestId("escalation-later").click();
  await expect(waiting).toBeVisible();

  // sessionStorage is per tab: a new tab on the campaign's page asks again
  const tab = await context.newPage();
  await tab.goto(`/campaigns/${id}`);
  await expect(tab.getByTestId("escalation-popup")).toContainText(`campaign ${id}, stage S2`);
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
  await expect(popup).toContainText(`campaign ${id}, stage S3`);           // and the decision is asked all the same
  await expect(popup.getByTestId("decision-select")).toBeVisible();
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
