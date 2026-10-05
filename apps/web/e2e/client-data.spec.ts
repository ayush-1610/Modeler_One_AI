// T-47: the client-data template is downloaded, filled and uploaded; any other workbook is sorted sheet by sheet; the
// reconciliation shows what the data plan expects from the client. The workbooks are written by a Python helper
// (software test data, never a model).
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

const REPO = resolve(__dirname, "../../..");

test("client files are read cell by cell, sorted, and reconciled with the data plan", async ({ page, request }) => {
  const dir = mkdtempSync(join(tmpdir(), "client-data-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "client_workbooks.py"), dir], { cwd: REPO });

  const started = await request.post("/api/v1/projects:initiate", {
    headers: { Authorization: "Bearer dev" },
    multipart: { drug_name: "Clientamide", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral 10 mg tablet.") } },
  });
  expect(started.ok()).toBeTruthy();
  const projectId = (await started.json()).data.project_id as string;
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: { Authorization: "Bearer dev" } })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}/client-data`);
  const download = page.waitForEvent("download");
  await page.getByTestId("download-template").click();
  expect((await download).suggestedFilename()).toBe("ModelerOne_ClientData_v1.xlsx");

  await page.getByTestId("client-upload").setInputFiles([join(dir, "client-template-filled.xlsx"), join(dir, "client-raw.xlsx")]);
  const filled = page.getByTestId("client-file-client-template-filled.xlsx");
  await expect(filled).toContainText("client-data template");
  await expect(filled).toContainText("1 dataset");
  await expect(filled).toContainText("PK_Summary!F7");          // the decimal comma is named with its cell, not guessed

  const raw = page.getByTestId("client-file-client-raw.xlsx");
  await expect(raw.getByTestId("sheet-Diss pH 6.8")).toContainText("dissolution");
  const notes = raw.getByTestId("sheet-Notes");
  await expect(notes).toContainText("other");
  await notes.getByLabel("category of Notes").selectOption("PRODUCT_INFO");
  await notes.getByPlaceholder("why").fill("shipping note with the batch numbers");
  await notes.getByRole("button", { name: "Set" }).click();
  await expect(raw.getByTestId("sheet-Notes")).toContainText("product info");

  // dissolution: each profile fitted (PK-Sim Weibull), test vs reference compared by f2 under its conditions
  await expect(page.getByTestId("f2-row")).toContainText("similar");
  const testProfile = page.locator("tr[data-testid^='profile-']", { hasText: "Test 10 mg" });
  await expect(testProfile).toContainText("t50 18 min");
  await testProfile.getByPlaceholder("formulation name").fill("Test10");
  await testProfile.getByRole("button", { name: "Propose as release model" }).click();
  await expect(page.getByText(/Problems|Error/)).toHaveCount(0);

  // the client's study arrived without the plan promising it; the client dataset is on the observed-data tab too
  await expect(page.getByText(/CL-01 .*delivered, not promised/)).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("client-data.png"), fullPage: true });
  await page.goto(`/projects/${projectId}/evidence?tab=observed`);
  await expect(page.locator(".evidence", { hasText: "CL-01" })).toContainText("client");
  // the proposed release model waits for acceptance on the Parameters tab, flagged until PK-Sim confirms the equation
  const views = await request.get(`/api/v1/projects/${projectId}/evidence`, { headers: { Authorization: "Bearer dev" } });
  const t50 = (await views.json()).data.evidence.find((e: { target: string }) => e.target === "form.Test10.weibull.t50");
  expect(t50.state).toBe("PROPOSED");
  expect(t50.flags.join(" ")).toContain("unconfirmed");
});
