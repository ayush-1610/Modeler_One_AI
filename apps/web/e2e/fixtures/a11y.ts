// The console's page checks (docs/plans/2026-11-23-console-redesign-implementation.md §5; design-review/DESIGN_SYSTEM.md
// §7): the checks the approved prototype passed (design-review/WIREFRAMES.md §6), on the real app, as the acceptance
// pass runs them over every page (acceptance.spec.ts; the console redesign's slice 10).
import { expect, type Page } from "@playwright/test";

const CONTROLS = "a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=menuitem]";

/** Visible controls with no accessible name: aria-label, aria-labelledby, their text, a title, a placeholder, or a label. */
export async function unnamed(page: Page): Promise<string[]> {
  return page.evaluate((selector) => {
    const named = (el: Element) => {
      const by = el.getAttribute("aria-labelledby");
      const text = (el.getAttribute("aria-label") || (by && by.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" "))
        || (el as HTMLElement).innerText || el.getAttribute("title") || el.getAttribute("placeholder")
        || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.textContent) || el.closest("label")?.textContent
        || (el.querySelector("img[alt]") as HTMLImageElement | null)?.alt || "").trim();
      return text.length > 0;
    };
    return Array.from(document.querySelectorAll(selector))
      .filter((el) => el.checkVisibility({ visibilityProperty: true, opacityProperty: true }) && !el.closest("[aria-hidden=true]"))
      .filter((el) => !named(el))
      .map((el) => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}.${(el.getAttribute("class") || "").split(" ")[0]} ${el.getAttribute("data-testid") ?? ""}`.trim());
  }, CONTROLS);
}

/** How far the page scrolls sideways, and what sticks out past the window (outside a box that scrolls by itself). */
export async function sideways(page: Page): Promise<[number, string]> {
  return page.evaluate(() => [document.documentElement.scrollWidth - window.innerWidth,
    [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1
      && !e.closest(".table-scroll, .tbl-scroll, .dag-scroll, .tabs")).slice(0, 6)
      .map((e) => `${e.tagName.toLowerCase()}.${(e.getAttribute("class") || "").split(" ")[0]}`).join(", ")] as [number, string]);
}

/** Controls smaller than 24 x 24 CSS px to the pointer (WCAG 2.2 SC 2.5.8), with the criterion's exceptions: a link
 *  inside a sentence (inline), a control the browser draws at its own size (a native checkbox, radio or select), and a
 *  small target with room around it (a 24 px circle on its centre touches no other target). The hit area is the box or
 *  its invisible ::after (app/styles/targets.css), whichever is larger. */
export async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate((selector) => {
    const visible = Array.from(document.querySelectorAll(selector))
      .filter((el) => el.checkVisibility({ visibilityProperty: true, opacityProperty: true }) && !el.closest("[aria-hidden=true]"))
      .filter((el) => !(el as HTMLInputElement).disabled);
    const hit = (el: Element) => {
      const box = el.getBoundingClientRect();
      const after = getComputedStyle(el, "::after");
      const extra = after.content !== "none" && after.content !== "normal" && after.position === "absolute";
      const w = Math.max(box.width, extra ? parseFloat(after.width) || 0 : 0);
      const h = Math.max(box.height, extra ? parseFloat(after.height) || 0 : 0);
      const cx = box.left + box.width / 2, cy = box.top + box.height / 2;
      return { w, h, cx, cy, left: cx - w / 2, right: cx + w / 2, top: cy - h / 2, bottom: cy + h / 2 };
    };
    const inline = (el: Element) => {
      if (el.tagName !== "A") return false;
      const block = el.parentElement;
      if (!block || getComputedStyle(el).display !== "inline") return false;
      return (block.textContent ?? "").trim().length > (el.textContent ?? "").trim().length + 3;
    };
    const native = (el: Element) => (el.tagName === "INPUT" && ["checkbox", "radio"].includes((el as HTMLInputElement).type))
      || (el.tagName === "SELECT" && !(el as HTMLElement).style.height);
    const boxes = visible.map((el) => ({ el, ...hit(el) }));
    const small = boxes.filter((b) => (b.w < 24 || b.h < 24) && !inline(b.el) && !native(b.el));
    const spaced = (b: (typeof boxes)[number]) => boxes.every((o) => {
      if (o.el === b.el || o.el.contains(b.el) || b.el.contains(o.el)) return true;
      // the 24 px circle on this one's centre reaches no other target, nor another small target's circle
      const nx = Math.max(o.left, Math.min(b.cx, o.right)), ny = Math.max(o.top, Math.min(b.cy, o.bottom));
      if (Math.hypot(nx - b.cx, ny - b.cy) < 12) return false;
      return !small.includes(o) || Math.hypot(o.cx - b.cx, o.cy - b.cy) >= 24;
    });
    return small.filter((b) => !spaced(b)).map((b) => `${b.el.tagName.toLowerCase()}.${(b.el.getAttribute("class") || "").split(" ")[0]} `
      + `${b.el.getAttribute("data-testid") ?? ((b.el as HTMLElement).innerText || "").trim().slice(0, 24)} ${Math.round(b.w)}x${Math.round(b.h)}`);
  }, CONTROLS);
}

/** Open a page and wait for the page itself, not its loading screen (a route's loading screen streams first). */
export async function open(page: Page, path: string) {
  await page.goto(path);
  await expect(page.locator('main[aria-busy="true"]')).toHaveCount(0);
  await expect(page.locator("main h1").first()).toBeVisible();
}
