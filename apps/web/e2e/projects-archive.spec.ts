// The Projects list (page review 1, the owner's decision 5 of 2026-10-29): archive, never delete. An archived project is
// hidden from the list, kept with who archived it and why, opened by its address, and restored with a reason.
import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

test("a project is archived with a reason, hidden, shown on request and restored; nothing is erased", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Archivamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nPBPK model.") } } });
  const projectId = (await started.json()).data.project_id as string;

  await page.goto("/");
  await page.getByTestId(`project-archive-${projectId}`).click();
  await expect(page.getByTestId("project-archive-confirm")).toBeDisabled();          // no reason, no archive
  await page.getByTestId("project-archive-reason").fill("a test project, not client work");
  await page.getByTestId("project-archive-confirm").click();
  await expect(page.getByTestId(`project-row-${projectId}`)).toHaveCount(0);        // hidden from the list …
  await page.getByTestId("projects-show-archived").click();
  await expect(page.getByTestId(`project-archived-${projectId}`)).toContainText("a test project, not client work");

  await page.goto(`/projects/${projectId}/start`);                                     // … and kept: it opens by its address
  await expect(page.getByTestId("start-drug-name")).toHaveText("Archivamide");

  await page.goto("/");
  await page.getByTestId("projects-show-archived").click();
  await page.getByTestId(`project-restore-${projectId}`).click();
  await page.getByTestId("project-archive-reason").fill("archived by mistake");
  await page.getByTestId("project-archive-confirm").click();
  await expect(page.getByTestId(`project-archived-${projectId}`)).toHaveCount(0);
  await expect(page.getByTestId(`project-archive-${projectId}`)).toBeVisible();

  const audit = await request.get(`/api/v1/projects/${projectId}/audit`, { headers: AUTH });
  const actions = ((await audit.json()).data.events as { action: string }[]).map((e) => e.action);
  expect(actions).toEqual(expect.arrayContaining(["project.archive", "project.restore"]));
});
