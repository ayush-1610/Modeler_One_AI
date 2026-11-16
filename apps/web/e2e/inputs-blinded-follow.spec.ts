// D-15 followed in the same visit (final review rounds 5 and 6): a decision made on this page can blind more than the
// subject it is made on, and these flows show it without a new visit. With the project's blinding on and no plan, the
// MS-01 split proposes a role for every study of the catalog: a study that joins the catalog (its signature lands its
// dataset, its sheet form's group is confirmed) can be proposed for S5 and is then blinded, with every product that
// holds its values; a study entered for external validation on its card is blinded the same way. Round 4's signed
// confirmation read no other card again, so the product's card kept showing the blinded study's values and offered its
// spot check, which the API refuses; and a sheet-form confirmation did not read the client's files again, so the sheet
// of a study the split had just blinded stayed readable. Round 5 read again only the cards whose delivery rows changed,
// while the API also withholds by file and by name: the why of a decision about the newly blinded study's file stayed
// readable on another study's card, and a study already in the model kept its row on the Studies list and its points.
// Round 6 has one rule read every answer of the project the blinding changes, once (round 7 adds the reading tray, whose
// figure suggestions are withheld by file too). What is not covered here: a change another person makes is seen at the
// next read, and a decision that starts a reading is followed at its end.
// Software test data (the made-up Exampleamide, its literature studies and a published table of the reading evaluation
// set), never a model; the stub engine is a software fixture.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type APIRequestContext, type Locator, type Page, test } from "@playwright/test";

import { AUTH, finishStart, openFile } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const OUTSIDE_NOTE = "s:'Summary'!A10";        // the workbook's working note with a number: not data
const BLINDING = { on: true, reason: "external validation is blinded until the MAP is signed" };

type Row = { subject: string; subject_type: string; label: string; blinded: boolean; batches: { id: string }[] };
type DeliveryPage = { running: boolean; deliveries: { files: { sha256: string; name: string }[] }[]; subjects: Row[] };
type Value = { id: string; verbatim: string | null; value: unknown; labels: Record<string, string>; field: string | null; method: string };
type Card = {
  blinded: boolean; links: { state: string; file_sha256: string; link_fact: string }[];
  checks: { id: string; severity: string; overridden: boolean; code: string; message: string | null }[];
  requirements: { req_id: string; status: string }[]; tables: { values: Value[] }[];
};

