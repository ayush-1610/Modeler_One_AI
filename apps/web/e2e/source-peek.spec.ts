// The source peek (docs/plans/2026-11-03-inputs-and-client-data.md §3.3; the owner, 2026-11-03): the icon at the top
// right of a value's card opens its source in the centre of the screen; a sheet shows as its grid with the cited cells
// highlighted. Software test data, never a model.
import { expect, test } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

const AUTH = { Authorization: "Bearer dev" };
const SHEET = "Assay,Species,fu\nPPB,Rat,0.12\nPPB,Human,0.09\n";

test("a value read from a client sheet opens in the centre peek with its cell highlighted", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Peekamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nAn IR tablet.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const docs = await request.post(`/api/v1/projects/${projectId}/documents`, { headers: AUTH, multipart: {
    role: "client_file", files: { name: "ppb.csv", mimeType: "text/csv", buffer: Buffer.from(SHEET) } } });
  const sha = (await docs.json()).data.documents[0].sha256 as string;
  const value = await request.post(`/api/v1/projects/${projectId}/evidence`, { headers: AUTH, data: {
    req_id: "REQ-bind.fu", target: "bind.fu", value: 0.09, source_type: "CLIENT_FILE", doc_sha256: sha, page: 1,
    locator: "ppb!C3", title: "ppb.csv", quote: "[ppb row 3] A3=PPB | B3=Human | C3=0.09" } });
  expect(value.status(), await value.text()).toBe(201);

  await page.goto(`/projects/${projectId}/inputs`);
  await page.getByTestId("peek-bind.fu").click();
  const peek = page.getByTestId("source-peek");
  await expect(peek.getByRole("dialog", { name: /Source of/ })).toBeVisible();
  await expect(peek.getByRole("region", { name: "Sheet ppb" })).toBeVisible();
  await expect(peek.locator("td.cited")).toHaveCount(3);                     // the quoted row's cells
  await expect(peek.locator("td.cited").last()).toHaveText("0.09");
  await page.screenshot({ path: test.info().outputPath("source-peek-sheet.png") });
  await page.mouse.click(8, 8);                                              // a click on the dimmed page closes it
  await expect(peek).toHaveCount(0);
});
