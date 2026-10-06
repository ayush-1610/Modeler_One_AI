// T-47: the guided client-data flow on files laid out the way CROs and labs send them (an ER tablet with a VBE and
// food-effect question). Each sheet is read from a form filled in from the sheet itself; the data-plan items the
// client cannot send are decided with a reason; then P3 is approved. The workbooks are written by a Python helper
// (software test data, never a model).
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type Page, test } from "@playwright/test";

const REPO = resolve(__dirname, "../../..");
const AUTH = { Authorization: "Bearer dev" };

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

test("an ER tablet's BE, dissolution and literature files are read sheet by sheet and P3 closes", async ({ page, request }) => {
  const dir = mkdtempSync(join(tmpdir(), "er-be-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "er_be_workbooks.py"), dir], { cwd: REPO });

  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "desvenlafaxine", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nER tablet 50 mg, VBE.") } },
  });
  const projectId = (await started.json()).data.project_id as string;
  const edit = (path: string, value: unknown) => ({ path, value, status: "EDITED", note: "from the proposal" });
  const brief = await request.put(`/api/v1/projects/${projectId}/brief`, { headers: AUTH, data: { reason: "from the proposal", changes: [
    edit("drug.modality", "small_molecule"),
    edit("qoi.applications", ["APP-01 model build and verification", "APP-12 food effect", "APP-14 virtual bioequivalence"]),
    edit("products[0].name", "Desvenlafaxine succinate ER Tablets"), edit("products[0].role", "TEST"),
    edit("products[0].release", "ER"), edit("products[0].dosage_form", "tablet"),
    edit("data_plan[0].item", "dissolution of test and RLD"), edit("data_plan[0].category", "dissolution"), edit("data_plan[0].provider", "CLIENT"),
    edit("data_plan[1].item", "BE study 230-23"), edit("data_plan[1].category", "rld_data"), edit("data_plan[1].provider", "CLIENT"),
  ] } });
  expect(brief.ok(), await brief.text()).toBeTruthy();
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}/client-data`);
  await expect(page.getByText(/What stops approval/)).toBeVisible();
  await expect(page.getByTestId("approve-client-data")).toBeDisabled();
  await page.getByTestId("client-upload").setInputFiles(["230-23 Fasting Reference.xlsx", "230-23 Fasting Test.xlsx",
    "Dissolution Test pH 6.8.xlsx", "Dissolution RLD pH 6.8.xlsx", "Nichols2012 IV 50 mg 5 h infusion.xlsx"].map((f) => join(dir, f)));
  await expect(page.getByText("5 files stored.")).toBeVisible();
  await shot(page, "1-uploaded");

  // the BE reference arm: times across the top, Mean / SD rows left out, the LLOQ quoted from the footnote
  const reference = page.getByTestId("client-file-230-23 Fasting Reference.xlsx");
  await reference.getByRole("button", { name: "Read this sheet" }).click();
  const reader = page.getByTestId("reader-Sheet1");
  await expect(reader).toContainText("Times run across row 4");
  await expect(reader).toContainText("summary rows: not read");
  await expect(reader.getByLabel("study id", { exact: true })).toHaveValue("230-23-REF");
  await expect(reader.getByLabel("LLOQ", { exact: true })).toHaveValue("0.5");
  await reader.getByLabel("formulation", { exact: true }).selectOption("mr");
  await reader.getByLabel("subjects", { exact: true }).fill("6");
  await reader.getByLabel("study purpose", { exact: true }).selectOption("external_validation");
  await reader.getByRole("button", { name: "Check what will be read" }).click();
  await expect(reader.getByTestId("read-result")).toContainText("Not a number");      // the NS cell, named with its cell
  await reader.getByLabel("no sample texts", { exact: true }).fill("NS");
  await reader.getByRole("button", { name: "Check what will be read" }).click();
  await expect(reader.getByTestId("read-result")).toContainText("65 values · 6 series · 11 times");
  await expect(reader.getByTestId("read-result")).toContainText("ready to save");
  await shot(page, "2-reader-be");
  await reader.getByRole("button", { name: "Save these data" }).click();
  await expect(page.getByText(/Sheet1: 1 dataset\(s\) for 230-23-REF saved/)).toBeVisible();
  await expect(reference.getByTestId("sheet-Sheet1")).toContainText("read ✓");

  // the test arm: the same layout, taken over from the last sheet; its own study id
  const testArm = page.getByTestId("client-file-230-23 Fasting Test.xlsx");
  await testArm.getByRole("button", { name: "Read this sheet" }).click();
  const reader2 = page.getByTestId("reader-Sheet1");
  await reader2.getByRole("button", { name: "Same settings as the last sheet" }).click();
  await expect(reader2.getByLabel("study id", { exact: true })).toHaveValue("230-23-TEST");
  await reader2.getByRole("button", { name: "Check what will be read" }).click();
  await expect(reader2.getByTestId("read-result")).toContainText("ready to save");
  await reader2.getByRole("button", { name: "Save these data" }).click();
  await expect(page.getByText(/230-23-TEST saved/)).toBeVisible();

  // dissolution: the test product named as in the brief, its conditions quoted from the title
  for (const [file, role, product] of [["Dissolution Test pH 6.8.xlsx", "TEST", ""], ["Dissolution RLD pH 6.8.xlsx", "RLD", "Reference product 50 mg"]]) {
    await page.getByTestId(`client-file-${file}`).getByRole("button", { name: "Read this sheet" }).click();
    const r = page.getByTestId("reader-pH 6.8");
    await expect(r.getByLabel("role", { exact: true })).toHaveValue(role);
    await expect(r.getByLabel("pH", { exact: true })).toHaveValue("6.8");
    if (product) await r.getByLabel("product", { exact: true }).fill(product);
    else await expect(r.getByLabel("product", { exact: true })).toHaveValue("Desvenlafaxine succinate ER Tablets");
    await r.getByRole("button", { name: "Check what will be read" }).click();
    await expect(r.getByTestId("read-result")).toContainText("96 values · 12 vessels · 8 times");
    if (role === "TEST") await shot(page, "3-reader-dissolution");
    await r.getByRole("button", { name: "Save these data" }).click();
    await expect(page.getByText(/pH 6.8: 96 dissolution values saved/)).toBeVisible();
  }
  await expect(page.getByTestId("f2-row")).toBeVisible();

  // published IV means: SD and N columns, the route from the file name
  await page.getByTestId("client-file-Nichols2012 IV 50 mg 5 h infusion.xlsx").getByRole("button", { name: "Read this sheet" }).click();
  const iv = page.getByTestId("reader-Fig 1");
  await expect(iv.getByLabel("route", { exact: true })).toHaveValue("iv_infusion");
  await iv.getByLabel("subjects", { exact: true }).fill("14");
  await iv.locator("label", { hasText: "Infusion time (min)" }).locator("input").fill("300");
  await iv.getByRole("button", { name: "Check what will be read" }).click();
  await expect(iv.getByTestId("read-result")).toContainText("ready to save");
  await iv.getByRole("button", { name: "Save these data" }).click();
  await expect(page.getByText(/Nichols2012 saved/)).toBeVisible();

  // what the client cannot send: decided with a reason, not left hanging
  await expect(page.getByTestId("recon-REQ-vbe.be_study")).toContainText("delivered");
  await expect(page.getByTestId("recon-REQ-vbe.rld_dissolution")).toContainText("delivered");
  await shot(page, "4-plan");
  const biorelevant = page.getByTestId("recon-REQ-fe.biorelevant");
  await biorelevant.getByLabel("reason for REQ-fe.biorelevant", { exact: true }).fill("the client has no FaSSIF / FeSSIF data");
  await biorelevant.getByRole("button", { name: "Get it from the literature instead" }).click();
  await expect(page.getByTestId("recon-REQ-fe.biorelevant")).toHaveCount(0);
  const variability = page.getByTestId("recon-REQ-vbe.variability");
  await variability.getByLabel("reason for REQ-vbe.variability", { exact: true }).fill("computed later from the BE study data");
  await variability.getByRole("button", { name: "Not from the client" }).click();
  await expect(page.getByTestId("recon-REQ-vbe.variability")).toContainText("not from the client");

  await expect(page.getByTestId("approve-client-data")).toBeEnabled();
  await page.getByTestId("approve-client-data").click();
  await expect(page.getByText("Client data approved (P3).")).toBeVisible();
  await shot(page, "5-approved");
});