/** A project of the made-up Exampleamide with Start done and its data plan derived; its API path. */
async function start(request: APIRequestContext): Promise<{ projectId: string; api: string }> {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 50 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  const api = `/api/v1/projects/${projectId}`;
  expect((await request.post(`${api}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  return { projectId, api };
}

async function data<T>(request: APIRequestContext, path: string, init?: { method: "post" | "put"; data?: unknown }): Promise<T> {
  const answer = init ? await request[init.method](path, { headers: AUTH, data: init.data }) : await request.get(path, { headers: AUTH });
  expect(answer.ok(), `${path}: ${await answer.text()}`).toBeTruthy();
  return (await answer.json()).data as T;
}

/** The client's files uploaded, then read: until the delivery and the client data say nothing is being read. */
async function deliver(request: APIRequestContext, api: string, files: { name: string; path: string }[], count: number) {
  for (const f of files) {
    const up = await request.post(`${api}/client-data`, { headers: AUTH, multipart: {
      files: { name: f.name, mimeType: XLSX, buffer: readFileSync(f.path) } } });
    expect(up.status(), await up.text()).toBe(201);
  }
  await expect.poll(async () => {
    const d = await data<DeliveryPage | null>(request, `${api}/delivery`);
    const c = await data<{ running: boolean } | null>(request, `${api}/client-data`);
    return Boolean(d && !d.running && d.deliveries.flatMap((x) => x.files).length === count && c && !c.running);
  }, { timeout: 300_000, intervals: [2000] }).toBe(true);
}

/** The messy workbook delivered (its layouts signed off earlier), its working note marked as not data with a why that
 *  quotes a number of it (41.7: a decision about the file, listed on every study's card of it), blinding on, and one of
 *  study 230-23's values linked to the product Exampleamide IR tablet: the study dosed it, so the product holds the
 *  study's values and is blinded with it. The study's card path, the product's row and another study of the file (231-24). */
async function workbookWithProduct(request: APIRequestContext, projectId: string, api: string) {
  const dir = mkdtempSync(join(tmpdir(), "blinded-follow-"));
  const printed = execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "delivery.py"),
                                      join(process.env.E2E_DATA_DIR!, "read-root"), projectId, dir], { cwd: REPO }).toString();
  const book = (JSON.parse(printed.trim().split("\n").pop()!) as { files: string[] }).files.find((n) => n.endsWith(".xlsx"))!;
  await deliver(request, api, [{ name: book, path: join(dir, book) }], 1);
  await data(request, `${api}/blinding`, { method: "put", data: BLINDING });
  let page = await data<DeliveryPage>(request, `${api}/delivery`);
  const sha = page.deliveries.flatMap((d) => d.files)[0].sha256;
  await data(request, `${api}/delivery/regions:exclude`, { method: "post", data: {
    file_sha256: sha, regions: [OUTSIDE_NOTE], scope: "outside", why: "a working note: 41.7 is a draft figure, not data" } });
  page = await data<DeliveryPage>(request, `${api}/delivery`);
  const study = page.subjects.find((s) => s.label === "230-23")!, product = page.subjects.find((s) => s.label === "Exampleamide IR tablet")!;
  const other = page.subjects.find((s) => s.label === "231-24")!;
  const card = `${api}/delivery/subjects/study/${study.subject}`;
  const value = (await data<Card>(request, card)).tables.flatMap((t) => t.values).find((v) => v.verbatim === "25.2")!;
  await data(request, `${api}/delivery/values:assign`, { method: "post", data: {
    targets: [value.id.split("#")[0]], product: product.subject, batch: product.batches[0].id, why: "the study dosed this batch" } });
  return { study, product, other, card, productCard: `${api}/delivery/subjects/product/${product.subject}` };
}

/** A study's card made ready to sign through the API, as a reviewer would on it: its facts, links, checks, spot check. */
async function readyToSign(request: APIRequestContext, card: string) {
  for (const [field, value] of Object.entries({ route: "oral", formulation: "ir_tablet", intended_use: "model_building", n: 24 })) {
    await data(request, `${card}:enter`, { method: "post", data: { field, value, why: "from the protocol" } });
  }
  let decided = await data<Card>(request, card);
  for (const link of decided.links.filter((l) => l.state !== "refused")) {
    await data(request, `${card}:link`, { method: "post", data: { file_sha256: link.file_sha256, link_fact: link.link_fact, confirmed: true, why: "the same study" } });
  }
  decided = await data<Card>(request, card);
  for (const check of decided.checks.filter((c) => c.severity === "fail" && !c.overridden)) {
    if (check.code !== "REQUIRED_ITEM_UNDISPOSED") {
      await data(request, `${card}:override`, { method: "post", data: { check_id: check.id, why: "read against the source: as written" } });
      continue;
    }
    for (const item of decided.requirements.filter((r) => r.status === "missing" && check.message?.includes(r.req_id))) {
      await data(request, `${card}:dispose`, { method: "post", data: { req_id: item.req_id, disposition: "ask_client", why: "asked" } });
    }
  }
  const draw = await data<{ draw: { id: string }; wanted: string[] }>(request, `${card}/spot-check:draw`, { method: "post" });
  await data(request, `${card}/spot-check`, { method: "post", data: { draw_id: draw.draw.id, ticks: draw.wanted.map((v) => ({ value_id: v, ok: true })) } });
}

/** The study's card (open) signed in its dialog, then Done. */
async function sign(page: Page, card: Locator, subject: string) {
  await card.getByTestId(`delivery-confirm-${subject}`).click();
  const dialog = page.getByTestId("delivery-confirm-dialog");
  await dialog.getByTestId("delivery-confirm-sign").click();
  await expect(dialog.getByTestId("delivery-signed")).toBeVisible({ timeout: 60_000 });
  await dialog.getByTestId("delivery-confirm-done").click();
  await expect(dialog).toHaveCount(0);
}

/** The text of a study's "Decisions made on this study", the delivery's decisions about its files unfolded. */
async function decisionsText(card: Locator, subject: string): Promise<string> {
  const section = card.getByTestId(`delivery-decisions-${subject}`);
  await expect(section).toBeVisible();
  const fold = section.getByTestId(`delivery-decisions-others-${subject}`);
  if (await fold.count() && (await fold.getAttribute("open")) === null) await fold.locator("summary").click();
  return section.innerText();
}

/** A subject's card in its area, opened. */
async function openCard(page: Page, subject: string): Promise<Locator> {
  const toggle = page.getByTestId(`delivery-subject-open-${subject}`);
  await expect(toggle).toBeVisible({ timeout: 30_000 });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  const card = page.getByTestId(`delivery-card-${subject}`);
  await expect(card).toBeVisible();
  return card;
}

/** The product's card shows the blinded study's values (its table opened where it is folded) and offers its spot
 *  check; or, blinded, withholds them, says so and offers neither the spot check nor the values. */
async function expectProduct(card: Locator, subject: string, blinded: boolean) {
  // the card as the page reads it now (blinded: read again since), then the table of the study's values opened
  if (blinded) await expect(card.getByTestId(`delivery-blinded-${subject}`)).toBeVisible();
  const table = card.getByRole("button", { name: /^Individual PK table: show the \d+ values/ });
  if ((await table.getAttribute("aria-expanded", { timeout: 15_000 })) !== "true") await table.click({ timeout: 15_000 });
  if (blinded) {
    await expect(card.locator(".delivery-withheld-cell").first()).toBeVisible();
    await expect(card).not.toContainText("25.2");
    await expect(card.getByRole("button", { name: "Start the spot check" })).toHaveCount(0);
    // round 6: no "Confirm and sign…" the API refuses (409 BLINDED); where it was, the wait and why
    await expect(card.getByTestId(`delivery-confirm-${subject}`)).toHaveCount(0);
    // the why ("it holds the values of study 230-23, which is blinded") is said once, on the card's head
    await expect(card.getByTestId(`delivery-sign-waits-${subject}`)).toHaveText("Signing waits until the plan is signed.");
  } else {
    await expect(card.getByTestId(`delivery-blinded-${subject}`)).toHaveCount(0);
    await expect(card).toContainText("25.2");
  }
}

test("a study signed on the delivery that the split blinds when it lands: its product's card and another study's card of its file follow in the same visit, each read once", async ({ page, request }) => {
  const { projectId, api } = await start(request);
  // the literature's studies first, so the split proposes roles before a plan (S5 for some)
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "blind_split.py"), join(process.env.E2E_DATA_DIR!, "read-root"), projectId], { cwd: REPO });
  const { study, product, other, card, productCard } = await workbookWithProduct(request, projectId, api);
  // 230-23 made ready to sign through the API, as a reviewer would on its card
  await readyToSign(request, card);
  expect((await data<Card>(request, productCard)).blinded).toBe(false);
  type Decision = { kind: string; why: string };
  const otherCard = `${api}/delivery/subjects/study/${other.subject}`;
  const whys = async () => (await data<{ decisions: Decision[] }>(request, otherCard)).decisions.filter((d) => d.kind === "not_data").map((d) => d.why);
  expect(await whys()).toEqual(["a working note: 41.7 is a draft figure, not data"]);

  // the product's card read first in this visit: it shows the study's values
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=formulations`);
  await expectProduct(await openCard(page, product.subject), product.subject, false);
  // 231-24, a study of the same workbook, not blinded: its card lists the decision about the file, its why as written
  await page.getByTestId("tab-studies").click();
  const otherOpen = await openCard(page, other.subject);
  expect(await decisionsText(otherOpen, other.subject)).toContain("41.7");
  await page.getByTestId(`delivery-subject-open-${other.subject}`).click();       // closed again
  // 230-23 signed on its card, then Done; what the page reads from then on is counted
  const prefix = `/api/v1/projects/${projectId}/`;
  const reads: string[] = [];
  page.on("request", (r) => {
    const path = new URL(r.url()).pathname;
    if (r.method() === "GET" && path.startsWith(prefix)) reads.push(path.slice(prefix.length));
  });
  await sign(page, await openCard(page, study.subject), study.subject);
  // the landing put 230-23 in the catalog and the split proposes it for S5: the API blinds it and the product, and masks
  // the why of a decision about its file on every card of it, 231-24's too (the file now holds a blinded study's values)
  await expect.poll(async () => (await data<Card>(request, productCard)).blinded).toBe(true);
  expect(await whys()).toEqual(["a working note: ••.• is a draft figure, not data"]);
  expect((await data<Card>(request, otherCard)).blinded).toBe(false);
  // in the same visit, 231-24's card shows the why masked, as the API answers it (round 5 kept "41.7" until a new visit)
  const otherAfter = await openCard(page, other.subject);
  await expect.poll(async () => decisionsText(otherAfter, other.subject), { timeout: 15_000 }).toContain("••.•");
  expect(await decisionsText(otherAfter, other.subject)).not.toContain("41.7");
  await otherAfter.getByTestId(`delivery-decisions-${other.subject}`).screenshot({ path: test.info().outputPath("1-other-study-why-masked.png") });
  // and the product's card says so, withholds the study's values, offers no spot check and no signature
  await page.getByTestId("tab-formulations").click();
  const blinded = await openCard(page, product.subject);
  await expectProduct(blinded, product.subject, true);
  await page.screenshot({ path: test.info().outputPath("1-product-blinded-same-visit.png"), fullPage: true });
  // one rule decided what the change of the blinding reads: each route once, though the delivery's rows and the inputs'
  // blinded studies both show it (round 5 read the client data, the sheet form, the documents, the evidence and the
  // delivery twice)
  const count = (path: string) => reads.filter((r) => r === path).length;
  // the reading tray too (round 7: its figure suggestions are withheld by file), which every area reads
  for (const path of ["delivery", "inputs", "reading-queue"]) expect(count(path), `${path}: ${reads.join(", ")}`).toBe(1);
  for (const path of ["client-data", "client-review", "documents", "evidence"]) expect(count(path), `${path}: ${reads.join(", ")}`).toBeLessThanOrEqual(1);
  const cards = reads.filter((r) => r.startsWith("delivery/subjects/") && !r.endsWith("/spot-check"));
  expect(cards.length, cards.join(", ")).toBe(new Set(cards).size);
  expect(cards).toContain(`delivery/subjects/study/${other.subject}`);
  // as a new visit shows it
  const again = await page.context().newPage();
  await again.goto(`/projects/${projectId}/inputs?tab=formulations`);
  await expectProduct(await openCard(again, product.subject), product.subject, true);
  await again.close();
});

test("a card decision that blinds a study already in the model: the Studies list, its dataset and its product follow in the same visit", async ({ page, request }) => {
  const { projectId, api } = await start(request);
  // no literature here: the split proposes no S5, so 230-23 lands unblinded
  const { study, product, card, productCard } = await workbookWithProduct(request, projectId, api);
  await readyToSign(request, card);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  const studyCard = await openCard(page, study.subject);
  await sign(page, studyCard, study.subject);
  type Dataset = { id: string; study: { study_id: string }; blinded?: boolean };
  const datasets = async () => (await data<{ datasets: Dataset[] }>(request, `${api}/evidence`)).datasets.filter((d) => d.study.study_id === "230-23");
  await expect.poll(async () => (await datasets()).length).toBeGreaterThan(0);
  const [landed] = await datasets();
  expect(landed.blinded ?? false).toBe(false);
  // in the model, its row on the Studies list says nothing is blinded, and its dataset's points can be shown
  const row = page.getByTestId("study-230-23");
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(row.locator(".chip", { hasText: "blinded" })).toHaveCount(0);
  const line = page.getByTestId(`dataset-${landed.id}`);
  await expect(line.getByTestId(`dataset-blinded-${landed.id}`)).toHaveCount(0);

  // its purpose corrected on its card, external validation: the delivery blinds it, and the product that holds its values
  const purpose = (await data<Card>(request, card)).tables.flatMap((t) => t.values).find((v) => v.field === "intended_use" && v.method === "person")!;
  await studyCard.getByTestId(`delivery-correct-${purpose.id}`).click();
  await studyCard.getByTestId(`correct-${purpose.id}-value`).fill("external_validation");
  await studyCard.getByTestId(`correct-${purpose.id}-why`).fill("the protocol keeps it for external validation");
  await studyCard.getByTestId(`correct-${purpose.id}-submit`).click();
  await expect(studyCard.getByTestId(`delivery-blinded-${study.subject}`)).toBeVisible({ timeout: 30_000 });
  expect((await data<Card>(request, productCard)).blinded).toBe(true);
  expect((await datasets())[0].blinded).toBe(true);
  // in the same visit: its row on the Studies list says blinded, and its dataset's points are withheld, with why
  await expect(row.locator(".chip", { hasText: "blinded" })).toBeVisible();
  await expect(line.getByTestId(`dataset-blinded-${landed.id}`)).toBeVisible();
  await expect(line.getByRole("button", { name: /^Show the points/ })).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("4-landed-study-blinded-same-visit.png"), fullPage: true });
  // and its product's card is blinded, with no signature offered
  await page.getByTestId("tab-formulations").click();
  await expectProduct(await openCard(page, product.subject), product.subject, true);
});

