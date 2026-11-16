// T-47 / F-402: D-15 on Inputs (final review INT-1, INT-2, INT-3). With the project's blinding on, two studies of a
// delivery are entered for external validation on their cards, with a reason that quotes a value: the delivery then
// blinds them, and no view of Inputs shows their values, the digits of the reasons, their pages' lines or their sheets.
// The card lists its decisions with the reason's digits masked ("Entered for Purpose of the study (value withheld)"),
// offers no "Confirm now with the sheet form" and withholds the sheet form's reading; Client files withholds the
// report's page lines (no peek) and the workbook's blinded sheet; the digitizer neither offers nor draws the report, and
// its original is not served. Software test data (the made-up Exampleamide), never a model.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH, finishStart, projectWithInputs } from "./fixtures/inputs";

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
  // and says why, so a wrong match is seen (round 3)
  await expect(card.getByTestId(`delivery-blinded-why-${fed.subject}`)).toHaveText(", because it is entered for external validation on its card");
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
  // the reading's withheld line says why too, and so does the list's chip (round 4: wherever it is withheld)
  await expect(body.locator('[data-testid^="how-read-withheld-"]')).toContainText(", because it is entered for external validation on its card,");
  await expect(page.locator('[data-testid^="study-blinded-why-"]').filter({ hasText: "entered for external validation" })).toHaveCount(2);
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

  // --- the digitizer: the report holds 230-25's values, so it is neither offered nor drawn, and its original is not
  // served until the plan is signed (final review INT-3) ---
  type Doc = { name: string; sha256: string; blinded: boolean; blinded_by: string[] };
  const reportDoc = (await read<{ documents: Doc[] }>("documents")).documents.find((d) => d.name === pdf)!;
  expect(reportDoc.blinded).toBe(true);
  expect(reportDoc.blinded_by).toEqual(["230-25"]);
  const original = await request.get(`${api}/documents/${reportDoc.sha256}/raw`, { headers: AUTH });
  expect(original.status()).toBe(409);
  const raws: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/raw")) raws.push(r.url()); });
  await page.getByTestId("tab-studies").click();
  await page.getByTestId("open-digitizer").click();
  const digitizer = page.getByTestId("digitizer");
  // it names the blinded study it waits for, and that the whole file waits, its other figures too (round 3)
  await expect(digitizer.getByTestId("digitize-withheld")).toContainText(
    `${pdf} is not offered here until the plan is signed: it holds the values of study 230-25, blinded until the plan is signed, `
    + "and the whole file waits until then, its other figures and pages too");
  await expect(digitizer.getByTestId("digitize-document")).toHaveCount(0);
  await expect(digitizer.locator("canvas")).toHaveCount(0);
  // asked for by a link to its page (the reading tray's Digitize, or one kept from before): said, and not drawn
  await page.goto(`/projects/${projectId}/inputs?tab=studies&digitize=${reportDoc.sha256}&page=2#observed-datasets`);
  await expect(page.getByTestId("digitize-withheld")).toContainText(`${pdf} is not drawn: it holds the values of study 230-25, blinded`);
  await expect(page.getByTestId("digitizer").locator("canvas")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("3-digitizer-withheld.png"), fullPage: true });
  expect(raws).toEqual([]);

  // the APIs the page reads give none of it either: what they say, not when they said it (final review round 5: an
  // answer sent at hh:mm:35.6… failed this once on its own timestamp)
  const said = async (path: string) => (await (await request.get(`${api}/${path}`, { headers: AUTH })).text())
    .replace(/\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)?/g, "<time>");
  expect(await said("client-review")).not.toContain("35.6");
  expect(await said("audit?limit=2000")).not.toContain("35.6");
});

