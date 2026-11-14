// The Inputs frame (plan docs/plans/2026-11-14-inputs-task-first.md, slice 1): a compact head with "Add data", a step bar
// that scrolls away, a status line with the page's one "Next", and one bar of areas that sits high on every area and
// stays in view; the client's files and the Delivery review in their own area; nothing faded in as it scrolls; and on a
// phone one row of areas that scrolls sideways with the current area in view, and no sideways page scroll, also on a
// study's and a product's card. Software test data, never a model.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

const AREAS = ["todo", "compound", "formulations", "studies", "individuals", "settings", "files"];

async function project(request: Parameters<typeof finishStart>[0]) {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Framamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 10 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const md = await request.post(`/api/v1/projects/${projectId}/datasets`, { headers: AUTH, data: {
    study: { study_id: "po-frame", n: 12, route: "oral", dose_mg: 10, formulation: "solution", food_state: "fasted", n_timepoints: 4 },
    time_unit: "h", unit: "ng/ml", origin: "LITERATURE", source: { title: "Frame study" },
    series: [{ times: [0.5, 1, 2, 4], values: [10, 20, 15, 5], n: 12 }] } });
  expect(md.status(), await md.text()).toBe(201);
  return projectId;
}

/** The page scrolls sideways: its content is wider than the window. */
const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
/** The page has stopped scrolling (a smooth scroll to a tool it opened has ended): the menu closes on a scroll. */
async function settled(page: Page) {
  await expect.poll(async () => {
    const at = await page.evaluate(() => window.scrollY);
    await page.waitForTimeout(150);
    return at === await page.evaluate(() => window.scrollY);
  }).toBe(true);
}
/** The selected area's tab lies inside the area bar's row, not cut off or scrolled out of it. */
const selectedInView = (page: Page) => page.getByRole("tablist", { name: "Input areas" }).evaluate((row) => {
  const tab = row.querySelector('[aria-selected="true"]')!.getBoundingClientRect(), box = row.getBoundingClientRect();
  return tab.left >= box.left - 1 && tab.right <= box.right + 1;
});

