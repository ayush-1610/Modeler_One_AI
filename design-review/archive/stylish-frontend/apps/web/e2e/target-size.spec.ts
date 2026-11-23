// Target size (WCAG 2.2 SC 2.5.8, the 2026-11-11 audit, item 7): the small controls on Start are at least 24 x 24 CSS px
// to the pointer. The visual size can stay small; the hit area is the element's box or its invisible ::after
// (app/styles/targets.css), whichever is larger, so both are measured.
import { expect, test, type Locator } from "@playwright/test";

const PROPOSAL = [
  "# Technical proposal TP-E2E-T: PBPK model of exampleamide",
  "Objective: predict exposure after a single oral dose of 10 mg in healthy adults, fasted and fed.",
].join("\n");

/** The pointer target of one control: its own box, or its ::after hit area when that is larger. */
async function target(control: Locator): Promise<{ width: number; height: number }> {
  return control.evaluate((el) => {
    const box = el.getBoundingClientRect();
    const after = getComputedStyle(el, "::after");
    const shown = after.content !== "none" && after.content !== "normal" && after.position === "absolute";
    const w = shown ? parseFloat(after.width) || 0 : 0;
    const h = shown ? parseFloat(after.height) || 0 : 0;
    return { width: Math.max(box.width, w), height: Math.max(box.height, h) };
  });
}

async function atLeast24(control: Locator, name: string) {
  await expect(control, name).toBeVisible();
  const t = await target(control);
  expect(t.width, `${name} width`).toBeGreaterThanOrEqual(24);
  expect(t.height, `${name} height`).toBeGreaterThanOrEqual(24);
}

test("Start: Change, citation, link buttons and the API dot are at least 24 x 24 px to the pointer", async ({ page }) => {
  await page.goto("/projects/start");
  await page.getByTestId("drug-name").fill("Exampleamide");
  await page.getByTestId("proposal-files").setInputFiles({ name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) });
  // a picked file's Remove is a link button
  await atLeast24(page.locator(".picked .link-btn").first(), "link-btn (Remove)");
  await atLeast24(page.getByTestId("nav-conn"), "nav-conn");

  await page.getByTestId("start-project").click();
  await page.waitForURL(/\/projects\/[^/]+\/start$/);
  // the objective arrives drafted with its quote: the row has a citation button and a Change control
  const row = page.getByTestId("start-field-qoi.text");
  await expect(row).toContainText("Objective: predict exposure");
  await atLeast24(page.getByTestId("edit-qoi.text"), "sb-change");
  const sbChange = await page.getByTestId("edit-qoi.text").boundingBox();
  expect(sbChange?.height ?? 0, "sb-change is 32px tall").toBeGreaterThanOrEqual(32);
  await atLeast24(row.locator(".cite").first(), "cite");
  await atLeast24(page.getByTestId("nav-conn"), "nav-conn");

  // the larger hit area did not take the click: Change still opens its editor
  await page.getByTestId("edit-qoi.text").click();
  await expect(page.getByTestId("input-qoi.text")).toBeVisible();
});
