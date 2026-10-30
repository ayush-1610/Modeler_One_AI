// R3c: the client's sheets are read on the Inputs step's Studies tab, where the reading agent's proposals wait for the
// person. With agents off (as in this run) the agent's button is off and the reader opens on code's first filling; the
// agent's own proposals are covered by the API tests. The workbook is a sheet of the reading evaluation set
// (modeler_intake.reading_eval), written by a Python helper: software test data, never a model.
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

test("a client sheet is read and saved on the Studies tab, next to the reading agent's button", async ({ page, request }) => {
  const dir = mkdtempSync(join(tmpdir(), "reading-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "reading_eval_workbook.py"), dir, "published-mean"], { cwd: REPO });
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "Exampleamide", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral solution, 10 mg.") } },
  });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);      // Inputs opens once Start is done (page review 1, decision 7)
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const upload = await request.post(`/api/v1/projects/${projectId}/client-data`, { headers: AUTH, multipart: {
    files: { name: "Smith2015_Table2.xlsx", mimeType: XLSX, buffer: readFileSync(join(dir, "Smith2015_Table2.xlsx")) } } });
  expect(upload.status(), await upload.text()).toBe(201);

  await page.goto(`/projects/${projectId}/inputs`);
  await page.getByTestId("tab-studies").click();
  const sheets = page.getByTestId("studies-client-files");
  await expect(sheets).toContainText("Agents are off");
  await expect(sheets.getByTestId("read-agent-Smith2015_Table2.xlsx")).toBeDisabled();
  await expect(sheets.getByTestId("sheet-Mean PK")).toContainText("not read yet");

  await sheets.getByTestId("sheet-Mean PK").getByRole("button", { name: "Read this sheet" }).click();
  const reader = page.getByTestId("reader-Mean PK");
  await expect(reader.getByTestId("reading-source")).toContainText("Filled in first by code");
  await reader.getByLabel("dose", { exact: true }).fill("10");
  await reader.getByLabel("formulation", { exact: true }).selectOption("solution");
  await reader.getByLabel("food", { exact: true }).selectOption("fasted");
  await reader.getByLabel("subjects", { exact: true }).fill("12");
  await reader.getByLabel("study purpose", { exact: true }).selectOption("model_building");
  await reader.getByRole("button", { name: "Check what will be read" }).click();
  await expect(reader.getByTestId("read-result")).toContainText("ready to save");
  await shot(page, "1-reader-on-studies");
  await reader.getByRole("button", { name: "Save these data" }).click();

  await expect(page.getByTestId("inputs-notice")).toContainText("Mean PK: 1 dataset(s) for Smith2015 saved");
  await expect(sheets.getByTestId("sheet-Mean PK")).toContainText("read ✓");
  await expect(page.getByTestId("study-Smith2015")).toBeVisible();
  await shot(page, "2-studies-after-save");
});
