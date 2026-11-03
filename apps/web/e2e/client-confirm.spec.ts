// The client's data, confirmed inline (docs/plans/2026-11-03-inputs-and-client-data.md §3.3–3.5; the owner,
// 2026-11-03): two client files give one study two doses and two subject counts. The study's card flags both; its
// confirmation waits until each is settled by selecting an option and confirming the selection, with no reason asked;
// a settled conflict stays in place with its final value; only the confirmed study loads. Software test data.
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

test("a study two client files contradict is settled on its card, then confirmed and loaded", async ({ page, request }) => {
  const dir = mkdtempSync(join(tmpdir(), "conflict-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "conflict_workbooks.py"), dir], { cwd: REPO });
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Confirmamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 10 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  for (const name of ["EX-101_protocol_PK.xlsx", "EX-101_PK_sheet.xlsx"]) {
    const up = await request.post(`/api/v1/projects/${projectId}/client-data`, { headers: AUTH, multipart: {
      files: { name, mimeType: XLSX, buffer: readFileSync(join(dir, name)) } } });
    expect(up.status(), await up.text()).toBe(201);
  }

  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  await page.getByTestId("tab-studies").click();
  const card = page.getByTestId("group-study:EX-101");
  await expect(card).toContainText("To confirm · 2 items");
  const confirm = card.getByTestId("confirm-study:EX-101");
  await expect(confirm).toBeDisabled();
  await expect(card).toContainText("Settle 2 open items first");
  const dose = card.getByTestId("issue-study:EX-101|dose_mg");
  await expect(dose).toContainText("Dose (mg): the client's files give 2 values");
  await shot(page, "1-study-with-a-conflict");

  // select the protocol's dose and confirm the selection: no reason asked; it stays in place, resolved
  await dose.getByRole("radio", { name: /^10 · EX-101_protocol_PK/ }).check();
  await dose.getByTestId("issue-confirm-study:EX-101|dose_mg").click();
  await expect(dose).toContainText("Resolved");
  await expect(card.getByTestId("issue-final-study:EX-101|dose_mg")).toHaveText("10");
  await expect(dose).toContainText("Not used: 5");
  // changeable until the group is confirmed
  await dose.getByTestId("issue-change-study:EX-101|dose_mg").click();
  await dose.getByRole("radio", { name: /^10 · EX-101_protocol_PK/ }).check();
  await dose.getByTestId("issue-confirm-study:EX-101|dose_mg").click();
  await expect(dose).toContainText("Resolved");

  // dosed against PK-evaluable: marked explained
  const n = card.getByTestId("issue-study:EX-101|n");
  await expect(n).toContainText("Differs");
  await n.getByTestId("issue-option-study:EX-101|n-explained").check();
  await n.getByTestId("issue-confirm-study:EX-101|n").click();
  await expect(n).toContainText("Explained: dosed and PK-evaluable counts differ");
  await expect(n).toContainText("Kept as given: 12");
  await shot(page, "2-settled-in-place");

  // "To confirm" shows only what waits for the person
  await page.getByTestId("to-confirm").click();
  await expect(page.getByTestId("to-confirm")).toHaveAttribute("aria-pressed", "true");
  await expect(card).toBeVisible();
  await page.getByTestId("to-confirm").click();

  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(card).toContainText("Confirmed by");
  await expect(card.getByTestId("issue-final-study:EX-101|dose_mg")).toHaveText("10");   // still shown, final
  await expect(page.getByTestId("study-EX-101")).toBeVisible();                          // loaded into the project
  await shot(page, "3-confirmed-and-loaded");
  const ev = await (await request.get(`/api/v1/projects/${projectId}/evidence`, { headers: AUTH })).json();
  const doses = (ev.data.datasets as { study: { dose_mg: number }; state: string }[]).map((d) => [d.study.dose_mg, d.state]);
  expect(doses).toEqual([[10, "ACCEPTED"], [10, "ACCEPTED"]]);                           // the selection is applied
});
