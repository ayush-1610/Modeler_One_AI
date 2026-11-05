// A client's Word or PDF file read for its data (docs/plans/2026-11-03-inputs-and-client-data.md §3.4, build I4): code
// lists the pages that hold project data; the reading agent proposes the study's facts, each quoted and checked by code
// (the browser flows run with no LLM provider, so a fixture runs the real reading job with a scripted model). The
// synopsis gives another dose than the PK sheet: the study's card flags it with both sources, and a person settles it
// by selecting one and confirming. Software test data.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const AUTH = { Authorization: "Bearer dev" };
const TYPES: Record<string, string> = {
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

test("a Word synopsis is read for its study's facts, and its dose against the PK sheet's is settled on the card", async ({ page, request }) => {
  const dir = mkdtempSync(join(tmpdir(), "documents-"));
  const fixture = join(__dirname, "fixtures", "document_reading.py");
  execFileSync("uv", ["run", "python", fixture, "write", dir], { cwd: REPO });
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Documentamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 10 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const ids: Record<string, string> = {};
  for (const name of ["EX-301_PK.xlsx", "EX-301_synopsis.docx"]) {
    const up = await request.post(`/api/v1/projects/${projectId}/client-data`, { headers: AUTH, multipart: {
      files: { name, mimeType: TYPES[name.split(".").pop()!], buffer: readFileSync(join(dir, name)) } } });
    expect(up.status(), await up.text()).toBe(201);
    ids[name] = (await up.json()).data.read[0].id;
  }

  // before the reading: code's inventory of the synopsis, and the agent's button (off: no LLM provider here)
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  await page.getByTestId("tab-studies").click();
  const doc = page.getByTestId("document-EX-301_synopsis.docx");
  await expect(doc).toContainText("Code found project data on 1 page");
  await expect(doc.getByTestId("inventory-1-design")).toContainText("single oral dose of 10 mg");
  await expect(doc.getByTestId("read-doc-EX-301_synopsis.docx")).toBeDisabled();
  await expect(page.getByTestId("group-study:EX-301")).not.toContainText("Conflict");

  execFileSync("uv", ["run", "python", fixture, "read", join(process.env.E2E_DATA_DIR!, "read-root"), projectId,
                      ids["EX-301_synopsis.docx"]], { cwd: REPO });
  await page.reload();
  await page.getByTestId("tab-studies").click();
  await expect(page.getByTestId("document-read-EX-301_synopsis.docx")).toContainText("6 study facts");

  // the synopsis says 10 mg, the PK sheet 5 mg: a conflict on the study's card, each value with its source
  const card = page.getByTestId("group-study:EX-301");
  const dose = card.getByTestId("issue-study:EX-301|dose_mg");
  await expect(dose).toContainText("Conflict");
  await expect(dose).toContainText("10");
  await expect(dose).toContainText("5");
  await expect(card.getByTestId("confirm-study:EX-301")).toBeDisabled();
  await expect(dose.getByRole("radio", { name: /^10 · EX-301_synopsis\.docx/ })).toBeVisible();
  await expect(dose.getByRole("radio", { name: /^5 · EX-301_PK\.xlsx/ })).toBeVisible();
  await dose.getByRole("button", { name: "Open the source of 10" }).click();      // the synopsis, its quote marked
  const peek = page.getByTestId("source-peek");
  await expect(peek.locator("mark").first()).toContainText("a single oral dose of 10 mg");
  await shot(page, "1-synopsis-against-sheet");
  await peek.getByTestId("source-peek-close").click();

  await dose.getByRole("radio", { name: /^10 · EX-301_synopsis/ }).check();
  await dose.getByTestId("issue-confirm-study:EX-301|dose_mg").click();
  await expect(dose).toContainText("Resolved");
  await expect(card.getByTestId("issue-final-study:EX-301|dose_mg")).toHaveText("10");
  await card.getByTestId("confirm-study:EX-301").click();
  await expect(card).toContainText("Confirmed by");
  await shot(page, "2-settled-and-confirmed");
  const datasets = (await (await request.get(`/api/v1/projects/${projectId}/evidence`, { headers: AUTH })).json()).data.datasets;
  expect(datasets.filter((d: { state: string }) => d.state === "ACCEPTED").map((d: { study: { dose_mg: number } }) => d.study.dose_mg))
    .toEqual([10]);
});
