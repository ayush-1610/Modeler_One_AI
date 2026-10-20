// The caveats a regulator reads must stay on screen through any restyle: "toContainText" passes on text that is hidden,
// clipped or the same colour as its background, so these checks ask for a visible, unclipped box, in both themes.
// Add a caveat here when a new screen carries one ("provisional (SME)", "UNVERIFIED" on Review & sign, "TEST ONLY").
import { expect, test, type Locator, type Page } from "@playwright/test";

const PROPOSAL = "# Technical proposal TP-E2E-9: PBPK model of exampleamide\nObjective: exposure after a single oral dose.";

async function onScreen(target: Locator) {
  await expect(target).toBeVisible();
  const box = await target.boundingBox();
  expect(box && box.width > 0 && box.height > 0).toBe(true);
  // not cut off by its own box (overflow hidden / ellipsis would clip the words)
  const clipped = await target.evaluate((el) => el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== "visible");
  expect(clipped).toBe(false);
  // legible: the text colour against the backgrounds under it, whatever CSS colour syntax the theme uses. Below 3:1 it is
  // effectively hidden (transparent, or its own background colour); the WCAG 4.5:1 target is the foundation PRs' job.
  const ratio = await target.evaluate((el) => {
    const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true })!;
    const rgba = (css: string): number[] => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "#000"; ctx.fillStyle = css; ctx.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    const over = (top: number[], under: number[]) => [0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3])).concat(1);
    const layers: number[][] = [];
    for (let n: Element | null = el; n; n = n.parentElement) layers.unshift(rgba(getComputedStyle(n).backgroundColor));
    const bg = layers.reduce((under, top) => over(top, under), [255, 255, 255, 1]);
    const text = rgba(getComputedStyle(el).color);
    const fg = over([text[0], text[1], text[2], text[3] * Number(getComputedStyle(el).opacity)], bg);
    const lum = (c: number[]) => {
      const f = (v: number) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
      return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
    };
    const [hi, lo] = [lum(fg), lum(bg)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  });
  expect(ratio).toBeGreaterThanOrEqual(3);
}

async function theme(page: Page, mode: "light" | "dark") {
  await page.emulateMedia({ colorScheme: mode });
  await page.evaluate((m) => document.documentElement.setAttribute("data-theme", m), mode);
}

test("Start: a scope the builder cannot model says 'not supported yet', visibly, in light and dark", async ({ page }) => {
  await page.goto("/projects/start");
  await page.getByTestId("drug-name").fill("Exampleamide");
  await page.getByTestId("proposal-files").setInputFiles({ name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) });
  await page.getByTestId("start-project").click();
  await page.waitForURL(/\/projects\/[^/]+\/start$/);

  await page.getByTestId("pick-modality-small_molecule").click();
  await page.getByTestId("pick-pbpk_model-full").click();
  await page.getByTestId("pick-site_of_action-systemic").click();
  await page.getByTestId("pick-formulation_types").getByLabel("liposome").check();
  await expect(page.getByTestId("gate-formulation_types-state")).toHaveText("not supported yet");

  for (const mode of ["light", "dark"] as const) {
    await theme(page, mode);
    await onScreen(page.getByTestId("gate-formulation_types-state"));
    await onScreen(page.getByTestId("gate-formulation_types-message"));
    await onScreen(page.getByTestId("start-waiting"));
    await page.screenshot({ path: test.info().outputPath(`start-gate-${mode}.png`), fullPage: true });
  }
});
