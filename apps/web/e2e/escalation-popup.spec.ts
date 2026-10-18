// A campaign waiting for a decision opens it on its project and campaign pages (the owner's request, 2026-10-17):
// nobody has to go to the review inbox to find it. The campaign state is seeded in the API's read root (software test
// data, no engine run); the decision itself is the inbox's signed decision (feedback.spec.ts).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

const AUTH = { Authorization: "Bearer dev" };

function upsert(file: string, key: string, row: Record<string, unknown>) {
  let rows: Record<string, unknown>[] = [];
  try { rows = JSON.parse(readFileSync(file, "utf-8"))[key] ?? []; } catch { /* first row */ }
  writeFileSync(file, JSON.stringify({ [key]: [...rows.filter((r) => r.id !== row.id), row] }));
}

test("an escalation opens as a dialog on the project and campaign pages", async ({ page, request }) => {
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

  await page.goto(`/projects/${projectId}`);
  const popup = page.getByTestId("escalation-popup");
  await expect(popup).toContainText(`campaign ${id}, stage S2`);
  await expect(popup.getByTestId("decision-select")).toBeVisible();      // the same signed decision as in the inbox
  await popup.getByTestId("escalation-later").click();
  await expect(popup).toHaveCount(0);

  await page.goto(`/campaigns/${id}`);
  await expect(page.getByTestId("escalation-popup")).toContainText("stage S2");
});
