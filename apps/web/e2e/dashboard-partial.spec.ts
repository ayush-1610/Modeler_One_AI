// The dashboard when part of what it reads fails (seen on the server, 2026-11-08: "The API answered HTTP 500"). It is the
// first page that reads every campaign at once, and one stored campaign in an earlier shape fails that whole read. The
// page still shows the projects, names the read that failed and what it leaves out, and never shows that figure as 0.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

test("a campaign list the API cannot answer leaves the dashboard up, says so, and shows no false 0", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Partialine", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nPBPK model.") } } });
  const projectId = (await started.json()).data.project_id as string;

  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  mkdirSync(root, { recursive: true });
  const file = join(root, "campaigns.json");
  const before = existsSync(file) ? readFileSync(file, "utf8") : null;
  const list = before ? (JSON.parse(before) as { campaigns: unknown[] }).campaigns : [];
  // a campaign as an earlier version wrote it: a key today's record does not know
  writeFileSync(file, JSON.stringify({ campaigns: [...list, {
    id: "camp-legacy", project: projectId, compound: "Partialine", question: "q", modelRisk: "medium", budgetSeconds: 1,
    elapsedSeconds: 0, currentStage: "S0", status: "COMPLETED", stages: [], legacyField: true }] }));
  try {
    expect((await request.get("/api/v1/campaigns", { headers: AUTH })).status()).toBe(500);    // the failure itself
    await page.goto("/");
    await expect(page.getByTestId(`project-card-${projectId}`)).toBeVisible();
    await expect(page.getByTestId("dash-partial")).toContainText("The campaigns could not be read");
    await expect(page.getByTestId("kpi-running-now")).toContainText("—");
    await expect(page.getByTestId("kpi-running-now")).toContainText("could not be read");
    await expect(page.getByTestId("api-problem")).toHaveCount(0);                              // not a page-wide failure
  } finally {
    if (before === null) writeFileSync(file, JSON.stringify({ campaigns: list })); else writeFileSync(file, before);
  }
});