test("a study entered for external validation on its card: the product that holds its values is blinded in the same visit", async ({ page, request }) => {
  const { projectId, api } = await start(request);
  const { study, product, productCard } = await workbookWithProduct(request, projectId, api);
  await page.setViewportSize({ width: 1440, height: 900 });
  // round 7: the page's first read of the delivery fails at the web server's proxy, as it did once under load (a bare 500,
  // "socket hang up": the API had closed the kept-alive connection the proxy reused). With no retries, no card came; a
  // read the proxy could not complete is now sent once more
  let failed = 0;
  await page.route((url) => url.pathname === `${api}/delivery`, async (route) => {
    if (route.request().method() === "GET" && failed++ === 0) {
      await route.fulfill({ status: 500, contentType: "text/plain", body: "Internal Server Error" });
      return;
    }
    await route.continue();
  });
  await page.goto(`/projects/${projectId}/inputs?tab=formulations`);
  await expectProduct(await openCard(page, product.subject), product.subject, false);
  expect(failed).toBeGreaterThan(1);
  await page.unroute((url) => url.pathname === `${api}/delivery`);
  // what 230-23 is for, entered on its card's facts form: external validation
  await page.getByTestId("tab-studies").click();
  const card = await openCard(page, study.subject);
  const facts = card.getByTestId(`delivery-facts-form-${study.subject}`);
  await facts.locator(".facts-row", { hasText: "Purpose of the study" }).locator('[data-testid$="-value"]').selectOption("external_validation");
  await facts.getByTestId(`delivery-facts-form-${study.subject}-why`).fill("the protocol keeps it for external validation");
  await facts.getByTestId(`delivery-facts-form-${study.subject}-submit`).click();
  await expect(card.getByTestId(`delivery-blinded-${study.subject}`)).toBeVisible();
  expect((await data<Card>(request, productCard)).blinded).toBe(true);
  // in the same visit, the product's card is blinded with it
  await page.getByTestId("tab-formulations").click();
  await expectProduct(await openCard(page, product.subject), product.subject, true);
  await page.screenshot({ path: test.info().outputPath("2-product-blinded-by-purpose.png"), fullPage: true });
});

