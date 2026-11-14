// T-47: the client's files where their data belong (plan 2026-11-05 §3.1; the owner, 2026-11-05: "every data went into
// the clinical study section"). Files are added for an area from the head's "Add data" (plan 2026-11-14 slice 1); each
// is listed once, in Client files, filed under the area its tag names; a name that says what it is wins over the area it
// was added for, and a file whose content reads otherwise says so on its row, to use or keep. The workbooks are written
// by a Python helper (software test data, never a model).
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { finishStart, openFile } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const AUTH = { Authorization: "Bearer dev" };

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

test("files are added where their data belong, shown there, and moved by saying what they are", async ({ page, request }) => {
  const dir = mkdtempSync(join(tmpdir(), "by-area-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "er_be_workbooks.py"), dir], { cwd: REPO });
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "desvenlafaxine", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nER tablet 50 mg, VBE.") } },
  });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();

  // added for Products and dissolution: the dissolution workbook, and a BE workbook whose name says nothing
  await page.goto(`/projects/${projectId}/inputs?tab=formulations`);
  await page.getByTestId("inputs-add-data").click();
  await expect(page.getByTestId("add-files-formulations")).toBeVisible();          // the head's menu: one entry per area
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("add-files-formulations")).toBeHidden();
  await page.getByTestId("client-upload-formulations").setInputFiles(
    ["Dissolution Test pH 6.8.xlsx", "230-23 Fasting Reference.xlsx"].map((f) => join(dir, f)));
  await expect(page.getByTestId("inputs-notice")).toContainText("2 files stored.");
  await expect(page.getByTestId("tab-files")).toContainText("2");
  await page.getByTestId("tab-files").click();
  // one row per file, filed under the area of its data; its name opens its sheets under the row
  const table = page.getByTestId("files-table");
  const dissolution = table.getByTestId("open-file-Dissolution Test pH 6.8.xlsx");
  await expect(dissolution).toHaveText("Products and dissolution");
  await expect(page.getByTestId("client-file-Dissolution Test pH 6.8.xlsx")).toHaveCount(0);
  await openFile(page, "Dissolution Test pH 6.8.xlsx");

  // the BE workbook's sheet holds plasma concentrations: its row says so, and "Use it" files it under Clinical studies
  const be = table.getByTestId("inputs-file-230-23 Fasting Reference.xlsx");
  await expect(be.getByLabel("what 230-23 Fasting Reference.xlsx is")).toHaveValue("formulation");
  await expect(be.getByTestId("open-file-230-23 Fasting Reference.xlsx")).toHaveText("Products and dissolution");
  const reading = be.getByTestId("tag-proposal-230-23 Fasting Reference.xlsx");
  await expect(reading).toContainText("Its content reads as clinical study");
  await shot(page, "1-products-files");
  await reading.getByRole("button", { name: "Use it" }).click();
  await expect(page.getByTestId("inputs-notice")).toContainText("230-23 Fasting Reference.xlsx: clinical study, filed under Clinical studies");
  await expect(be.getByTestId("open-file-230-23 Fasting Reference.xlsx")).toHaveText("Clinical studies");

  // added for Clinical studies, a workbook named as dissolution is still filed under Products and dissolution, by its name
  await page.getByTestId("client-upload-studies").setInputFiles(join(dir, "Dissolution RLD pH 6.8.xlsx"));
  await expect(page.getByTestId("inputs-notice")).toContainText(
    "Dissolution RLD pH 6.8.xlsx is filed under Products and dissolution, by its name");
  await expect(table.getByTestId("open-file-Dissolution RLD pH 6.8.xlsx")).toHaveText("Products and dissolution");
  await expect(page.getByTestId("client-file-Dissolution Test pH 6.8.xlsx")).toBeVisible();      // an open row stays open
  await openFile(page, "Dissolution RLD pH 6.8.xlsx");
  await shot(page, "2-files-view");
  await table.getByTestId("open-file-Dissolution RLD pH 6.8.xlsx").click();
  await expect(page.getByTestId("tab-formulations")).toHaveAttribute("aria-selected", "true");

  // the compound's files are added the same way (in vitro and physico-chemistry reports)
  await page.getByTestId("inputs-add-data").click();
  await expect(page.getByTestId("add-files-compound")).toContainText("In vitro and physico-chemistry files");
});
