// T-47: on the Inputs step, the client-data template is downloaded, filled and uploaded; any other workbook is sorted sheet
// by sheet; the dissolution profiles are on the Formulations tab; what the client sent beyond the data checklist is named. The workbooks are written by a Python helper
// (software test data, never a model).
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { finishStart, openFile } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");

test("client files are read cell by cell, sorted, and what the checklist did not promise is named", async ({ page, request }) => {
  const dir = mkdtempSync(join(tmpdir(), "client-data-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "client_workbooks.py"), dir], { cwd: REPO });

  const started = await request.post("/api/v1/projects:initiate", {
    headers: { Authorization: "Bearer dev" },
    multipart: { drug_name: "Clientamide", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral 10 mg tablet.") } },
  });
  expect(started.ok()).toBeTruthy();
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);      // Inputs opens once Start is done (page review 1, decision 7)
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: { Authorization: "Bearer dev" } })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  const download = page.waitForEvent("download");
  await page.getByTestId("download-template").click();
  expect((await download).suggestedFilename()).toBe("ModelerOne_ClientData_v1.xlsx");

  await page.getByTestId("client-upload-studies").setInputFiles([join(dir, "client-template-filled.xlsx"), join(dir, "client-raw.xlsx")]);
  await page.getByTestId("tab-files").click();                    // each file and its sheets, in Client files
  await openFile(page, "client-template-filled.xlsx");
  await openFile(page, "client-raw.xlsx");
  const filled = page.getByTestId("client-file-client-template-filled.xlsx");
  await expect(filled).toContainText("client-data template");
  await expect(filled).toContainText("1 dataset");
  // the decimal comma is named with its cell, not guessed, in words (final review round 6: "PK_Summary!F7" as written)
  await expect(filled).toContainText("sheet PK_Summary, cell F7: value: “1,2” is not a plain number");
  await expect(filled).not.toContainText("PK_Summary!F7");

  const raw = page.getByTestId("client-file-client-raw.xlsx");
  await expect(raw.getByTestId("sheet-Diss pH 6.8")).toContainText("dissolution");
  const notes = raw.getByTestId("sheet-Notes");
  await expect(notes).toContainText("not sorted");
  await notes.getByRole("button", { name: "change" }).click();
  await notes.getByLabel("category of Notes").selectOption("PRODUCT_INFO");
  await notes.getByPlaceholder("why").fill("shipping note with the batch numbers");
  await notes.getByRole("button", { name: "Set" }).click();
  await expect(raw.getByTestId("sheet-Notes")).toContainText("product info");

  // dissolution, on Products and dissolution: each profile fitted (PK-Sim Weibull), test vs reference compared by f2
  await page.getByTestId("tab-formulations").click();
  await expect(page.getByTestId("f2-row")).toContainText("similar");
  // the client's product is confirmed first, inline: its data load only then (plan 2026-11-03 §3.3)
  const product = page.locator("[data-testid^='group-product:']", { hasText: "Test 10 mg" });
  await expect(product).toContainText("To confirm");
  const productId = (await product.getAttribute("data-testid"))!.replace(/^group-/, "");
  await product.getByTestId(`confirm-${productId}`).click();
  // said once, on the card's head line: who confirmed it and how; the group inside does not repeat it (final review OWN-14)
  await expect(page.getByTestId(`card-loaded-${productId}`)).toContainText(/Confirmed with the sheet form by dev-user on \d{1,2} \w{3} \d{4}, \d\d:\d\d\./);
  await expect(product.getByTestId(`group-confirmed-${productId}`)).toHaveCount(0);
  // on its product's card a profile is named without the product (final review OWN-10): the card's title says it
  const testCard = page.locator("[data-testid^='product-card-']", { has: page.locator(".card-title", { hasText: /^Test 10 mg$/ }) });
  const testProfile = testCard.locator("li[data-testid^='profile-']").first();
  await expect(testProfile).toContainText("t50 18 min");
  await expect(testProfile).not.toContainText("Test 10 mg");
  // confirmed is not yet a formulation: the card says its release is not set, and offers to set it
  await expect(testCard.locator("[data-testid^='card-release-product']").first()).toContainText("the formulation's release is not set yet");
  await testProfile.getByPlaceholder("formulation name").fill("Test10");
  await testProfile.getByRole("button", { name: "Use as release" }).click();
  await expect(page.getByText(/Problems|Error/)).toHaveCount(0);

  // a dissolution sheet in the client's own layout: the guided reader finds the time and vessel columns
  await page.getByTestId("tab-files").click();
  await raw.getByTestId("sheet-Diss pH 6.8").getByRole("button", { name: "Read this sheet" }).click();
  const reader = page.getByTestId("reader-Diss pH 6.8");
  await expect(reader.getByLabel("pH", { exact: true })).toHaveValue("6.8");
  await reader.getByLabel("product", { exact: true }).fill("Raw 10 mg");
  await reader.getByLabel("role", { exact: true }).selectOption("OTHER");
  await reader.getByLabel("batch", { exact: true }).fill("R1");
  await reader.getByLabel("medium", { exact: true }).fill("phosphate");
  await reader.getByLabel("last value column", { exact: true }).selectOption("C");
  await reader.getByRole("button", { name: "Check what will be read" }).click();
  await expect(reader.getByTestId("read-result")).toContainText("4 values · 2 vessels · 2 times — ready to save");
  await reader.getByRole("button", { name: "Save these data" }).click();

  // the client's study arrived without the checklist promising it; the client dataset is among every dataset
  await page.getByTestId("tab-studies").click();
  // its hover says so without the dataset's id (round 7: "dataset CL-01 (ds-5d48c2722b): delivered, …")
  await expect(page.locator("[data-testid^='dataset-unpromised-']").first())
    .toHaveAttribute("title", /^Dataset CL-01: delivered, not promised by the data plan$/);
  await expect(page.locator(".evidence", { hasText: "CL-01" })).toContainText("client");
  await page.screenshot({ path: test.info().outputPath("client-data.png"), fullPage: true });
  await page.getByTestId("tab-formulations").click();
  // its own product's card, the profile named by what tells it apart (the card's title names the product)
  const rawCard = page.locator("[data-testid^='product-card-']", { has: page.locator(".card-title", { hasText: /^Raw 10 mg$/ }) });
  await expect(rawCard.locator("li[data-testid^='profile-']").first()).toContainText("phosphate pH 6.8");
  // the proposed release model flows in, held for the review; PK-Sim has confirmed the equation, so the value carries
  // the engine check rather than an "unconfirmed" flag
  const views = await request.get(`/api/v1/projects/${projectId}/evidence`, { headers: { Authorization: "Bearer dev" } });
  const t50 = (await views.json()).data.evidence.find((e: { target: string }) => e.target === "form.Test10.weibull.t50");
  expect(t50.state).toBe("PROPOSED");
  expect(t50.flags.join(" ")).not.toContain("unconfirmed");
  expect(t50.conditions["engine check"]).toContain("engine-image run");
});
