// The Delivery section, end to end (contracts 2026-11-12 §8.10): two client files arrive (a messy workbook and a PDF
// report of the made-up Exampleamide), code reads them with the layouts a person signed off earlier (all but one), and
// a reviewer works by exception: the coverage panel, a value's source with its cell highlighted, the one mapping that
// waits, the study's card on Clinical studies (plan 2026-11-14 slice 3) with the delivery's clean-up said once as its
// gate line (the loose note settled with its file, in Client files), its facts filled in one typed form, its other
// blockers each settled with its decision and reason, the spot check ticked and sent once, the decisions listed before
// the signed confirmation, and the study in the project once. A decision on the card costs the decision and the one
// page it changed, and an area shown again reads nothing the page holds (plan 2026-11-14 §2.1; final review OWN-7,
// CODE-4). Software test data: it proves the review path, never a model.
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type Locator, type Page, type Request, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");

type Row = { subject: string; label: string };
type Value = { id: string; verbatim: string | null };
type Card = { tables: { id: string; kind: string; values: Value[]; mapping_id: string | null }[]; blockers: { code: string }[] };

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

/** The requests the page sends while `act` runs and the page settles: to the API (but the escalations bell's, which
 *  polls by itself every few seconds) and for its server-rendered parts. Next's prefetch of a page a link leads to is
 *  said apart ("prefetch …"): it reads no data of this page. */
