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

/** Text below the AA contrast its size asks for (WCAG 2.x SC 1.4.3): 4.5:1, or 3:1 for large text (24 px, or 18.66 px
 *  bold), against what is behind it: the backgrounds up the tree, a translucent one blended over the one under it, and the
 *  text's own and its ancestors' opacity blended in. Left out, as the criterion leaves them out or styles cannot say: a
 *  disabled control's text, text over an image or a gradient, a chart's own drawing (SVG), hidden text. The Graphite
 *  restyle's accessibility pass (R4). Each finding names the element, its words, the ratio and the two colours. */
export async function lowContrast(page: Page): Promise<string[]> {
  // colours at rest: a row's fade-in (kit.css table-row-in) measured half-way reads as low contrast; a spinner never ends
  await page.evaluate(() => Promise.race([
    Promise.all(document.getAnimations().filter((a) => a.effect?.getTiming().iterations !== Infinity).map((a) => a.finished.catch(() => null))),
    new Promise((done) => setTimeout(done, 2_000)),
  ]));
  return page.evaluate(() => {
    type C = [number, number, number, number];
    const parse = (c: string): C | null => {
      let m = /^rgba?\(([^)]+)\)$/.exec(c);
      if (m) { const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
      m = /^color\(srgb ([^)]+)\)$/.exec(c);   // a color-mix() is computed as color(srgb r g b / a), each 0..1
      if (m) { const p = m[1].split(/[\s/]+/).filter(Boolean).map(Number); return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1]; }
      return null;
    };
    const over = (top: C, under: C): C => {
      const a = top[3] + under[3] * (1 - top[3]);
      if (a === 0) return [255, 255, 255, 0];
      return [0, 1, 2].map((i) => (top[i] * top[3] + under[i] * under[3] * (1 - top[3])) / a).concat(a) as C;
    };
    const lum = (c: C) => {
      const [r, g, b] = c.slice(0, 3).map((v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const hex = (c: C) => "#" + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
    const found = new Map<string, string>();
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const own = Array.from(el.childNodes).filter((n) => n.nodeType === Node.TEXT_NODE).map((n) => n.textContent ?? "").join("").trim();
      if (!own || !/[\p{L}\p{N}]/u.test(own)) continue;
      if (!el.checkVisibility({ visibilityProperty: true, opacityProperty: true })) continue;
      if (el.closest("[aria-hidden=true], svg, .js-plotly-plot, :disabled, [aria-disabled=true], .sr-only")) continue;
      const style = getComputedStyle(el);
      const fg = parse(style.color);
      if (!fg) continue;
      // what is behind the text: each background up the tree, until one is opaque; the window's white under them all
      const layers: C[] = [];
      let unknown = false, opacity = 1;
      for (let a: HTMLElement | null = el; a; a = a.parentElement) {
        const st = getComputedStyle(a);
        opacity *= Number(st.opacity);
        if (st.backgroundImage !== "none") { unknown = true; break; }
        const bg = parse(st.backgroundColor);
        if (bg && bg[3] > 0) { layers.push(bg); if (bg[3] >= 1) break; }
      }
      if (unknown) continue;
      let back: C = [255, 255, 255, 1];
      for (const layer of layers.reverse()) back = over(layer, back);
      const text = over([fg[0], fg[1], fg[2], fg[3] * opacity], back);
      const l1 = lum(text), l2 = lum(back);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const size = parseFloat(style.fontSize), bold = Number(style.fontWeight) >= 700;
      const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
      if (ratio + 0.005 >= need) continue;
      const who = `${el.tagName.toLowerCase()}.${(el.getAttribute("class") || "").split(" ")[0]}`;
      const key = `${who} ${hex(text)} on ${hex(back)}`;
      if (!found.has(key)) found.set(key, `${who} "${own.slice(0, 28)}" ${ratio.toFixed(2)}:1 (${hex(text)} on ${hex(back)}, needs ${need})`);
    }
    return [...found.values()].slice(0, 20);
  });
}

/** Open a page and wait for the page itself, not its loading screen (a route's loading screen streams first). */
export async function open(page: Page, path: string) {
  await page.goto(path);
  await expect(page.locator('main[aria-busy="true"]')).toHaveCount(0);
  await expect(page.locator("main h1").first()).toBeVisible();
}
