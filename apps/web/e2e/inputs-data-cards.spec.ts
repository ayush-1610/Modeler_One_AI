// T-47: the client's data reviewed one study at a time, as data (build C, plan 2026-11-05 §3.2; the owner, 2026-11-05:
// "one by one study/product/data, easy to review"). With more than three studies, an index names each, the first to
// confirm is open and the others are folded; each opens from the index. The workbook is written by a Python helper
// (software test data, never a model).
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const AUTH = { Authorization: "Bearer dev" };
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

test("a delivery with four studies is reviewed one study at a time, each as data", async ({ page, request }) => {
  const dir = mkdtempSync(join(tmpdir(), "four-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "four_studies.py"), dir], { cwd: REPO });
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Cardamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 10 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const up = await request.post(`/api/v1/projects/${projectId}/client-data`, { headers: AUTH, multipart: {
    files: { name: "four-studies.xlsx", mimeType: XLSX, buffer: readFileSync(join(dir, "four-studies.xlsx")) } } });
  expect(up.status(), await up.text()).toBe(201);

  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  // the client-data template, sent with no tag, is shown with the studies (it holds every kind of data)
  await expect(page.getByTestId("studies-client-files").getByTestId("client-file-four-studies.xlsx")).toBeVisible();
  await expect(page.getByTestId("files-unplaced")).toHaveCount(0);
  const index = page.getByTestId("group-index");
  for (const s of ["CL-1", "CL-2", "CL-3", "CL-4"]) await expect(index.getByTestId(`index-study:${s}`)).toBeVisible();
  // the first to confirm is open, as data; the others are folded
  const first = page.getByTestId("group-study:CL-1");
  await expect(first.getByTestId("profile-chart")).toBeVisible();
  await expect(first.getByTestId("dataset-stats")).toContainText("41");                 // Cmax of CL-1's mean profile
  await expect(page.getByTestId("group-study:CL-3").getByTestId("profile-chart")).toHaveCount(0);
  await expect(page.getByTestId("toggle-study:CL-3")).toHaveText("Open");
  await shot(page, "1-one-study-at-a-time");
  // any study opens from the index, with its own data
  await index.getByTestId("index-study:CL-3").click();
  const third = page.getByTestId("group-study:CL-3");
  await expect(third.getByTestId("dataset-stats")).toContainText("123");                // 3 × 41
  // confirming the open one moves to the next to confirm
  await first.getByTestId("confirm-study:CL-1").click();
  await expect(first).toContainText("Confirmed by");
  await expect(page.getByTestId("group-study:CL-2").getByTestId("profile-chart")).toBeVisible();
});
