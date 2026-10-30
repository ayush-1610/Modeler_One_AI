// The project document library (docs/plans/2026-10-28-project-document-library.md, PR 1): reached from the sidebar of an
// open project, every document with who added it and what the project took from it; searched, filtered and opened.
import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

test("the library lists each document with what cites it, and finds, filters and opens one", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Librarimide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nfu was 9 % in human plasma.") } } });
  const projectId = (await started.json()).data.project_id as string;
  const docs = (await (await request.get(`/api/v1/projects/${projectId}/documents`, { headers: AUTH })).json()).data.documents;
  const sha = docs.find((d: { role: string }) => d.role === "proposal").sha256 as string;
  await request.post(`/api/v1/projects/${projectId}/documents`, { headers: AUTH, multipart: {
    role: "annex", files: { name: "annex.md", mimeType: "text/markdown", buffer: Buffer.from("# Annex\nNothing used.") } } });
  // a value read from the proposal, cited to its page
  const fu = await request.post(`/api/v1/projects/${projectId}/evidence`, { headers: AUTH, data: {
    req_id: "REQ-bind.fu", target: "bind.fu", value: 9, unit: "%", source_type: "PUBLICATION", doc_sha256: sha, page: 1,
    quote: "fu was 9 % in human plasma", conditions: { species: "human", matrix: "plasma" } } });
  expect(fu.ok(), await fu.text()).toBeTruthy();

  await page.goto(`/projects/${projectId}/start`);
  await page.getByTestId("nav-library").click();
  await page.waitForURL(/\/library$/);
  const proposal = page.getByTestId("library-row-proposal.md");
  await expect(proposal).toContainText("bind.fu = 9 %");
  await expect(page.getByTestId("library-row-annex.md")).toContainText("Nothing taken from it yet");
  await page.getByTestId("library-search").fill("bind.fu");
  await expect(page.getByTestId("library-row-annex.md")).toHaveCount(0);
  await page.getByTestId("library-search").fill("");
  await page.getByTestId("library-role").selectOption("annex");
  await expect(proposal).toHaveCount(0);
  await page.getByTestId("library-role").selectOption("");
  await page.screenshot({ path: test.info().outputPath("library.png"), fullPage: true });
  await page.getByTestId("library-open-proposal.md").click();
  await expect(page.getByTestId("library-viewer")).toContainText("fu was 9 % in human plasma");
});
