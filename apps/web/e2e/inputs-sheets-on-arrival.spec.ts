// T-47: each client sheet read by code on arrival (build C2, plan 2026-11-05 §3.1; the owner, 2026-11-05: "the agent must
// recognise, clean and bring everything into the project"). A sheet that needs nothing more is saved at once and waits
// on its product's card; a BE arm waits on its study's card, drawn, asking only what the sheet does not say. The
// workbooks are written by a Python helper (software test data, never a model).
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

test("sheets are read on arrival: a complete one waits on its product, a BE arm asks for its facts on its study", async ({ page, request }) => {
  const dir = mkdtempSync(join(tmpdir(), "arrival-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "er_be_workbooks.py"), dir], { cwd: REPO });
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "desvenlafaxine", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nER tablet 50 mg, VBE.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  const edit = (path: string, value: unknown) => ({ path, value, status: "EDITED", note: "from the proposal" });
  expect((await request.put(`/api/v1/projects/${projectId}/brief`, { headers: AUTH, data: { reason: "from the proposal", changes: [
    edit("products[0].name", "Desvenlafaxine succinate ER Tablets"), edit("products[0].role", "TEST"),
    edit("products[0].release", "ER"), edit("products[0].dosage_form", "tablet"),
  ] } })).ok()).toBeTruthy();
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  await page.getByTestId("client-upload-studies").setInputFiles(
    ["230-23 Fasting Reference.xlsx", "Dissolution Test pH 6.8.xlsx"].map((f) => join(dir, f)));
  await expect(page.getByTestId("inputs-notice")).toContainText("2 files stored.");

  // the BE arm: read by code, drawn on its study's card, asking only what the sheet does not say
  const card = page.getByTestId("group-study:230-23-REF");
  const draft = card.getByTestId("draft-Sheet1");
  await expect(draft.getByTestId("dataset-view")).toBeVisible();
  await expect(card.getByTestId("confirm-study:230-23-REF")).toBeDisabled();
  await expect(draft.getByTestId("need-n")).toBeVisible();
  await expect(draft.getByTestId("need-dose")).toHaveCount(0);                       // "50 mg" in the title: read
  await shot(page, "1-be-arm-to-finish");
  await draft.getByTestId("need-n").fill("6");
  await draft.getByTestId("need-formulation").selectOption("mr");
  await draft.getByTestId("need-purpose").selectOption("model_building");
  await draft.getByTestId("finish-Sheet1").click();
  await expect(page.getByTestId("inputs-notice")).toContainText("Sheet1: read");
  await expect(card.getByTestId("draft-Sheet1")).toHaveCount(0);
  await expect(card.getByTestId("dataset-view")).toBeVisible();
  await expect(card).toContainText("Subjects (n)");
  await expect(card.getByTestId("confirm-study:230-23-REF")).toBeEnabled();
  await card.getByTestId("confirm-study:230-23-REF").click();
  await expect(card).toContainText("Confirmed by");

  // the test product's dissolution: nothing to give (its product named as in the brief): saved on arrival, on its card
  await page.getByTestId("tab-formulations").click();
  await expect(page.getByTestId("release-view").first()).toBeVisible();
  await expect(page.getByTestId("client-file-Dissolution Test pH 6.8.xlsx").getByTestId("sheet-pH 6.8")).toContainText("read ✓");
  await shot(page, "2-dissolution-on-its-product");
});
