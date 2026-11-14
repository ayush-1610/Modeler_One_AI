// The motion system of the "Modeler One App" design (theme spec §5; plan 2026-11-06-app-design-merge §6): a damped
// spring engine that sleeps when nothing moves, magnetic surfaces, scroll life (reveal, the head's parallax, the progress
// bar, the step bar's compact state) and rolling counters (`rollTo`). Framework-agnostic: each entry point returns its cleanup.
// Motion only: nothing here reads or changes data. Everything is skipped when the viewer asks for reduced motion.

export const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A damped spring: stiffness 180, damping 22, mass 0.8 settle with a slight rebound. */
export class Spring {
  x: number; v = 0; t: number; k: number; c: number; m: number;
  constructor(v = 0, o: { stiffness?: number; damping?: number; mass?: number } = {}) {
    this.x = v; this.t = v; this.k = o.stiffness ?? 180; this.c = o.damping ?? 22; this.m = o.mass ?? 0.8;
  }
  /** One step of `dt` seconds; true when at rest. */
  step(dt: number): boolean {
    const a = (-this.k * (this.x - this.t) - this.c * this.v) / this.m;
    this.v += a * dt; this.x += this.v * dt;
    return Math.abs(this.v) < 0.005 && Math.abs(this.x - this.t) < 0.005;
  }
}

type Item = { springs: Spring[]; paint: () => void };
const live = new Set<Item>();
let last = 0, raf = 0;
function tick(now: number) {
  const dt = Math.min((now - (last || now)) / 1000, 1 / 30) / 2;   // clamped, two substeps for stability
  last = now;
  live.forEach((it) => {
    const rest = it.springs.map((s) => s.step(dt) && s.step(dt)).every(Boolean);
    it.paint();
    if (rest) live.delete(it);
  });
  raf = live.size ? requestAnimationFrame(tick) : 0;
  if (!raf) last = 0;
}
/** Animate an item until its springs rest; the loop stops when nothing moves. */
export function wake(it: Item) {
  live.add(it);
  if (!raf) raf = requestAnimationFrame(tick);
}

/** `data-magnet` surfaces lean up to 6 px toward the pointer and carry a light under it (`--lx`/`--ly`). Painted with the
 *  `translate` property, so `transform` stays free for hover lift and press. */
export function magnet(root: HTMLElement): () => void {
  if (reducedMotion()) return () => {};
  const items = new WeakMap<HTMLElement, { sx: Spring; sy: Spring; item: Item }>();
  let current: HTMLElement | null = null;
  const of = (el: HTMLElement) => {
    let m = items.get(el);
    if (!m) {
      const sx = new Spring(0), sy = new Spring(0);
      m = { sx, sy, item: { springs: [sx, sy], paint: () => { el.style.translate = `${sx.x.toFixed(2)}px ${sy.x.toFixed(2)}px`; } } };
      items.set(el, m);
    }
    return m;
  };
  const release = (el: HTMLElement | null) => {
    if (!el) return;
    const m = of(el); m.sx.t = 0; m.sy.t = 0; wake(m.item);
  };
  const move = (e: PointerEvent) => {
    const el = (e.target as Element | null)?.closest?.("[data-magnet]") as HTMLElement | null;
    if (el !== current) { release(current); current = el; }
    if (!el) return;
    const r = el.getBoundingClientRect();
    const nx = (e.clientX - r.left) / r.width, ny = (e.clientY - r.top) / r.height;
    el.style.setProperty("--lx", `${(nx * 100).toFixed(1)}%`);
    el.style.setProperty("--ly", `${(ny * 100).toFixed(1)}%`);
    const m = of(el); m.sx.t = (nx - 0.5) * 12; m.sy.t = (ny - 0.5) * 12; wake(m.item);
  };
  const leave = () => { release(current); current = null; };
  root.addEventListener("pointermove", move, { passive: true });
  root.addEventListener("pointerleave", leave);
  return () => { root.removeEventListener("pointermove", move); root.removeEventListener("pointerleave", leave); };
}

const EASE = "cubic-bezier(0.25, 1, 0.5, 1)";

/** Scroll life: sections below the fold fade in, in sequence, as they scroll in; the head recedes (its art at 0.32x, its copy at 0.14x, fading by
 *  380 px and blurring up to 6 px); the 3 px bar at the top shows how far down the page is; the step bar compacts once
 *  the head is passed. New sections (a client read that finishes later) are picked up as they appear. */
