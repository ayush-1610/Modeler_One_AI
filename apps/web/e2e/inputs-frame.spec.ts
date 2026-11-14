// The Inputs frame (plan docs/plans/2026-11-14-inputs-task-first.md, slice 1): a compact head with "Add data", a step bar
// that scrolls away, and one bar of areas that sits high on every area and stays in view; the client's files and the
// Delivery review in their own area; nothing faded in as it scrolls; and on a phone one row of areas that scrolls
// sideways, with no sideways page scroll. Software test data, never a model.
import { expect, type Page, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

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

  for (const area of AREAS) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.getByTestId(`tab-${area}`).click();
    await expect(page.getByTestId(`tab-${area}`)).toHaveAttribute("aria-selected", "true");
    const box = (await bar.boundingBox())!;
    expect(box.y, `the area bar on ${area}`).toBeLessThanOrEqual(480);
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
  await expect(page.getByTestId("ask-literature")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("1-add-data.png") });
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("ask-literature")).toBeHidden();
  // "To confirm" is at the end of the bar; pressed on To do it opens an area to confirm in
  await page.getByTestId("tab-todo").click();
  await page.getByTestId("to-confirm").click();
  await expect(page.getByTestId("to-confirm")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "false");
  await page.getByTestId("to-confirm").click();
  await page.screenshot({ path: test.info().outputPath("2-frame.png") });
});

test("on a phone the areas are one row that scrolls sideways, and the page does not", async ({ page, request }) => {
  const projectId = await project(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${projectId}/inputs?tab=compound`);
  const bar = page.getByTestId("area-bar");
  await expect(page.getByTestId("tab-compound")).toHaveAttribute("aria-selected", "true");   // an explicit ?tab wins
  const tabs = bar.getByRole("tablist");
  const row = await tabs.evaluate((el) => ({ height: el.getBoundingClientRect().height, scrolls: el.scrollWidth > el.clientWidth }));
  expect(row.height, "one row of areas").toBeLessThan(60);
  expect(row.scrolls, "the row scrolls sideways").toBe(true);
  for (const area of AREAS) {
    await page.getByTestId(`tab-${area}`).click();
    await expect(page.getByTestId(`tab-${area}`)).toHaveAttribute("aria-selected", "true");
    expect(await sideways(page), `no sideways page scroll on ${area}`).toBe(false);
  }
  await page.screenshot({ path: test.info().outputPath("3-phone.png") });
});
