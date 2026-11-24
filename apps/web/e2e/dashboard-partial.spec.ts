// Home (earlier the dashboard) when part of what it reads cannot be read (seen on the server, 2026-11-08 and again 2026-11-24: "The
// campaigns could not be read (The API answered HTTP 500)"). It is the first page that reads every campaign at once, and
// one stored campaign in an earlier shape failed that whole read. Now a key this version does not know is left out, and a
// campaign that still does not read is named on the page with why; the rest of the list stands and is counted.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

test("a campaign stored in an earlier shape no longer fails the list; one that cannot be read is named", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Partialine", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nPBPK model.") } } });
  const projectId = (await started.json()).data.project_id as string;

  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  mkdirSync(root, { recursive: true });
  const file = join(root, "campaigns.json");
  const before = existsSync(file) ? readFileSync(file, "utf8") : null;
  const list = before ? (JSON.parse(before) as { campaigns: unknown[] }).campaigns : [];
  const legacyId = `camp-legacy-${projectId}`;
  const brokenId = `camp-broken-${projectId}`;
  const campaign = { project: projectId, compound: "Partialine", question: "q", modelRisk: "medium", budgetSeconds: 1,
                     elapsedSeconds: 0, currentStage: "S0", stages: [] };
  writeFileSync(file, JSON.stringify({ campaigns: [...list,
    // as an earlier version wrote it: a key today's record does not know (once a 500 for the whole list)
    { ...campaign, id: legacyId, status: "COMPLETED", legacyField: true },
    // a key today's record needs is missing: it cannot be shown, so it is named
    { ...campaign, id: brokenId }] }));
  try {
    const answer = await request.get("/api/v1/campaigns", { headers: AUTH });
    expect(answer.status()).toBe(200);
    const data = (await answer.json()).data as { campaigns: { id: string }[]; unreadable: { id: string }[] };
    expect(data.campaigns.map((c) => c.id)).toContain(legacyId);
    expect(data.unreadable.map((u) => u.id)).toEqual([brokenId]);
    await page.goto("/");
    await expect(page.getByTestId("home-projects").getByTestId(`project-row-${projectId}`)).toBeVisible();
    await expect(page.getByTestId("dash-partial")).toContainText(`One campaign was stored in a shape this version cannot read`);
    await expect(page.getByTestId("dash-partial")).toContainText(brokenId);
    await expect(page.getByTestId("dash-partial")).not.toContainText("The campaigns could not be read");
    await expect(page.getByTestId("kpi-running-now")).not.toContainText("could not be read");  // the rest is counted
    await expect(page.getByTestId("api-problem")).toHaveCount(0);                              // not a page-wide failure
  } finally {
    if (before === null) writeFileSync(file, JSON.stringify({ campaigns: list })); else writeFileSync(file, before);
  }
});
