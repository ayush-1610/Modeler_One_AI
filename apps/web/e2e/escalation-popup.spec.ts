// A campaign waiting for a decision (the console redesign, slice 2): a flash bar on its project's pages and on the
// campaign's own page, for the people who may decide it, and the signed decision opens from there; Your work and Home
// list it as a link. Nothing opens by itself over another page (before: a pop-up on every page). The campaign state is
// seeded in the API's read root (software test data, no engine run); the signed decision itself is feedback.spec.ts.
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

// the seeded decisions are never signed here: close them, or they would wait in the next specs' Your work
test.afterAll(() => dropEscalations((r) => r.campaignId.startsWith("camp-popup-")));

test("an escalation shows a flash bar on its project's pages, the decision opens from it, and nothing opens by itself", async ({ page, request }) => {
  const { projectId, id } = await seed(request);
  await page.goto(`/projects/${projectId}`);
  const flash = page.getByTestId("escalation-flash");
  const popup = page.getByTestId("escalation-popup");
  await expect(flash).toContainText(`Campaign ${id}, stage S2`);
  await expect(popup).toHaveCount(0);                                       // it waits to be opened
  await page.getByTestId("escalation-waiting").click();
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
  await expect(page.getByTestId("escalation-waiting")).toBeFocused();      // focus on the way back, not lost to the page
  await page.reload();
  await expect(flash).toBeVisible();
  await expect(popup).toHaveCount(0);                                       // a reload asks nothing by itself either

  // a page that has nothing to do with the campaign shows nothing
  await page.goto("/projects/start");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(flash).toHaveCount(0);
  await expect(popup).toHaveCount(0);

  // Home and Your work list it as a link to the campaign; nothing is decided there
  await page.goto("/");
  await expect(page.getByTestId("dash-attention").locator(`a[href="/campaigns/${id}"]`)).toBeVisible();
  await page.goto("/work");
  const open = page.getByTestId(`work-open-esc-${id}-S2`);
  await expect(open).toHaveAttribute("href", `/campaigns/${id}`);
  await open.click();

  // the campaign's own page asks for its own decision
  await page.waitForURL(new RegExp(`/campaigns/${id}$`));
  await expect(flash).toContainText(`Campaign ${id}, stage S2`);
  await page.getByTestId("escalation-waiting").click();
  await expect(popup).toContainText(`campaign ${id}, stage S2`);
});

test("a campaign whose record cannot be read can still be decided", async ({ page }) => {
  // an escalation whose campaign the API does not know: Your work links to the campaign's page, which asks for it
  const id = `camp-popup-orphan-${Date.now()}`;
  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  upsert(join(root, "escalations.json"), "escalations", {
    id: `${id}-S3`, campaignId: id, stage: "S3", reasonCode: "ROUNDS_EXHAUSTED", evidence: "Seeded: no campaign record.",
    options: [{ id: "abort", label: "Stop the campaign", requiresSignature: true }],
  });
  await page.goto("/work");
  await expect(page.getByTestId(`work-row-esc-${id}-S3`)).toContainText("Campaign not recorded yet");
  await page.goto(`/campaigns/${id}`);
  await expect(page.getByTestId("campaign-pending")).toBeVisible();        // the page says the campaign is not recorded
  await page.getByTestId("escalation-waiting").click();
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
  await page.getByTestId("escalation-waiting").first().click();
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
