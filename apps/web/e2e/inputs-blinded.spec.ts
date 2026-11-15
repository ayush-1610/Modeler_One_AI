// T-47 / F-402: D-15 on Inputs (final review INT-1, INT-2, INT-3). With the project's blinding on, two studies of a
// delivery are entered for external validation on their cards, with a reason that quotes a value: the delivery then
// blinds them, and no view of Inputs shows their values, the digits of the reasons, their pages' lines or their sheets.
// The card lists its decisions with the reason's digits masked ("Entered for Purpose of the study (value withheld)"),
// offers no "Confirm now with the sheet form" and withholds the sheet form's reading; Client files withholds the
// report's page lines (no peek) and the workbook's blinded sheet. Software test data (the made-up Exampleamide), never a
// model.
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const WHY = "CSR table 14.2.2: Cmax 35.6 ng/mL in 6 subjects, kept for external validation";

type Row = { subject: string; label: string; blinded: boolean };

test("a study the delivery blinds shows no value, reason digit, page line or sheet on Inputs, and no sheet-form path", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 50 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const api = `/api/v1/projects/${projectId}`;
  const read = async <T,>(path: string) => (await (await request.get(`${api}/${path}`, { headers: AUTH })).json()).data as T;

  // the messy workbook and the PDF report, read with the layouts signed off earlier
  const dir = mkdtempSync(join(tmpdir(), "blinded-"));
  const printed = execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "delivery.py"),
                                      join(process.env.E2E_DATA_DIR!, "read-root"), projectId, dir], { cwd: REPO }).toString();
  const fixture = JSON.parse(printed.trim().split("\n").pop()!) as { files: string[] };
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  await page.getByTestId("tab-studies").click();
  await page.getByTestId("client-upload-studies").setInputFiles(fixture.files.map((name) => join(dir, name)));
  await page.getByTestId("tab-files").click();
  const section = page.getByTestId("delivery-section");
  await expect(section.getByTestId("delivery-total-files")).toHaveText("2", { timeout: 120_000 });
  await expect(section.getByTestId("delivery-running")).toHaveCount(0, { timeout: 120_000 });

  // blinding on; 231-24 (the workbook's Fed sheet) and 230-25 (the report's table) entered for external validation
  const on = await request.put(`${api}/blinding`, { headers: AUTH, data: { on: true, reason: "external validation is blinded until the MAP is signed" } });
  expect(on.ok(), await on.text()).toBeTruthy();
  const subjects = (await read<{ subjects: Row[] }>("delivery")).subjects;
  const fed = subjects.find((s) => s.label === "231-24")!, report = subjects.find((s) => s.label === "230-25")!;
  for (const s of [fed, report]) {
    const entered = await request.post(`${api}/delivery/subjects/study/${s.subject}:enter`, { headers: AUTH,
      data: { field: "intended_use", value: "external_validation", why: WHY } });
    expect(entered.ok(), await entered.text()).toBeTruthy();
  }
  expect((await read<{ subjects: Row[] }>("delivery")).subjects.filter((s) => s.blinded).map((s) => s.label).sort()).toEqual(["230-25", "231-24"]);

  // --- the card of 231-24: its values withheld, its decisions' reasons masked, no sheet-form path ---
  await page.reload();
  await page.getByTestId("tab-studies").click();
  const toggle = page.getByTestId(`delivery-subject-open-${fed.subject}`);
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  const card = page.getByTestId(`delivery-card-${fed.subject}`);
  await expect(card.getByTestId(`delivery-blinded-${fed.subject}`)).toBeVisible();
  const decisions = card.getByTestId(`delivery-decisions-own-${fed.subject}`);
  await expect(decisions).toContainText("Entered for Purpose of the study (value withheld)");
  await expect(decisions).toContainText("Cmax ••.• ng/mL in • subjects");
  await expect(decisions).not.toContainText("35.6");
  // the sheet form read the Fed sheet as study 231-24: neither its path nor its reading is offered while blinded
  const body = card.locator("xpath=ancestor::*[contains(@class,'card-body')][1]");
  await expect(body.locator('[data-testid^="confirm-sheet-"]')).toHaveCount(0);
  const howRead = body.locator('[data-testid^="how-read-"]').first();
  await howRead.locator("summary").click();
  await expect(body.locator('[data-testid^="how-read-withheld-"]')).toContainText("Withheld: the study is blinded until the plan is signed");
  await expect(page.locator("body")).not.toContainText("35.6");
  await page.screenshot({ path: test.info().outputPath("1-blinded-card.png"), fullPage: true });

  // --- Client files: the report's page lines withheld with no peek, the workbook's blinded sheet not offered ---
  await page.getByTestId("tab-files").click();
  const pdf = fixture.files.find((name) => name.endsWith(".pdf"))!, book = fixture.files.find((name) => name.endsWith(".xlsx"))!;
  await page.getByTestId(`file-toggle-${pdf}`).click();
  const reading = page.getByTestId(`document-${pdf}`);
  await expect(reading.locator('[data-testid^="inventory-withheld-"]').first()).toHaveText("withheld (blinded)");
  await expect(reading.locator('[data-testid^="peek-"], button:has-text("Show")')).toHaveCount(0);
  await expect(reading).not.toContainText("Table 5. Study 230-25");
  await expect(reading).not.toContainText("0.5 ng/mL");
  await page.getByTestId(`file-toggle-${pdf}`).click();
  await page.getByTestId(`file-toggle-${book}`).click();
  await expect(page.getByTestId("sheet-blinded-Fed")).toHaveText("blinded until the plan is signed");
  await expect(page.getByTestId("sheet-blinded-Fasting")).toHaveCount(0);           // 230-23's sheet stays open
  await page.screenshot({ path: test.info().outputPath("2-blinded-files.png"), fullPage: true });

  // the APIs the page reads give none of it either
  const review = await request.get(`${api}/client-review`, { headers: AUTH });
  expect(await review.text()).not.toContain("35.6");
  const trail = await request.get(`${api}/audit?limit=2000`, { headers: AUTH });
  expect(await trail.text()).not.toContain("35.6");
});