// Round 4 (round 3's skeptic, blinding scope b): a study confirmed with the sheet form (a filled client-data template's)
// that is blinded says why on its card's visible withheld line and in the list, not only in the closed "How the files
// were read" fold: the group's own reason (`blinded_why`), from the delivery's card where the study has one.
test("a template study blinded on its delivery card says why on its sheet-form card and in the list", async ({ page, request }) => {
  const dir = mkdtempSync(join(tmpdir(), "blinded-template-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "client_workbooks.py"), dir], { cwd: REPO });
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Clientamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral 10 mg tablet.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  const api = `/api/v1/projects/${projectId}`;
  expect((await request.post(`${api}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const up = await request.post(`${api}/client-data`, { headers: AUTH, multipart: {
    files: { name: "client-template-filled.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             buffer: readFileSync(join(dir, "client-template-filled.xlsx")) } } });
  expect(up.status(), await up.text()).toBe(201);
  const on = await request.put(`${api}/blinding`, { headers: AUTH, data: { on: true, reason: "external validation is blinded until the MAP is signed" } });
  expect(on.ok(), await on.text()).toBeTruthy();
  // the delivery holds the template's study too (confirmed with the sheet form): entered for external validation there
  let study: { subject: string; label: string; confirm_on: string } | undefined;
  for (let i = 0; i < 60 && !study; i++) {
    const page_ = (await (await request.get(`${api}/delivery`, { headers: AUTH })).json()).data as
      { running: boolean; subjects: { subject: string; label: string; confirm_on: string; subject_type: string }[] };
    study = page_.running ? undefined : page_.subjects.find((s) => s.subject_type === "study" && s.label === "CL-01");
    if (!study) await page.waitForTimeout(1000);
  }
  expect(study?.confirm_on).toBe("client-review");
  const entered = await request.post(`${api}/delivery/subjects/study/${study!.subject}:enter`, { headers: AUTH,
    data: { field: "intended_use", value: "external_validation", why: "kept for external validation" } });
  expect(entered.ok(), await entered.text()).toBeTruthy();
  const group = ((await (await request.get(`${api}/client-review`, { headers: AUTH })).json()).data.groups as
    { id: string; blinded: boolean; blinded_why: string | null }[]).find((g) => g.id === "study:CL-01")!;
  expect(group).toMatchObject({ blinded: true, blinded_why: "it is entered for external validation on its card" });

  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  await expect(page.getByTestId("study-blinded-why-study:CL-01")).toHaveText("because it is entered for external validation on its card");
  const toggle = page.getByTestId("toggle-study:CL-01");
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  await expect(page.getByTestId("group-withheld-study:CL-01")).toContainText(
    "Withheld: study CL-01 is blinded until the plan is signed, because it is entered for external validation on its card.");
  await page.screenshot({ path: test.info().outputPath("4-template-study-withheld-why.png"), fullPage: true });

  // Round 5: the reason leads where it can be changed. The sheet-form card shows the delivery's reading only for reference,
  // so its words open that reading at the study's purpose, where "Change the purpose…" is offered (its value withheld)
  const reason = page.getByTestId("group-withheld-why-study:CL-01-purpose");
  await expect(reason).toHaveText("it is entered for external validation on its card");
  await reason.click();
  const change = page.getByTestId(`delivery-purpose-${study!.subject}-intended_use`);
  await expect(change).toBeFocused();
  await expect(change).toHaveText("Change the purpose…");
  await page.screenshot({ path: test.info().outputPath("5-template-study-purpose-to-change.png"), fullPage: true });
  // wrong, it is changed there: the study is no longer blinded by it, and the sheet form's reading of it is shown again
  await change.click();
  const form = page.locator(`[data-testid^="purpose-"][data-testid$="-value"]`);
  await expect(form).toBeFocused();
  await form.selectOption("model_building");
  await page.locator(`[data-testid^="purpose-"][data-testid$="-why"]`).fill("entered on the wrong study: CL-01 builds the model");
  await page.locator(`[data-testid^="purpose-"][data-testid$="-submit"]`).click();
  await expect(page.getByTestId("group-withheld-study:CL-01")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByTestId("study-blinded-why-study:CL-01")).toHaveCount(0);
  const after = ((await (await request.get(`${api}/client-review`, { headers: AUTH })).json()).data.groups as
    { id: string; blinded: boolean }[]).find((g) => g.id === "study:CL-01")!;
  expect(after.blinded).toBe(false);
});

// Round 5 (round 4's skeptic): why is said wherever a study is withheld, also where round 4 left it out: a product's card
// head (blinded because it holds a blinded study's values), Populations and individuals, and the delivery card's own
// withheld line leads to the purpose that blinds it. The delivery of e2e/fixtures/delivery.py; 230-23's profile is given
// the product, then 230-23 is entered for external validation. Software test data (the made-up Exampleamide), never a model.
test("a blinded product says why on its card head, Populations says why, and the reason leads to the purpose", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 50 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const api = `/api/v1/projects/${projectId}`;
  const read = async <T,>(path: string) => (await (await request.get(`${api}/${path}`, { headers: AUTH })).json()).data as T;
  const dir = mkdtempSync(join(tmpdir(), "blinded-product-"));
  const printed = execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "delivery.py"),
                                      join(process.env.E2E_DATA_DIR!, "read-root"), projectId, dir], { cwd: REPO }).toString();
  const fixture = JSON.parse(printed.trim().split("\n").pop()!) as { files: string[] };
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  await page.getByTestId("client-upload-studies").setInputFiles(fixture.files.map((name) => join(dir, name)));
  await page.getByTestId("tab-files").click();
  const section = page.getByTestId("delivery-section");
  await expect(section.getByTestId("delivery-total-files")).toHaveText("2", { timeout: 120_000 });
  await expect(section.getByTestId("delivery-running")).toHaveCount(0, { timeout: 120_000 });
  const on = await request.put(`${api}/blinding`, { headers: AUTH, data: { on: true, reason: "external validation is blinded until the MAP is signed" } });
  expect(on.ok(), await on.text()).toBeTruthy();

  // a person says the product 230-23 dosed (one of its values), then enters 230-23 for external validation
  type Row_ = Row & { subject_type: string; batches: { id: string }[] };
  const subjects = (await read<{ subjects: Row_[] }>("delivery")).subjects;
  const study = subjects.find((s) => s.label === "230-23")!, product = subjects.find((s) => s.subject_type === "product")!;
  const card = await read<{ tables: { values: { id: string; verbatim: string | null }[] }[] }>(`delivery/subjects/study/${study.subject}`);
  const value = card.tables.flatMap((t) => t.values).find((v) => v.verbatim === "25.2")!;
  const assigned = await request.post(`${api}/delivery/values:assign`, { headers: AUTH, data: {
    targets: [value.id.split("#")[0]], product: product.subject, batch: product.batches[0].id, why: "the study dosed this batch" } });
  expect(assigned.ok(), await assigned.text()).toBeTruthy();
  const entered = await request.post(`${api}/delivery/subjects/study/${study.subject}:enter`, { headers: AUTH,
    data: { field: "intended_use", value: "external_validation", why: "kept for external validation" } });
  expect(entered.ok(), await entered.text()).toBeTruthy();
  expect((await read<{ subjects: Row[] }>("delivery")).subjects.filter((s) => s.blinded).map((s) => s.label).sort())
    .toEqual([product.label, "230-23"].sort());

  // the product's card head: the chip and, beside it, why
  await page.goto(`/projects/${projectId}/inputs?tab=formulations`);
  const productCard = page.locator("[data-testid^='product-card-']", { has: page.locator(".card-title", { hasText: product.label }) });
  await expect(productCard.locator("[data-testid^='card-blinded-why-']")).toHaveText("because it holds the values of a blinded study");
  await expect(productCard.locator("[data-testid^='card-blinded-product']")).toHaveText("blinded until the plan is signed");
  // Populations and individuals: the study's line says why, as everywhere it is withheld
  await page.getByTestId("tab-individuals").click();
  await expect(page.getByTestId("individual-blinded-study:230-23")).toHaveText(
    "Blinded until the plan is signed, because it is entered for external validation on its card.");
  await page.screenshot({ path: test.info().outputPath("6-populations-why.png"), fullPage: true });
  // the study's card: its withheld line's reason leads to its purpose on the card, where it is changed
  await page.getByTestId("tab-studies").click();
  const toggle = page.getByTestId(`delivery-subject-open-${study.subject}`);
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  await page.getByTestId(`delivery-blinded-why-${study.subject}`).getByRole("button", { name: /^it is entered for external validation on its card/ }).click();
  await expect(page.getByTestId(`delivery-purpose-${study.subject}-intended_use`)).toBeFocused();
  await expect(page.locator("body")).not.toContainText("25.2");
});

// Round 5: a dataset blinded by the project's list says why on its line (round 4 left "blinded until the MAP is signed"
// without a reason, plan §5), its plan's part leading to the studies' roles on Review & sign, where they are decided.
test("a blinded dataset says why, and the plan's part of the reason leads to where the roles are decided", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Blindamide", [
    { study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }, { study_id: "po-10", route: "oral", dose_mg: 10 },
    { study_id: "po-50", route: "oral", dose_mg: 50 }, { study_id: "po-100", route: "oral", dose_mg: 100 },
  ]);
  const api = `/api/v1/projects/${projectId}`;
  expect((await request.get(`${api}/plan`, { headers: AUTH })).ok()).toBeTruthy();           // the plan places the studies
  const on = await request.put(`${api}/blinding`, { headers: AUTH, data: { on: true, reason: "ICH M15 §4.1 for this project" } });
  expect(on.ok(), await on.text()).toBeTruthy();
  const datasets = (await (await request.get(`${api}/evidence`, { headers: AUTH })).json()).data.datasets as
    { id: string; blinded?: boolean; blinded_why?: string | null }[];
  const blinded = datasets.find((d) => d.blinded)!;
  expect(blinded.blinded_why).toBe("the plan places it in S5 (external validation)");

  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  const why = page.getByTestId(`blinded-why-${blinded.id}`).first();
  await expect(why).toHaveText("Its values are blinded until the plan is signed, because the plan places it in S5 (external validation) (ICH M15).");
  const link = why.getByRole("link", { name: /^the plan places it in S5 \(external validation\)/ });
  await expect(link).toHaveAttribute("href", `/projects/${projectId}/plan#review-studies`);
  await page.screenshot({ path: test.info().outputPath("7-dataset-why.png"), fullPage: true });
  await link.click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/plan#review-studies$`));
  await expect(page.locator("#review-studies")).toBeVisible();
});

// Round 6 (the owner's copy, 7bb1): a study the delivery blinds by its card, the project's list not holding it, while a
// dataset of its name is listed (the Fed sheet read with the sheet form for model building before the card said what it
// is for). On 7bb1 its card said "what the sheet form read of it is shown once the plan is signed" beside the dataset's
// line offering "Show the points": the evidence redacted the list's studies only. Here the dataset is still to confirm,
// so the card is the delivery's, its sheet-form reading folded under "How the files were read" saying the same. One
// rule now: the line withholds the points and says why. Software test data (the made-up Exampleamide), never a model.
test("a study the delivery blinds withholds its sheet-form dataset's points beside the line that says they are withheld", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 50 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const api = `/api/v1/projects/${projectId}`;
  const read = async <T,>(path: string) => (await (await request.get(`${api}/${path}`, { headers: AUTH })).json()).data as T;
  const dir = mkdtempSync(join(tmpdir(), "blinded-sheet-dataset-"));
  const printed = execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "delivery.py"),
                                      join(process.env.E2E_DATA_DIR!, "read-root"), projectId, dir], { cwd: REPO }).toString();
  const book = (JSON.parse(printed.trim().split("\n").pop()!) as { files: string[] }).files.find((n) => n.endsWith(".xlsx"))!;
  const up = await request.post(`${api}/client-data`, { headers: AUTH, multipart: {
    files: { name: book, mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: readFileSync(join(dir, book)) } } });
  expect(up.status(), await up.text()).toBe(201);
  type Page_ = { running: boolean; deliveries: { files: { sha256: string }[] }[]; subjects: (Row & { subject_type: string })[] };
  await expect.poll(async () => {
    const d = await read<Page_ | null>("delivery");
    const c = await read<{ running: boolean } | null>("client-data");
    return Boolean(d && !d.running && d.deliveries.flatMap((x) => x.files).length === 1 && c && !c.running);
  }, { timeout: 300_000, intervals: [2000] }).toBe(true);
  const on = await request.put(`${api}/blinding`, { headers: AUTH, data: { on: true, reason: "external validation is blinded until the MAP is signed" } });
  expect(on.ok(), await on.text()).toBeTruthy();
  // the Fed sheet read with the sheet form as study 231-24, for model building: its dataset is listed, to confirm
  const delivered = await read<Page_>("delivery");
  const sid = `file-${delivered.deliveries.flatMap((d) => d.files)[0].sha256.slice(0, 12)}`;
  const finished = await request.post(`${api}/client-review:finish`, { headers: AUTH, data: { file: sid, sheet: "Fed", answers: {
    n: 6, route: "oral", formulation: "ir_tablet", food_state: "fed", dose: 100, purpose: "model_building" } } });
  expect(finished.ok(), await finished.text()).toBeTruthy();
  type Dataset = { id: string; study: { study_id: string }; blinded?: boolean; blinded_why?: string | null; series: { values: (number | null)[] }[] };
  const fed = async () => (await read<{ datasets: Dataset[] }>("evidence")).datasets.find((d) => d.study.study_id === "231-24")!;
  expect((await fed()).blinded ?? false).toBe(false);
  // then 231-24 entered for external validation on its delivery card: the delivery blinds it, the list does not
  const study = delivered.subjects.find((s) => s.label === "231-24")!;
  const entered = await request.post(`${api}/delivery/subjects/study/${study.subject}:enter`, { headers: AUTH,
    data: { field: "intended_use", value: "external_validation", why: WHY } });
  expect(entered.ok(), await entered.text()).toBeTruthy();
  expect((await read<{ external: string[] }>("blinding")).external).not.toContain("231-24");
  const dataset = await fed();
  expect(dataset.blinded).toBe(true);
  expect(dataset.blinded_why).toBe("it is entered for external validation on its card");
  expect(dataset.series.flatMap((s) => s.values).every((v) => v === null)).toBe(true);

  // its card: the sheet form's line says what it read is withheld, and the dataset's line beside it withholds the points
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  const toggle = page.getByTestId(`delivery-subject-open-${study.subject}`);
  await expect(toggle).toBeVisible({ timeout: 30_000 });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  const card = page.getByTestId(`delivery-card-${study.subject}`);
  await card.locator("details.how-read > summary", { hasText: "How the files were read: the sheet form" }).click();
  await expect(card.locator('[data-testid^="how-read-withheld-"]')).toContainText(
    "Withheld: the study is blinded until the plan is signed, because it is entered for external validation on its card, and the "
    + "sheet form's reading shows its values.");
  // round 6: its signature is not offered either (the API refuses it); where it would be, the wait and why
  await expect(card.getByTestId(`delivery-confirm-${study.subject}`)).toHaveCount(0);
  await expect(card.getByTestId(`delivery-sign-waits-${study.subject}`)).toHaveText(
    "Signing waits until the plan is signed, because it is entered for external validation on its card.");
  const line = page.getByTestId(`dataset-${dataset.id}`);
  await expect(line.getByTestId(`dataset-blinded-${dataset.id}`)).toHaveText(/blinded until\s+the plan is signed/);
  await expect(line.getByRole("button", { name: /^Show the points/ })).toHaveCount(0);
  await expect(line.getByTestId(`blinded-why-${dataset.id}`)).toContainText("because it is entered for external validation on its card");
  await page.screenshot({ path: test.info().outputPath("8-sheet-dataset-withheld.png"), fullPage: true });
});
