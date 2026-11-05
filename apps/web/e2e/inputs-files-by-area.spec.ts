// T-47: the client's files where their data belong (plan 2026-11-05 §3.1; the owner, 2026-11-05: "every data went into
// the clinical study section"). Each data area has its own "Add files"; a file is shown in the area its tag names, a
// name that says what it is wins over the area it was added on, and a file whose content reads otherwise says so on its
// card, to use or keep. The workbooks are written by a Python helper (software test data, never a model).
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

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

  // added on Products and dissolution: the dissolution workbook, and a BE workbook whose name says nothing
  await page.goto(`/projects/${projectId}/inputs?tab=formulations`);
  await expect(page.getByTestId("files-bar-formulations")).toContainText("No client file here yet");
  await page.getByTestId("client-upload-formulations").setInputFiles(
    ["Dissolution Test pH 6.8.xlsx", "230-23 Fasting Reference.xlsx"].map((f) => join(dir, f)));
  await expect(page.getByTestId("inputs-notice")).toContainText("2 files stored.");
  const here = page.getByTestId("formulations-client-files");
  await expect(here).toContainText("formulation and dissolution files (2)");
  await expect(here.getByTestId("client-file-Dissolution Test pH 6.8.xlsx")).toBeVisible();

  // the BE workbook's sheet holds plasma concentrations: its card says so, and "Use it" moves it to Clinical studies
  const be = here.getByTestId("client-file-230-23 Fasting Reference.xlsx");
  await expect(be.getByLabel("what 230-23 Fasting Reference.xlsx is")).toHaveValue("formulation");
  const reading = be.getByTestId("tag-proposal-230-23 Fasting Reference.xlsx");
  await expect(reading).toContainText("Its content reads as clinical study");
  await shot(page, "1-products-files");
  await reading.getByRole("button", { name: "Use it" }).click();
  await expect(page.getByTestId("inputs-notice")).toContainText("230-23 Fasting Reference.xlsx: clinical study, shown on Clinical studies");
  await expect(here).toContainText("formulation and dissolution files (1)");
  await page.getByTestId("tab-studies").click();
  await expect(page.getByTestId("studies-client-files").getByTestId("client-file-230-23 Fasting Reference.xlsx")).toBeVisible();
  await expect(page.getByTestId("files-bar-studies")).toContainText("1 client file here");

  // added on Clinical studies, a workbook named as dissolution still goes to Products and dissolution, by its name
  await page.getByTestId("client-upload-studies").setInputFiles(join(dir, "Dissolution RLD pH 6.8.xlsx"));
  await expect(page.getByTestId("inputs-notice")).toContainText(
    "Dissolution RLD pH 6.8.xlsx is shown on Products and dissolution, by its name");
  await expect(page.getByTestId("client-file-Dissolution RLD pH 6.8.xlsx")).toHaveCount(0);

  // the files view: every file, what it is, and the area it opens in
  await page.getByTestId("inputs-files").click();
  const drawer = page.getByTestId("inputs-files-drawer");
  await expect(drawer.getByTestId("inputs-file-Dissolution RLD pH 6.8.xlsx")).toContainText("Open on Products and dissolution");
  await shot(page, "2-files-view");
  await drawer.getByTestId("open-file-Dissolution RLD pH 6.8.xlsx").click();
  await expect(page.getByTestId("formulations-client-files")).toContainText("formulation and dissolution files (2)");
  await expect(page.getByTestId("client-file-Dissolution RLD pH 6.8.xlsx")).toBeVisible();

  // the compound area has its own "Add files" too (in vitro and physico-chemistry reports)
  await page.getByTestId("tab-compound").click();
  await expect(page.getByTestId("files-bar-compound")).toContainText("add the in vitro and physico-chemistry files");
});