async function requests(page: Page, act: () => Promise<void>, settle = 1500): Promise<string[]> {
  const seen: string[] = [];
  const hear = (r: Request) => {
    const url = r.url();
    if (url.includes("_rsc=")) {
      const path = new URL(url).pathname.replace(/^\/projects\/[^/]+/, "");
      seen.push(r.headers()["next-router-prefetch"] ? `prefetch ${path || "/"}` : `${r.method()} server render ${path || "/"}`);
    } else if (url.includes("/api/v1/") && !/\/api\/v1\/escalations(\?|$)/.test(url)) {
      seen.push(`${r.method()} ${url.replace(/^.*\/api\/v1\/(projects\/[^/?]+\/)?/, "")}`);
    }
  };
  page.on("request", hear);
  await act();
  await page.waitForTimeout(settle);
  page.off("request", hear);
  return seen;
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

  // --- the files arrive: uploaded on Inputs (the head's Add data), read by code; the review is in Client files ---
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  await page.getByTestId("tab-studies").click();
  await page.getByTestId("client-upload-studies").setInputFiles(fixture.files.map((name) => join(dir, name)));
  await page.getByTestId("tab-files").click();
  const section = page.getByTestId("delivery-section");
  await expect(section.getByTestId("delivery-total-files")).toHaveText("2", { timeout: 120_000 });
  await expect(section.getByTestId("delivery-running")).toHaveCount(0, { timeout: 120_000 });

  // --- the coverage panel: every numeric cell of every table is accounted for; one stray note and nothing unassigned ---
  await expect(section.getByTestId("delivery-total-silent-loss")).toHaveText("0");
  await expect(section.getByTestId("delivery-total-regions")).toHaveText("12");
  await expect(section.getByTestId("delivery-total-outside")).toHaveText("1");
  await expect(section.getByTestId("delivery-total-unassigned")).toHaveText("0");
  await expect(section.getByTestId("delivery-rules")).toHaveText("Intake rules v0.1 · UNVERIFIED");
  const delivery = await read<{ deliveries: { files: { file_id: string; name: string }[] }[]; subjects: Row[] }>("delivery");
  const files = delivery.deliveries.flatMap((d) => d.files);
  expect(files.map((f) => f.name).sort()).toEqual([...fixture.files].sort());
  // each file once, in the one table of files, with one status (plan 2026-11-14 slice 2): the PDF's prose was not read
  const pdf = files.find((f) => f.name.endsWith(".pdf"))!;
  for (const f of files) await expect(page.getByTestId(`file-state-${f.name}`)).toHaveText(f === pdf ? "partly read" : "read");
  // a file's own reading opens under its row: its regions, and how long each stage took
  await page.getByTestId(`file-toggle-${pdf.name}`).click();
  await expect(page.getByTestId(`delivery-file-state-${pdf.file_id}`)).toHaveText("partly read");   // the row's one status
  await page.getByTestId(`delivery-file-toggle-${pdf.file_id}`).click();
  await expect(page.getByTestId(`delivery-regions-${pdf.file_id}`)).toContainText("not read: no text reader is set up");   // its prose: not read, and why in plain words
  await expect(page.getByTestId(`delivery-stages-${pdf.file_id}`)).toContainText("finding the tables and texts");
  await page.getByTestId(`file-toggle-${pdf.name}`).click();
  await expect(page.getByTestId(`delivery-regions-${pdf.file_id}`)).toHaveCount(0);
  await expect(section.getByTestId("delivery-files")).toHaveCount(0);                        // no second list of the files
  // the layout that waits is checked in To do's queue (plan 2026-11-14 slice 4), where it holds up the study's signature
  await expect(section.getByTestId("delivery-in-todo")).toContainText("1 table layout to check");
  await page.getByTestId("tab-todo").click();
  await expect(page.getByTestId("todo-group-layouts").getByTestId(`delivery-mapping-${waiting}`)).toBeVisible();
  await expect(page.getByTestId("todo-group-layouts")).toContainText("To decide");
  await page.getByTestId("tab-files").click();
  await shot(page, "1-coverage");

  // --- the study's card is on Clinical studies, its row in the list of the client's studies; the delivery's clean-up
  // (here the stray note) is its one gate line, not a blocker of its own, and "Confirm and sign" waits on it ---
  const study = delivery.subjects.find((s) => s.label === "230-23")!;
  // a card, or a table of values on it, opened unless it is open already
  const expand = async (toggle: Locator) => {
    await expect(toggle).toBeVisible();
    if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  };
  const open = (subject: string) => expand(page.getByTestId(`delivery-subject-open-${subject}`));
  await page.getByTestId("tab-studies").click();
  await expect(page.getByTestId("studies-list")).toBeVisible();
  await open(study.subject);
  const card = page.getByTestId(`delivery-card-${study.subject}`);
  for (const code of ["SCHEMA_GAP", "CHECK_FAILED", "SPOT_CHECK"]) {
    await expect(card.getByTestId(`delivery-blocker-${study.subject}-${code}`)).toBeVisible();
  }
  await expect(card.getByTestId(`delivery-blocker-${study.subject}-OUTSIDE_NUMBERS`)).toHaveCount(0);
  await expect(card.getByTestId(`delivery-gate-${study.subject}`)).toHaveAttribute("data-codes", /OUTSIDE_NUMBERS/);
  await expect(card.getByTestId(`delivery-gate-${study.subject}`)).toContainText("Waits for the delivery clean-up");
  await expect(card.getByTestId(`delivery-confirm-${study.subject}`)).toBeDisabled();
  const before = await read<Card>(`delivery/subjects/study/${study.subject}`);
  const value = before.tables.flatMap((t) => t.values).find((v) => v.verbatim === "25.2")!;
  // a table of the card is one line until opened (unless a row of it needs the person)
  const table = before.tables.find((t) => t.values.some((v) => v.id === value.id))!;
  await expand(card.getByTestId(`delivery-table-toggle-${table.id}`));
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
  await open(other.subject);
  const pdfCard = await read<Card>(`delivery/subjects/study/${other.subject}`);
  const pdfTable = pdfCard.tables.find((t) => t.kind === "table")!;
  const pdfValue = pdfTable.values[0];
  const otherCard = page.getByTestId(`delivery-card-${other.subject}`);
  await expand(otherCard.getByTestId(`delivery-table-toggle-${pdfTable.id}`));
  await otherCard.getByTestId(`delivery-source-open-${pdfValue.id}`).click();
  const drawn = otherCard.getByTestId(`delivery-source-${pdfValue.id}`);
  await expect(drawn.getByTestId("source-page")).toHaveAttribute("data-drawn", "true", { timeout: 30_000 });
  await expect(drawn.getByTestId("source-box")).toBeVisible();
  await expect(drawn.getByTestId("source-cell-value")).toHaveAttribute("data-role", /value/);
  await shot(page, "3-pdf-source");
  await page.getByTestId(`delivery-subject-open-${other.subject}`).click();      // closed again

  // --- the one mapping that waits: shown with its table's numbers masked, then approved ---
  // a layout is checked from the head of the table it reads (not listed again apart)
  const urine = before.tables.find((t) => t.mapping_id === waiting)!;
  await card.getByTestId(`delivery-table-mapping-${urine.id}`).click();
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
  await expect(card.locator('[data-code="MAPPING_NOT_APPROVED"]')).toHaveCount(0, { timeout: 120_000 });
  await expect(card.getByTestId(`delivery-card-mappings-${study.subject}`)).toHaveCount(0);
  await page.getByTestId("tab-files").click();
  await expect(section.getByTestId("delivery-running")).toHaveCount(0, { timeout: 120_000 });
  await expect(section.getByTestId("delivery-in-todo")).not.toContainText("table layout");
  await expect(section.getByTestId("delivery-total-silent-loss")).toHaveText("0");

  // --- the delivery's clean-up: the stray note with a number is marked as not data with its file's other loose
  // numbers, in To do's table of numbers not read (plan 2026-11-14 slice 4) ---
  const workbook = files.find((f) => !f.name.endsWith(".pdf"))!;
  await page.getByTestId("tab-todo").click();
  await page.getByTestId(`notread-mark-open-${workbook.file_id}`).click();
  await page.getByTestId(`notread-mark-${workbook.file_id}-why`).fill("a working note, not data");
  await page.getByTestId(`notread-mark-${workbook.file_id}-submit`).click();
  await expect(page.getByTestId(`notread-${workbook.file_id}`)).toHaveCount(0);
  await page.getByTestId("tab-files").click();
  await expect(section.getByTestId("delivery-total-outside")).toHaveText("0");
  await page.getByTestId("tab-studies").click();
  await open(study.subject);
  await expect(card.getByTestId(`delivery-gate-${study.subject}`)).toHaveCount(0);

  // --- the study's facts no file states, in one typed form with one reason: the route first (an oral study then also
  // needs its dosage form), then what the study record needs before it can be loaded ---
  const facts = card.getByTestId(`delivery-facts-form-${study.subject}`);
  // pressed with no fact given, the button says what it needs, beside it (final review CODE-6: it was disabled, silent);
  // the label names the control it is for (A11Y-10)
  await facts.getByTestId(`delivery-facts-form-${study.subject}-submit`).click();
  await expect(facts.getByTestId(`delivery-facts-form-${study.subject}-missing`)).toHaveText(/^Choose or type (at least one of the facts|the fact)$/);
  await expect(facts.getByLabel("Route", { exact: true })).toHaveAttribute("data-testid", `delivery-enter-gap-${study.subject}-route-value`);
  await card.getByTestId(`delivery-enter-gap-${study.subject}-route-value`).selectOption("oral");
  await expect(facts.getByTestId(`delivery-facts-form-${study.subject}-missing`)).toHaveCount(0);
  await facts.getByTestId(`delivery-facts-form-${study.subject}-why`).fill("from the protocol");
  const saved = await requests(page, async () => {
    await facts.getByTestId(`delivery-facts-form-${study.subject}-submit`).click();
    await expect(card.getByTestId(`delivery-gap-${study.subject}-route`)).toHaveCount(0);
  });
  // a decision on the card costs the decision and the delivery page read again (final review OWN-7, CODE-4: 17 requests
  // before round 3); the card is the decision's answer, written into the page
  expect(saved, saved.join("\n")).toEqual([`POST delivery/subjects/study/${study.subject}:enter`, "GET delivery"]);
  // saved, the reason is not carried over unseen to the next facts (final review CODE-7): the field is empty, and "use
  // last" offers it for this kind of decision
  await expect(facts.getByTestId(`delivery-facts-form-${study.subject}-why`)).toHaveValue("");
  await expect(facts.getByTestId(`delivery-facts-form-${study.subject}-last`)).toHaveAccessibleName("Use the last reason: from the protocol");
  await expect(card.getByTestId(`delivery-blocker-${study.subject}-SCHEMA_GAP`)).toHaveCount(0);
  for (const [label, entered] of [["Number of subjects", "24"], ["Purpose of the study", "model_building"], ["Dosage form", "ir_tablet"]]) {
    const control = facts.locator(".facts-row", { hasText: label }).locator('[data-testid$="-value"]');
    if (await control.evaluate((e) => e.tagName) === "SELECT") await control.selectOption(entered);
    else await control.fill(entered);
  }
  await facts.getByTestId(`delivery-facts-form-${study.subject}-why`).fill("from the protocol");
  await facts.getByTestId(`delivery-facts-form-${study.subject}-submit`).click();
  await expect(card.locator('[data-code="LANDING_FIELD_MISSING"]')).toHaveCount(0);
  await expect(facts).toHaveCount(0);
  await expect(card.getByTestId(`delivery-landing-problem-${study.subject}`)).toHaveCount(0);
  // the required item no file gives: asked of the client
  await card.getByTestId(`delivery-dispose-${study.subject}-REQ-sys.demographics-choice`).selectOption("ask_client");
  await card.getByTestId(`delivery-dispose-${study.subject}-REQ-sys.demographics-why`).fill("asked in the data request");
  const disposed = await requests(page, async () => {
    await card.getByTestId(`delivery-dispose-${study.subject}-REQ-sys.demographics-submit`).click();
    await expect(card.getByTestId(`delivery-requirement-${study.subject}-REQ-sys.demographics`)).toContainText("asked of the client");
  });
  expect(disposed, disposed.join("\n")).toEqual([`POST delivery/subjects/study/${study.subject}:dispose`, "GET delivery"]);   // 31 before
  // the failed check that stands as written: accepted as is, with why
  const above = card.locator('[data-code="ABOVE_RANGE"]');
  await above.locator('[data-testid^="delivery-override-open-"]').click();
  await above.locator('[data-testid$="-why"]').fill("read against the source: written as >1000");
  // the page's own reads of the cards (once it is idle) are done before the decision is counted
  await expect(page.getByTestId("status-checking")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  const accepted = await requests(page, async () => {
    await above.locator('[data-testid$="-submit"]').click();
    await expect(card.getByTestId(`delivery-blocker-${study.subject}-CHECK_FAILED`)).toHaveCount(0);
  });
  expect(accepted, accepted.join("\n")).toEqual([`POST delivery/subjects/study/${study.subject}:override`, "GET delivery"]);   // 18 before
  // an area whose reads the page holds is shown with no request (4 and 9 before round 3): Client files, then the card again
  const toFiles = await requests(page, async () => {
    await page.getByTestId("tab-files").click();
    await expect(section).toBeVisible();
  });
  expect(toFiles, toFiles.join("\n")).toEqual([]);
  const toStudies = await requests(page, async () => {
    await page.getByTestId("tab-studies").click();
    await expect(card).toBeVisible();
  });
  expect(toStudies, toStudies.join("\n")).toEqual([]);
  // only the spot check is left
  await expect(card.getByTestId(`delivery-blocker-${study.subject}-SPOT_CHECK`)).toBeVisible();
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
  // the ticks are recorded, and the card, which says how far the spot check is, is read again: nothing else
  const recorded = await requests(page, async () => {
    await submit.click();
    await expect(card.getByTestId(`spot-state-${study.subject}`)).toHaveText("complete");
  });
  expect(recorded, recorded.join("\n")).toEqual([`POST delivery/subjects/study/${study.subject}/spot-check`,
                                                  `GET delivery/subjects/study/${study.subject}`]);
  expect(tickRequests).toBe(1);                                             // every tick, once
  await expect(card.getByTestId(`delivery-ready-${study.subject}`)).toBeVisible();
  // before the signature, the decisions made on the study, each with who made it and why
  const decisions = card.getByTestId(`delivery-decisions-${study.subject}`);
  await expect(decisions).toContainText("Accepted as is");
  await expect(decisions).toContainText("read against the source: written as >1000");
  await expect(decisions).toContainText("asked of the client");
  await expect(decisions).toContainText("Table layout approved");

  // --- the signed confirmation ---
  await card.getByTestId(`delivery-confirm-${study.subject}`).click();
  const dialog = page.getByTestId("delivery-confirm-dialog");
  await expect(dialog.getByTestId("delivery-confirm-record")).toContainText("230-23");
  await expect(dialog.getByTestId("delivery-confirm-rules")).toContainText("v0.1, UNVERIFIED");
  await expect(dialog.getByTestId("delivery-confirm-coverage")).toContainText("0 numbers not read in their tables");
  await expect(dialog.getByTestId("delivery-confirm-blockers")).toHaveCount(0);
  await shot(page, "7-confirm");
  // the API's refusal of a signature without a recent step-up opens the step-up over the dialog (the Keycloak
  // sign-in itself is oidc-signing.spec.ts); cancelled, nothing is signed and the dialog says why
  await page.route("**/subjects/**:confirm", (route) => route.fulfill({
    status: 403, contentType: "application/json",
    body: JSON.stringify({ detail: { code: "STEP_UP_REQUIRED", message: "Confirm your identity to sign." } }),
  }));
  // pressed from the keyboard: the step-up takes the focus, and gives it back to the signing dialog's button when it
  // closes (final review A11Y-1: the button was disabled while sent, so the focus fell to the page and Tab and Escape
  // left the dialog open behind)
  await dialog.getByTestId("delivery-confirm-sign").focus();
  await page.keyboard.press("Enter");
  const stepUp = page.getByRole("dialog", { name: "Confirm your identity to sign" });
  await expect(stepUp).toBeVisible();
  await expect(stepUp).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("step-up-dialog")).toHaveCount(0);
  await expect(dialog.getByTestId("delivery-confirm-problem")).toContainText("Confirm your identity to sign.");
  await expect(dialog.getByTestId("delivery-confirm-sign")).toBeFocused();
  for (let i = 0; i < 4; i += 1) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((d) => d.contains(document.activeElement)), "Tab stays in the signing dialog").toBe(true);
  }
  await page.unroute("**/subjects/**:confirm");
  // with the step-up (the DEV sign-in carries a fresh one), the record is signed and its values are loaded
  await dialog.getByTestId("delivery-confirm-sign").click();
  await expect(dialog.getByTestId("delivery-signed")).toContainText(/Dev User \| Reviewed \| \d{4}-\d\d-\d\d/);
  // the signed view keeps the focus in the dialog (its panel), so its Done is one Tab away, never the page's top
  await expect.poll(() => dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
  await expect(dialog.getByTestId("delivery-landed")).toContainText("Loaded into the project: 2 datasets");
  await dialog.getByTestId("delivery-confirm-done").click();
  await expect(card.getByTestId(`delivery-manifestation-${study.subject}`)).toContainText("Dev User | Reviewed |");
  await expect(card.getByTestId(`delivery-confirm-${study.subject}`)).toHaveCount(0);
  // the card says who signed it and that it is in the model; its row in the list says Done
  await expect(page.locator('[data-testid^="card-loaded-"]')).toContainText("Signed by Dev User");
  await expect(page.locator(`[data-testid="study-row-study:230-23"] [data-testid="study-status-study:230-23"]`)).toHaveText("Done");
  await shot(page, "8-confirmed");

  // --- on Inputs: the study is in the project once; the sheet form's reading of it, folded on its card, shows it
  // loaded, with nothing to confirm there ---
  await expect(page.getByTestId("study-230-23")).toHaveCount(1);
  await page.getByTestId("how-read-study:230-23").locator("summary").click();
  const legacy = page.getByTestId("group-study:230-23");
  await expect(legacy).toContainText("in the model");
  await expect(legacy).not.toContainText("To confirm");
  await expect(page.getByTestId("confirm-study:230-23")).toHaveCount(0);
  // each dataset names the rule its points below the LLOQ are judged with, and how many it leaves out (drawn once, under
  // the card's Observed data, not again in the sheet form's reading)
  await expect(page.getByTestId("card-observed-study:230-23").getByTestId("dataset-blq").first()).toContainText("judged by the rule “omit”");
  // the project holds the study's two datasets (the parent and the metabolite), both from the signed confirmation
  const evidence = await read<{ datasets: { study: { study_id: string }; state: string; decision_reason: string }[] }>("evidence");
  const loaded = evidence.datasets.filter((d) => d.study.study_id === "230-23");
  expect(loaded.map((d) => d.state)).toEqual(["ACCEPTED", "ACCEPTED"]);
  for (const d of loaded) expect(d.decision_reason).toMatch(/^confirmed on Delivery \(cf-\d+, signature /);
});
