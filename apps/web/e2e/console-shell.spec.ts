// The console shell (docs/plans/2026-11-23-console-redesign-implementation.md, slice 1; design-review/DESIGN_SYSTEM.md
// §4, §7): on every main page, at a desktop and at a phone's width, every visible control has an accessible name, the page
// has one top heading, and nothing scrolls sideways; on a phone the navigation is a menu the top bar opens. The same
// checks the approved prototype passed (design-review/WIREFRAMES.md §6), now on the real app.
import { expect, test, type Page } from "@playwright/test";

import { projectWithInputs } from "./fixtures/inputs";

/** Visible controls with no accessible name: aria-label, aria-labelledby, their text, a title, a placeholder, or a label. */
async function unnamed(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const named = (el: Element) => {
      const by = el.getAttribute("aria-labelledby");
      const text = (el.getAttribute("aria-label") || (by && by.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" "))
        || (el as HTMLElement).innerText || el.getAttribute("title") || el.getAttribute("placeholder")
        || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.textContent) || el.closest("label")?.textContent
        || (el.querySelector("img[alt]") as HTMLImageElement | null)?.alt || "").trim();
      return text.length > 0;
    };
    return Array.from(document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=tab]"))
      .filter((el) => el.checkVisibility({ visibilityProperty: true, opacityProperty: true }) && !el.closest("[aria-hidden=true]"))
      .filter((el) => !named(el))
      .map((el) => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}.${(el.getAttribute("class") || "").split(" ")[0]} ${el.getAttribute("data-testid") ?? ""}`.trim());
  });
}

async function check(page: Page, path: string) {
  await page.goto(path);
  // the page itself, not its loading screen (a route's loading screen streams first: its own head, aria-busy)
  await expect(page.locator('main[aria-busy="true"]')).toHaveCount(0);
  await expect(page.locator("main h1").first()).toBeVisible();
  expect(await page.locator("h1").count(), `${path}: one top heading`).toBe(1);
  expect(await unnamed(page), `${path}: every control named`).toEqual([]);
  // the page's own width, and what sticks out past the window (outside a box that scrolls by itself), named on failure
  const [wide, who] = await page.evaluate(() => [document.documentElement.scrollWidth - window.innerWidth,
    [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1
      && !e.closest(".table-scroll, .tbl-scroll, .dag-scroll, .tabs")).slice(0, 6)
      .map((e) => `${e.tagName.toLowerCase()}.${(e.getAttribute("class") || "").split(" ")[0]}`).join(", ")] as const);
  expect(wide, `${path}: no sideways scroll (${who})`).toBeLessThanOrEqual(1);
}

test("every main page: named controls, one heading, no sideways scroll, at 1440 and 390 px", async ({ page, request }) => {
  const id = await projectWithInputs(request, "Consolamide", [{ study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }]);
  const pages = ["/", "/work", "/projects", "/campaigns", "/help", "/projects/start", `/projects/${id}`, `/projects/${id}/start`, `/projects/${id}/inputs`, `/projects/${id}/dataroom`,
                 `/projects/${id}/plan`, `/projects/${id}/library`, `/projects/${id}/history`, "/no-such-page"];
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of pages) await check(page, path);
  }
});

test("the shell: fixed navigation with the project's steps on a desktop, a menu on a phone", async ({ page, request }) => {
  const id = await projectWithInputs(request, "Shellamide", [{ study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }]);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${id}/inputs`);
  const steps = page.getByRole("navigation", { name: "Project steps" });
  await expect(steps).toBeVisible();
  await expect(steps.getByTestId("step-start")).toHaveAttribute("data-state", /done|needs_you|running|not_started/);
  await expect(page.getByTestId("nav-inputs")).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("navigation", { name: "Breadcrumbs" })).toContainText("Inputs");
  await expect(page.getByTestId("nav-menu")).toBeHidden();                      // no menu button on a desktop
  await page.screenshot({ path: test.info().outputPath("shell-desktop.png") });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByTestId("sidebar")).toBeHidden();                       // closed until asked for
  await page.getByTestId("nav-menu").click();
  await expect(page.getByTestId("nav-menu")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("nav-library")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("shell-phone-menu.png") });
  await page.getByTestId("nav-library").click();                               // a choice closes the menu
  await page.waitForURL(/\/library$/);
  await expect(page.getByTestId("sidebar")).toBeHidden();
});
