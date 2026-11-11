// A phone (390 × 844) is a supported screen (the 2026-11-11 audit 2, item 8): nothing makes the page wider than the
// screen, the step bar held in view is one row about 44 px tall, an in-page jump lands below it, and a wide table keeps
// its identifying column and its action in view.
import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

const PHONE = { width: 390, height: 844 };

async function project(request: import("@playwright/test").APIRequestContext, name: string) {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: name, extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nAn IR tablet.") } } });
  expect(started.ok(), await started.text()).toBeTruthy();
  return (await started.json()).data.project_id as string;
}

test("the Library is no wider than a phone, and Withdraw is under the document's name, on screen", async ({ page, request }) => {
  const projectId = await project(request, "Phonamide");
  await page.setViewportSize(PHONE);
  await page.goto(`/projects/${projectId}/library`);
  await expect(page.getByTestId("library-row-proposal.md")).toBeVisible();
  // 603 px before: a header's sr-only text escaped the table's scroll box
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(PHONE.width);
  const withdraw = await page.getByTestId("library-withdraw-proposal.md").boundingBox();
  expect(withdraw).not.toBeNull();
  expect(withdraw!.x + withdraw!.width).toBeLessThanOrEqual(PHONE.width);         // x = 603–685 before
  // the name column stays put while the table scrolls sideways
  const scroller = page.locator("[data-testid=library] .table-scroll");
  await scroller.evaluate((el) => { el.scrollLeft = el.scrollWidth; });
  const name = await page.getByTestId("library-open-proposal.md").boundingBox();
  expect(name!.x).toBeGreaterThanOrEqual(0);
  expect(name!.x + name!.width).toBeLessThanOrEqual(PHONE.width);
  await page.screenshot({ path: test.info().outputPath("library-390.png"), fullPage: true });
});

test("on a phone the step bar is one row about 44 px tall, and an in-page jump lands below it", async ({ page, request }) => {
  const projectId = await project(request, "Steppamide");
  await page.setViewportSize(PHONE);
  for (const path of [`/projects/${projectId}/start`, `/projects/${projectId}/history`]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const bar = page.getByTestId("stepper");
    await expect(bar).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(PHONE.width);
    const box = (await bar.boundingBox())!;
    expect(box.height).toBeLessThanOrEqual(48);                                    // 92–121 px as a 2×2 grid before
    // scrolled down, the bar is held under the top bar; the page's jump margin clears both
    // (a new project's page can be short: a spacer after the bar, in the box it is held in, gives it room to scroll)
    await bar.evaluate((el) => {
      const spacer = document.createElement("div");
      spacer.style.height = "2000px";
      el.parentElement!.parentElement!.append(spacer);
      window.scrollTo(0, document.documentElement.scrollHeight);
    });
    const held = await bar.evaluate((el) => ({
      bottom: el.getBoundingClientRect().bottom,
      pad: parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop),
    }));
    expect(held.bottom).toBeLessThanOrEqual(72 + 48);                              // 193 px before
    expect(held.pad).toBeGreaterThanOrEqual(held.bottom);                          // 96 px before
  }
  // the current step says its name; the others are their numbered dots, still named for a screen reader
  await page.goto(`/projects/${projectId}/start`);
  await expect(page.getByTestId("step-start").locator(".step-label")).toBeVisible();
  await expect(page.getByTestId("step-inputs")).toContainText("Inputs");          // in the DOM, clipped, not removed
  const other = await page.getByTestId("step-inputs").locator(".step-text").boundingBox();
  expect(other!.width).toBeLessThanOrEqual(1);
  await page.screenshot({ path: test.info().outputPath("start-390.png") });
});