test("the area bar is high on every area, stays in view, and the page opens on To do", async ({ page, request }) => {
  const projectId = await project(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs`);
  const bar = page.getByTestId("area-bar");
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "true");     // something is missing to run
  await expect(page.getByTestId("still-missing")).toBeVisible();
  await expect(page.locator(".hero-lede")).toHaveText("Fill in what the model needs and confirm the client's data.");
  // the step bar scrolls away with the page; the area bar is what stays
  await expect(page.locator(".stepper-wrap")).toHaveCSS("position", "static");
  await expect(bar).toHaveCSS("position", "sticky");
  // the status line: what is missing, to decide and to confirm, and the page's one primary button
  await expect(page.getByTestId("inputs-status")).toBeVisible();
  await expect(page.getByTestId("status-missing")).toBeVisible();
  await expect(page.getByTestId("inputs-next")).toHaveText(/^Next: /);
  await expect(page.locator("main .btn.primary:visible")).toHaveCount(1);

  for (const area of AREAS) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.getByTestId(`tab-${area}`).click();
    await expect(page.getByTestId(`tab-${area}`)).toHaveAttribute("aria-selected", "true");
    const box = (await bar.boundingBox())!;
    expect(box.y, `the area bar on ${area}`).toBeLessThanOrEqual(340);      // the slim head (slice 2; slice 1 had 480)
    // the Delivery review is in Client files only
    if (area !== "files") await expect(page.getByTestId("delivery-section")).toHaveCount(0);
  }

  // scrolled down a long area, the bar is still at the top of the window, and nothing below the fold is faded out
  await page.getByTestId("tab-compound").click();
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(async () => (await bar.boundingBox())!.y).toBeLessThanOrEqual(1);
  const faded = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("[data-no-reveal] section, [data-no-reveal] .card")]
    .filter((el) => el.style.opacity === "0").length);
  expect(faded).toBe(0);
  // the head's "Add data": the client's files by area and the other sources, in one menu that closes on Escape
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByTestId("inputs-add-data").click();
  await expect(page.getByTestId("add-files-studies")).toBeVisible();
  await expect(page.getByTestId("add-template")).toBeVisible();
  await expect(page.getByTestId("ask-literature")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("1-add-data.png") });
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("ask-literature")).toBeHidden();
  // the menu's observed-data tools open on Clinical studies: a table typed in, a figure digitized
  await page.getByTestId("inputs-add-data").click();
  await page.getByTestId("add-typed-table").click();
  await expect(page.getByTestId("tab-studies")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("typed-table")).toBeVisible();
  await settled(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByTestId("inputs-add-data").click();
  await page.getByTestId("add-digitize").click();
  await expect(page.getByTestId("digitizer-card")).toBeVisible();
  // "To confirm" is on the status line: it opens To do narrowed to its word, in the URL; pressed again, every item
  await settled(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByTestId("tab-compound").click();
  await expect(page).toHaveURL(/\?tab=compound$/);
  await page.getByTestId("to-confirm").click();
  await expect(page.getByTestId("to-confirm")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("todo-filter-to_confirm")).toHaveAttribute("aria-pressed", "true");
  await expect(page).toHaveURL(/\?tab=todo&status=to_confirm$/);
  await page.getByTestId("to-confirm").click();
  await expect(page.getByTestId("todo-filter-all")).toHaveAttribute("aria-pressed", "true");
  // "Only what needs me" is in the URL too, and a link to it opens the page as it was
  await page.getByTestId("todo-only").check();
  await expect(page).toHaveURL(/\?tab=todo&only=1$/);
  await page.reload();
  await expect(page.getByTestId("todo-only")).toBeChecked();
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "true");
  await page.getByTestId("todo-only").uncheck();
  // "Next" opens the first open item where it is settled
  await page.getByTestId("tab-todo").click();
  await page.getByTestId("inputs-next").click();
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "false");
  await page.screenshot({ path: test.info().outputPath("2-frame.png") });
});

test("on a phone the areas are one row that scrolls sideways, and the page does not", async ({ page, request }) => {
  const projectId = await project(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  const bar = page.getByTestId("area-bar");
  await expect(page.getByTestId("tab-studies")).toHaveAttribute("aria-selected", "true");    // an explicit ?tab wins …
  await expect.poll(() => selectedInView(page), "the linked area's tab in view").toBe(true);  // … and is shown in the row
  const tabs = bar.getByRole("tablist");
  const row = await tabs.evaluate((el) => ({ height: el.getBoundingClientRect().height, scrolls: el.scrollWidth > el.clientWidth }));
  expect(row.height, "one row of areas").toBeLessThan(60);
  expect(row.scrolls, "the row scrolls sideways").toBe(true);
  for (const area of AREAS) {
    await page.getByTestId(`tab-${area}`).click();
    await expect(page.getByTestId(`tab-${area}`)).toHaveAttribute("aria-selected", "true");
    expect(await sideways(page), `no sideways page scroll on ${area}`).toBe(false);
  }
  // an item of To do opens its area, and the row brings that area's tab into view
  await page.getByTestId("tab-todo").click();
  await page.locator("[data-testid^='missing-']").last().click();
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "false");
  await expect.poll(() => selectedInView(page), "the opened area's tab in view").toBe(true);
  await page.screenshot({ path: test.info().outputPath("3-phone.png") });
});

test("on a phone a study's and a product's card fit the window: their charts, tables and forms stay inside them", async ({ page, request }) => {
  const projectId = await project(request);
  const dir = mkdtempSync(join(tmpdir(), "frame-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "client_workbooks.py"), dir], { cwd: REPO });
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "er_be_workbooks.py"), dir], { cwd: REPO });
  // a filled client-data template: a study with code's NCA table, and two products with their dissolution
  const up = await request.post(`/api/v1/projects/${projectId}/client-data`, { headers: AUTH, multipart: {
    files: { name: "client-template-filled.xlsx", mimeType: XLSX, buffer: readFileSync(join(dir, "client-template-filled.xlsx")) } } });
  expect(up.status(), await up.text()).toBe(201);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  // and a BE arm read on arrival, whose card asks for what the sheet does not say
  await page.getByTestId("client-upload-studies").setInputFiles(join(dir, "230-23 Fasting Reference.xlsx"));
  await expect(page.getByTestId("inputs-notice")).toContainText("1 file stored.");
  await expect(page.getByTestId("group-study:230-23-REF").getByTestId("need-n")).toBeVisible();
  const study = page.locator("[data-testid^='group-study:']", { has: page.getByTestId("dataset-stats") }).first();
  await expect(study.getByTestId("dataset-stats")).toBeAttached();
  expect(await sideways(page), "no sideways page scroll on the studies' cards").toBe(false);
  // a card's chips keep their colour: "To confirm" on a card is not the status line's plain button chip
  const chip = study.locator(".confirm-title .chip").first();
  await expect(chip).toContainText("To confirm");
  expect(await chip.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe(
    await study.evaluate((el) => getComputedStyle(el).backgroundColor));
  await page.getByTestId("tab-formulations").click();
  await expect(page.locator("[data-testid^='group-product:']").first()).toBeVisible();
  expect(await sideways(page), "no sideways page scroll on the products' cards").toBe(false);
  await page.screenshot({ path: test.info().outputPath("4-phone-cards.png"), fullPage: true });
});