test("a sheet's study the split blinds once the sheet form confirms it: the sheet is withheld in the same visit", async ({ page, request }) => {
  const { projectId, api } = await start(request);
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "blind_split.py"), join(process.env.E2E_DATA_DIR!, "read-root"), projectId], { cwd: REPO });
  const dir = mkdtempSync(join(tmpdir(), "blinded-sheet-split-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "reading_eval_workbook.py"), dir, "published-mean"], { cwd: REPO });
  const name = "Smith2015_Table2.xlsx";
  await deliver(request, api, [{ name, path: join(dir, name) }], 1);
  await data(request, `${api}/blinding`, { method: "put", data: BLINDING });
  type Files = { files: { file: string; blinded_sheets: string[] }[] };
  const sheetsWithheld = async () => (await data<Files>(request, `${api}/client-data`)).files.find((f) => f.file === name)!.blinded_sheets;

  // the sheet read with the sheet form and saved in this visit: its study, Smith2015, waits on its card to be confirmed
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=files`);
  await openFile(page, name);
  const sheets = page.getByTestId(`client-file-${name}`);
  await sheets.getByTestId("sheet-Mean PK").getByRole("button", { name: "Read this sheet" }).click();
  const reader = page.getByTestId("reader-Mean PK");
  // 25 mg, between the literature's oral doses (10 to 100 mg): the split trains oral absorption at the lowest and the
  // highest dose, and holds the others for external validation (S5)
  await reader.getByLabel("dose", { exact: true }).fill("25");
  await reader.getByLabel("formulation", { exact: true }).selectOption("solution");
  await reader.getByLabel("food", { exact: true }).selectOption("fasted");
  await reader.getByLabel("subjects", { exact: true }).fill("12");
  await reader.getByLabel("study purpose", { exact: true }).selectOption("model_building");
  await reader.getByRole("button", { name: "Check what will be read" }).click();
  await expect(reader.getByTestId("read-result")).toContainText("ready to save");
  await reader.getByRole("button", { name: "Save these data" }).click();
  await expect(sheets.getByTestId("sheet-Mean PK")).toContainText("read ✓");
  await expect(page.getByTestId("sheet-blinded-Mean PK")).toHaveCount(0);
  expect(await sheetsWithheld()).toEqual([]);
  // confirmed with the sheet form: its dataset joins the catalog, and the split, before a plan, proposes it for S5
  await page.getByTestId("tab-studies").click();
  const study = page.getByTestId("group-study:Smith2015");
  await study.getByTestId("confirm-study:Smith2015").click();
  await expect(page.getByTestId("card-loaded-study:Smith2015")).toBeVisible();
  await expect.poll(sheetsWithheld).toEqual(["Mean PK"]);
  // in the same visit, Client files withholds the sheet as a new visit does: blinded until the plan is signed
  await page.getByTestId("tab-files").click();
  await openFile(page, name);
  await expect(page.getByTestId("sheet-blinded-Mean PK")).toHaveText("blinded until the plan is signed");
  await page.screenshot({ path: test.info().outputPath("3-sheet-withheld-same-visit.png"), fullPage: true });
});
