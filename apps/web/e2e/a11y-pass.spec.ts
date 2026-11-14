// The accessibility and wording pass (2026-11-11 audit 2, item 10): small text never in --ink-faint, motion that stops
// (once, and not at all under reduced motion), an outline with no h1 → h3 jump on Inputs, a phone menu that Escape
// closes, and one name for a step on every page. Software test data entered through the API, never a model.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

const AUTH = { Authorization: "Bearer dev" };
const APP = join(__dirname, "..", "app");

test("no text rule is coloured --ink-faint (2.99:1 on --bg): it is for rules, icons and graph edges only", () => {
  const css = [join(APP, "globals.css"), ...readdirSync(join(APP, "styles")).filter((f) => f.endsWith(".css")).map((f) => join(APP, "styles", f))];
  // an arrow glyph between flow columns is an icon, not text (globals.css: "--ink-faint is for non-text only")
  const ICONS = [".flow-arrow"];
  const offenders = css.flatMap((file) => readFileSync(file, "utf8").split("\n").map((line, i) => ({ file, line, n: i + 1 })))
    .filter(({ line }) => /(^|[;{\s])color:\s*var\(--ink-faint\)/.test(line) && !ICONS.some((s) => line.trimStart().startsWith(s)))
    .map(({ file, n, line }) => `${file.slice(APP.length + 1)}:${n}: ${line.trim()}`);
  expect(offenders, "small text uses --ink-quiet (4.66:1 on --bg)").toEqual([]);
});

test("a form control's edge is 3:1 on the card and on the page (WCAG 1.4.11)", () => {
  // the base rule for every bare input, select and textarea draws its edge in --control-border (audit 2 review: it was
  // rgba(0,0,0,0.1), about 1.25:1, while the token's comment said 3:1)
  const css = readFileSync(join(APP, "globals.css"), "utf8");
  const token = (name: string) => css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`))?.[1];
  const luminance = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a: string, b: string) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  const edge = token("control-border");
  expect(edge, "--control-border is an opaque #rrggbb colour").toBeTruthy();
  for (const ground of ["surface", "raised", "bg"]) {
    expect(ratio(edge!, token(ground)!), `--control-border on --${ground}`).toBeGreaterThanOrEqual(3);
  }
});

test("a search field keeps the 2 px focus ring", async ({ page }) => {
  // .dash-tools / .library-tools / .table-tools search fields set outline: none on :focus, above the global
  // :focus-visible ring, so only a 1 px border change was left (audit 2 review)
  await page.goto("/");
  const search = page.getByTestId("dash-search");
  await expect(search).toBeVisible();
  // polled: on a cold first load the page can hydrate (and re-render the field) between the focus and the read
  await expect.poll(async () => {
    await search.focus();
    return search.evaluate((el) => {
      const s = getComputedStyle(el);
      return { style: s.outlineStyle, width: s.outlineWidth };
    });
  }).toEqual({ style: "solid", width: "2px" });
});

test("the hero curve draws once, and not at all under reduced motion", async ({ page }) => {
  await page.goto("/");
  const curve = page.locator(".hero-art .curve").first();
  await expect(curve).toBeAttached();
  expect(await curve.evaluate((el) => getComputedStyle(el).animationIterationCount)).toBe("1");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await expect(curve).toBeAttached();
  const reduced = await curve.evaluate((el) => {
    const s = getComputedStyle(el);
    return { name: s.animationName, offset: s.strokeDashoffset };
  });
  // drawn and still: no animation, the curve at its end state (not the opacity-0 first keyframe)
  expect(reduced).toEqual({ name: "none", offset: "0px" });
  // every other animation (the skeleton sweep among them) runs one cycle, never an infinite flicker
  const infinite = await page.evaluate(() => [...document.querySelectorAll("*")].filter((el) =>
    getComputedStyle(el).animationIterationCount === "infinite").length);
  expect(infinite).toBe(0);
});

test("on a phone, Escape closes the menu and gives focus back to its toggle", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const toggle = page.getByTestId("nav-menu");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  // the creation page has one name: "New project", in the menu as on the dashboard
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "New project" })).toHaveCount(1);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Projects" }).focus();
  await page.keyboard.press("Escape");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(toggle).toBeFocused();
});

test("Inputs: the outline has no h1 → h3 jump, and the eyebrow names the step", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "Outlinol", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet.") } },
  });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();

  for (const tab of ["", "?tab=studies", "?tab=individuals"]) {
    await page.goto(`/projects/${projectId}/inputs${tab}`);
    await expect(page.getByTestId("inputs-more")).toBeAttached();
    const skips = await page.evaluate(() => {
      const levels = [...document.querySelectorAll("main h1, main h2, main h3, main h4, main h5, main h6")]
        .map((h) => Number(h.tagName[1]));
      return levels.flatMap((l, i) => (i && l > levels[i - 1] + 1 ? [`h${levels[i - 1]} → h${l}`] : []));
    });
    expect(skips, `inputs${tab}`).toEqual([]);
    await expect(page.locator(".hero-pill").first()).toHaveText("Step 2 of 4 · Inputs");
  }
  // the rail's panel says what the next step needs, in words
  await page.goto(`/projects/${projectId}/inputs`);
  const rail = page.getByTestId("still-missing").or(page.getByTestId("inputs-ready")).or(page.getByTestId("assembling"));
  await expect(rail.first().getByRole("heading", { level: 2 })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Missing for S0");
});
