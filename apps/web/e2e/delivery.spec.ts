// The Delivery section, end to end (contracts 2026-11-12 §8.10): two client files arrive (a messy workbook and a PDF
// report of the made-up Exampleamide), code reads them with the layouts a person signed off earlier (all but one), and
// a reviewer works by exception: the coverage panel, a value's source with its cell highlighted, the one mapping that
// waits, the study's blockers each settled with its decision and reason, the spot check ticked and sent once, the
// signed confirmation, and the study in the project once. Software test data: it proves the review path, never a model.
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");

type Row = { subject: string; label: string };
type Value = { id: string; verbatim: string | null };
type Card = { tables: { kind: string; values: Value[] }[]; blockers: { code: string }[] };

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

test("a delivery is reviewed by exception, spot-checked, signed and loaded once", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 50 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const api = `/api/v1/projects/${projectId}`;
  const read = async <T,>(path: string) => (await (await request.get(`${api}/${path}`, { headers: AUTH })).json()).data as T;

  // the two files, and every layout of theirs approved earlier except the urine table's
  const dir = mkdtempSync(join(tmpdir(), "delivery-"));
  const printed = execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "delivery.py"),
                                      join(process.env.E2E_DATA_DIR!, "read-root"), projectId, dir], { cwd: REPO }).toString();
  const fixture = JSON.parse(printed.trim().split("\n").pop()!) as { files: string[]; waiting: { mapping_id: string } };
  const waiting = fixture.waiting.mapping_id;

  // --- the files arrive: uploaded on Inputs, read by code ---
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  await page.getByTestId("tab-studies").click();
  await page.getByTestId("client-upload-studies").setInputFiles(fixture.files.map((name) => join(dir, name)));
  const section = page.getByTestId("delivery-section");
  await expect(section.getByTestId("delivery-total-files")).toHaveText("2", { timeout: 120_000 });
  await expect(section.getByTestId("delivery-running")).toHaveCount(0, { timeout: 120_000 });

  // --- the coverage panel: every numeric cell of every table is accounted for; one stray note and nothing unassigned ---
  await expect(section.getByTestId("delivery-total-silent-loss")).toHaveText("0");
  await expect(section.getByTestId("delivery-total-regions")).toHaveText("12");
  await expect(section.getByTestId("delivery-total-outside")).toHaveText("1");
  await expect(section.getByTestId("delivery-total-unassigned")).toHaveText("0");
  await expect(section.getByTestId("delivery-rules")).toHaveText("rules UNVERIFIED v0.1");
  const delivery = await read<{ deliveries: { files: { file_id: string; name: string }[] }[]; subjects: Row[] }>("delivery");
  const files = delivery.deliveries.flatMap((d) => d.files);
  expect(files.map((f) => f.name).sort()).toEqual([...fixture.files].sort());
  for (const f of files) await expect(section.getByTestId(`delivery-file-state-${f.file_id}`)).toHaveText("read");
  // a file's regions, and how long each stage took
  const pdf = files.find((f) => f.name.endsWith(".pdf"))!;
  await section.getByTestId(`delivery-file-toggle-${pdf.file_id}`).click();
  await expect(section.getByTestId(`delivery-regions-${pdf.file_id}`)).toContainText("no model is configured");   // its prose: not read, and why
  await expect(section.getByTestId(`delivery-stages-${pdf.file_id}`)).toContainText("parse");
  await section.getByTestId(`delivery-file-toggle-${pdf.file_id}`).click();
  await expect(section.getByTestId(`delivery-mapping-${waiting}`)).toContainText("waits for approval");
  await shot(page, "1-coverage");

  // --- a value's source: its cell highlighted, with its time ---
  const study = delivery.subjects.find((s) => s.label === "230-23")!;
  await section.getByTestId(`delivery-subject-open-${study.subject}`).click();
  const card = section.getByTestId(`delivery-card-${study.subject}`);
  for (const code of ["OUTSIDE_NUMBERS", "SCHEMA_GAP", "CHECK_FAILED", "SPOT_CHECK"]) {
    await expect(card.getByTestId(`delivery-blocker-${code}`)).toBeVisible();
  }
  const before = await read<Card>(`delivery/subjects/study/${study.subject}`);
  const value = before.tables.flatMap((t) => t.values).find((v) => v.verbatim === "25.2")!;
  await card.getByTestId(`delivery-source-open-${value.id}`).click();
  const source = card.getByTestId(`delivery-source-${value.id}`);
  await expect(source.getByTestId("source-cell-value")).toHaveText("25.2");
  await expect(source.getByTestId("source-cell-value")).toHaveAttribute("data-highlighted", "true");
  await expect(source.getByTestId("source-cell-value")).toBeInViewport();
  await expect(source.getByTestId("source-cell-time")).toHaveText("2");
  await shot(page, "2-source");
  await card.getByTestId(`delivery-source-close-${value.id}`).click();

  // a PDF's value: its page drawn, with the value's box over it
  const other = delivery.subjects.find((s) => s.label === "230-25")!;
  await section.getByTestId(`delivery-subject-open-${other.subject}`).click();
  const pdfCard = await read<Card>(`delivery/subjects/study/${other.subject}`);
  const pdfValue = pdfCard.tables.find((t) => t.kind === "table")!.values[0];
  const otherCard = section.getByTestId(`delivery-card-${other.subject}`);
  await otherCard.getByTestId(`delivery-source-open-${pdfValue.id}`).click();
  const drawn = otherCard.getByTestId(`delivery-source-${pdfValue.id}`);
  await expect(drawn.getByTestId("source-page")).toHaveAttribute("data-drawn", "true", { timeout: 30_000 });
  await expect(drawn.getByTestId("source-box")).toBeVisible();
  await expect(drawn.getByTestId("source-cell-value")).toHaveAttribute("data-role", /value/);
  await shot(page, "3-pdf-source");
  await section.getByTestId(`delivery-subject-open-${study.subject}`).click();

  // --- the one mapping that waits: shown with its table's numbers masked, then approved ---
  await card.getByTestId(`delivery-card-mapping-${waiting}`).click();
  const mapping = page.getByTestId("delivery-mapping-dialog");
  await expect(mapping.getByTestId("mapping-status")).toHaveText("waits for approval");
  await expect(mapping.getByTestId("mapping-columns")).toContainText("Amount (mg)");
  await expect(mapping.getByTestId("mapping-sample")).toContainText("#.#");
  await expect(mapping.getByTestId("mapping-sample").locator("tbody td").filter({ hasText: /\d/ })).toHaveCount(0);   // no digit of the body
  await shot(page, "4-mapping");
  await mapping.getByTestId("mapping-approve-why").fill("the urine table's layout, checked against the file");
  await mapping.getByTestId("mapping-approve-submit").click();
  await expect(mapping.getByTestId("mapping-said")).toContainText("is approved");
  await expect(mapping.getByTestId("mapping-status")).toHaveText("approved");
  await mapping.getByTestId("mapping-close").click();
  // its file is read again with the approved layout; nothing waits, and nothing was lost
  await expect(section.getByTestId("delivery-running")).toHaveCount(0, { timeout: 120_000 });
  await expect(section.getByTestId("delivery-mappings")).toHaveCount(0);
  await expect(section.getByTestId("delivery-total-silent-loss")).toHaveText("0");
  await expect(card.locator('[data-code="MAPPING_NOT_APPROVED"]')).toHaveCount(0);

  // --- the study's blockers, each settled with its decision and the reason ---
  // the stray note with a number: not data
  await card.getByTestId("delivery-outside-accept-0-why").fill("a working note, not data");
  await card.getByTestId("delivery-outside-accept-0-submit").click();
  await expect(card.getByTestId("delivery-blocker-OUTSIDE_NUMBERS")).toHaveCount(0);
  await expect(section.getByTestId("delivery-total-outside")).toHaveText("0");
  // the route no file states
  await card.getByTestId("delivery-gap-enter-route").click();
  await card.getByTestId("delivery-enter-gap-route-value").fill("oral");
  await card.getByTestId("delivery-enter-gap-route-why").fill("from the protocol");
  await card.getByTestId("delivery-enter-gap-route-submit").click();
  await expect(card.getByTestId("delivery-blocker-SCHEMA_GAP")).toHaveCount(0);
  // what the study record still needs before it can be loaded (an oral study also its dosage form): entered on the
  // check that names it
  for (const [needs, entered] of [["needs n,", "24"], ["needs intended_use,", "model_building"], ["needs formulation,", "ir_tablet"]]) {
    const check = card.locator('[data-code="LANDING_FIELD_MISSING"]').filter({ hasText: needs });
    await check.getByRole("button", { name: "Enter it…" }).click();
    await check.locator('[data-testid$="-value"]').fill(entered);
    await check.locator('[data-testid$="-why"]').fill("from the protocol");
    await check.locator('[data-testid$="-submit"]').click();
    await expect(check).toHaveCount(0);
  }
  await expect(card.locator('[data-code="LANDING_FIELD_MISSING"]')).toHaveCount(0);
  await expect(card.getByTestId(`delivery-landing-problem-${study.subject}`)).toHaveCount(0);
  // the required item no file gives: asked of the client
  await card.getByTestId("delivery-dispose-REQ-sys.demographics-choice").selectOption("ask_client");
  await card.getByTestId("delivery-dispose-REQ-sys.demographics-why").fill("asked in the data request");
  await card.getByTestId("delivery-dispose-REQ-sys.demographics-submit").click();
  await expect(card.getByTestId("delivery-requirement-REQ-sys.demographics")).toContainText("asked of the client");
  // the failed check that stands as written: overridden, with why
  const above = card.locator('[data-code="ABOVE_RANGE"]');
  await above.getByRole("button", { name: "Override…" }).click();
  await above.locator('[data-testid$="-why"]').fill("read against the source: written as >1000");
  await above.locator('[data-testid$="-submit"]').click();
  await expect(card.getByTestId("delivery-blocker-CHECK_FAILED")).toHaveCount(0);
  // only the spot check is left
  await expect(card.getByTestId("delivery-blocker-SPOT_CHECK")).toBeVisible();
  await expect(card.locator('[data-testid^="delivery-blocker-"]')).toHaveCount(1);
  await shot(page, "5-settled");

  // --- the spot check: drawn, each value ticked against its source, sent in one request ---
  let tickRequests = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/spot-check")) tickRequests += 1; });
  await card.getByTestId(`spot-draw-${study.subject}`).click();
  const ticks = card.locator('[data-testid^="spot-tick-"]');
  await expect(ticks.first()).toBeVisible();
  const submit = card.getByTestId(`spot-submit-${study.subject}`);
  await expect(submit).toBeDisabled();
  // a row shows the tuple it is ticked for and opens its source
  const firstRow = card.locator('[data-testid^="spot-row-"]').filter({ has: page.locator('[data-testid^="spot-source-"]') }).first();
  await firstRow.locator('[data-testid^="spot-source-"]').click();
  await expect(card.getByTestId(`delivery-spot-${study.subject}`).getByTestId("source-cell-value")).toBeVisible();
  await firstRow.locator('[data-testid^="spot-source-"]').click();
  const wanted = await ticks.count();
  expect(wanted).toBeGreaterThan(0);
  for (let i = 0; i < wanted; i += 1) await ticks.nth(i).check();
  await expect(card.getByTestId(`spot-progress-${study.subject}`)).toContainText(`${wanted} of ${wanted} ticked`);
  expect(tickRequests).toBe(0);                                             // nothing is sent while ticking
  await shot(page, "6-spot-check");
  await submit.click();
  await expect(card.getByTestId(`spot-state-${study.subject}`)).toHaveText("complete");
  expect(tickRequests).toBe(1);                                             // every tick, once
  await expect(card.getByTestId(`delivery-ready-${study.subject}`)).toBeVisible();

  // --- the signed confirmation ---
  await card.getByTestId(`delivery-confirm-${study.subject}`).click();
  const dialog = page.getByTestId("delivery-confirm-dialog");
  await expect(dialog.getByTestId("delivery-confirm-record")).toContainText("230-23");
  await expect(dialog.getByTestId("delivery-confirm-rules")).toContainText("rules UNVERIFIED v0.1");
  await expect(dialog.getByTestId("delivery-confirm-coverage")).toContainText("silent loss 0");
  await expect(dialog.getByTestId("delivery-confirm-blockers")).toHaveCount(0);
  await shot(page, "7-confirm");
  // the API's refusal of a signature without a recent step-up opens the step-up over the dialog (the Keycloak
  // sign-in itself is oidc-signing.spec.ts); cancelled, nothing is signed and the dialog says why
  await page.route("**/subjects/**:confirm", (route) => route.fulfill({
    status: 403, contentType: "application/json",
    body: JSON.stringify({ detail: { code: "STEP_UP_REQUIRED", message: "Confirm your identity to sign." } }),
  }));
  await dialog.getByTestId("delivery-confirm-sign").click();
  await expect(page.getByRole("dialog", { name: "Confirm your identity to sign" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("step-up-dialog")).toHaveCount(0);
  await expect(dialog.getByTestId("delivery-confirm-problem")).toContainText("Confirm your identity to sign.");
  await page.unroute("**/subjects/**:confirm");
  // with the step-up (the DEV sign-in carries a fresh one), the record is signed and its values are loaded
  await dialog.getByTestId("delivery-confirm-sign").click();
  await expect(dialog.getByTestId("delivery-signed")).toContainText(/Dev User \| Reviewed \| \d{4}-\d\d-\d\d/);
  await expect(dialog.getByTestId("delivery-landed")).toContainText("Loaded into the project: 2 datasets");
  await dialog.getByTestId("delivery-confirm-done").click();
  await expect(card.getByTestId(`delivery-manifestation-${study.subject}`)).toContainText("Dev User | Reviewed |");
  await expect(card.getByTestId(`delivery-confirm-${study.subject}`)).toHaveCount(0);
  await expect(section.getByTestId(`delivery-subject-${study.subject}`)).toContainText("confirmed and loaded");
  await shot(page, "8-confirmed");

  // --- on Inputs: the study is in the project once; its own card shows it loaded, with nothing to confirm there ---
  await expect(page.getByTestId("study-230-23")).toHaveCount(1);
  const legacy = page.getByTestId("group-study:230-23");
  await expect(legacy).toContainText("loaded");
  await expect(legacy).not.toContainText("To confirm");
  await expect(page.getByTestId("confirm-study:230-23")).toHaveCount(0);
  // each dataset names the rule its points below the LLOQ are judged with, and how many it leaves out
  await expect(legacy.getByTestId("dataset-blq").first()).toContainText("judged by the rule “omit”");
  // the project holds the study's two datasets (the parent and the metabolite), both from the signed confirmation
  const evidence = await read<{ datasets: { study: { study_id: string }; state: string; decision_reason: string }[] }>("evidence");
  const loaded = evidence.datasets.filter((d) => d.study.study_id === "230-23");
  expect(loaded.map((d) => d.state)).toEqual(["ACCEPTED", "ACCEPTED"]);
  for (const d of loaded) expect(d.decision_reason).toMatch(/^confirmed on Delivery \(cf-\d+, signature /);
});