export function scrollFx(main: HTMLElement): () => void {  // `main`: the page area that holds each page's <main>
  const progress = document.getElementById("mo-prog");
  const reduce = reducedMotion();
  const timers: number[] = [];
  const seen = new WeakSet<Element>();
  // what waits to fade in carries `.reveal-pending` (opacity 0, design.css), not an inline style, so print and save-as-PDF
  // show it (the print rule) and tooling can turn it off
  const PENDING = "reveal-pending";
  const pending = new Set<HTMLElement>();
  const settle = (el: HTMLElement) => {
    // the reveal's inline transition goes once it has played
    timers.push(window.setTimeout(() => { el.style.transition = ""; }, 900));
  };
  const show = (el: HTMLElement) => { pending.delete(el); el.classList.remove(PENDING); };
  const reveal = (el: HTMLElement, i: number) => {
    timers.push(window.setTimeout(() => {
      el.style.transition = `opacity 800ms ${EASE}`;
      show(el);
      settle(el);
    }, i * 90));
  };
  let batch = 0;
  const io = new IntersectionObserver((entries) => {
    batch = 0;
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      io.unobserve(e.target);
      reveal(e.target as HTMLElement, batch++);
    }
  }, { threshold: 0.06, rootMargin: "0px 0px -5% 0px" });
  // safety net: anything still hidden on screen after 1.8 s is shown (an observer can miss a fast layout change); it runs
  // only while something waits
  let net = 0;
  const check = () => {
    pending.forEach((el) => {
      if (!el.isConnected) { pending.delete(el); return; }
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight && r.bottom > 0) { io.unobserve(el); reveal(el, 0); }
    });
    if (!pending.size) { window.clearInterval(net); net = 0; }
  };
  const SELECTOR = "section, details, .card, .input-block, [data-reveal]";
  const prepare = () => {
    if (reduce) return;
    main.querySelectorAll<HTMLElement>(SELECTOR).forEach((el) => {
      if (seen.has(el) || el.closest("[data-magnet], .hero-band, .dialog, .stepper-wrap") || el.parentElement?.closest(SELECTOR)) return;
      seen.add(el);
      // what is already on screen stays put (a page that just opened is read and used at once); what is below rises as
      // the page is scrolled to it
      if (el.getBoundingClientRect().top < window.innerHeight) return;
      // a fade in place, never a rise: a figure being digitized or a drop target must not move under the pointer, or a
      // point would be recorded where the person did not click
      el.classList.add(PENDING);
      pending.add(el);
      io.observe(el);
    });
    if (pending.size && !net) net = window.setInterval(check, 1800);
  };
  prepare();
  let queued = 0;
  const mo = new MutationObserver(() => { if (!queued) queued = requestAnimationFrame(() => { queued = 0; prepare(); }); });
  mo.observe(main, { childList: true, subtree: true });
  // a printout or a saved PDF holds the whole page: everything still waiting is shown at once, without the fade
  const beforePrint = () => { pending.forEach((el) => { io.unobserve(el); show(el); }); };
  window.addEventListener("beforeprint", beforePrint);

  let ticking = false;
  const onScroll = () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      const y = window.scrollY;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      if (progress) progress.style.transform = `scaleX(${max > 0 ? Math.min(y / max, 1) : 0})`;
      const hero = main.querySelector<HTMLElement>(".hero-band");
      if (!reduce && hero) {
        const art = hero.querySelector<HTMLElement>(".hero-art");
        const copy = hero.querySelector<HTMLElement>(".hero-inner");
        if (art) art.style.translate = `0 ${(y * 0.32).toFixed(1)}px`;
        if (copy) {
          copy.style.translate = `0 ${(y * 0.14).toFixed(1)}px`;
          copy.style.opacity = String(Math.max(0, 1 - y / 380));
          copy.style.filter = y > 1 ? `blur(${Math.min(y / 70, 6).toFixed(2)}px)` : "";
        }
      }
      const bar = main.querySelector<HTMLElement>(".stepper-wrap");
      if (bar) bar.classList.toggle("compact", hero ? y > hero.offsetHeight - 40 : y > 40);
    });
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  return () => {
    io.disconnect(); mo.disconnect(); cancelAnimationFrame(queued); window.clearInterval(net); timers.forEach((t) => window.clearTimeout(t));
    pending.forEach(show);
    window.removeEventListener("scroll", onScroll);
    window.removeEventListener("beforeprint", beforePrint);
  };
}

/** Roll `el`'s number from what it shows to `target` on a softer spring, with a glow that follows its speed; exact after
 *  1.6 s. `el` must have no children React renders (the Counter component owns its text). */
export function rollTo(el: HTMLElement, target: number): () => void {
  if (reducedMotion()) { el.textContent = String(target); return () => {}; }
  const s = new Spring(Number(el.textContent) || 0, { stiffness: 120, damping: 20, mass: 1 });
  s.t = target;
  wake({ springs: [s], paint: () => {
    el.textContent = String(Math.round(s.x));
    const sp = Math.min(Math.abs(s.v) / 40, 1);
    el.style.textShadow = sp > 0.01 ? `0 ${(sp * 3).toFixed(1)}px ${(sp * 8).toFixed(1)}px rgba(0,113,227,${(0.35 * sp).toFixed(2)})` : "";
  } });
  const t = window.setTimeout(() => { s.x = target; s.v = 0; el.textContent = String(target); el.style.textShadow = ""; }, 1600);
  return () => window.clearTimeout(t);
}
