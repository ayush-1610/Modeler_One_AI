// A campaign waiting for a decision opens it on its project and campaign pages (the owner's request, 2026-10-17):
// nobody has to go to the review inbox to find it. The campaign state is seeded in the API's read root (software test
// data, no engine run); the decision itself is the inbox's signed decision (feedback.spec.ts).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

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

test("an escalation opens as a dialog on the project and campaign pages", async ({ page, request }) => {
  const { projectId, id } = await seed(request);
  await page.goto(`/projects/${projectId}`);
  const popup = page.getByTestId("escalation-popup");
  await expect(popup).toContainText(`campaign ${id}, stage S2`);
  await expect(popup.getByTestId("decision-select")).toBeVisible();      // the same signed decision as in the inbox

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
  await page.reload();                                                      // it is only closed for this visit
  await expect(popup).toBeVisible();

  await popup.getByTestId("escalation-later").click();
  await expect(popup).toHaveCount(0);

  await page.goto(`/campaigns/${id}`);
  await expect(page.getByTestId("escalation-popup")).toContainText("stage S2");
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
