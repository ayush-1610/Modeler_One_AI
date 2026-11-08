"use client";

// The design's global motion and feedback (theme spec §4.13, §4.14, §4.16, §5; plan 2026-11-06-app-design-merge §6):
// the scroll progress bar, magnetic surfaces, scroll life, the page transition, the toast and the celebration burst.
// Mounted once in the root layout. Motion and feedback only: no data is read or changed here.

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { magnet, reducedMotion, rollTo, scrollFx } from "@/lib/motion";

const TOAST = "mo-toast";
const BURST = "mo-burst";

/** One calm sentence at the bottom of the screen, gone after 2.4 s (every action's result may use it). */
export function toast(message: string) {
  window.dispatchEvent(new CustomEvent(TOAST, { detail: message }));
}

/** The celebration after a signature or a completion: the light blooms from the top of the screen, then clears. */
export function celebrate() {
  window.dispatchEvent(new Event(BURST));
}

export function Motion() {
  const path = usePathname();
  const [message, setMessage] = useState("");
  const [burst, setBurst] = useState(false);

  // magnetic surfaces, once for the whole document
  useEffect(() => magnet(document.body), []);

  // scroll life and the page transition, for each page
  useEffect(() => {
    const area = document.querySelector<HTMLElement>(".content");
    if (!area) return;
    const main = area.querySelector<HTMLElement>(":scope > main");
    if (main && !reducedMotion()) {
      // a fade, not a rise: a page used at once (a drop on the plan canvas, a point on a figure) must not move under the
      // pointer while it enters
      main.style.transition = "none"; main.style.opacity = "0";
      const t = window.setTimeout(() => {
        main.style.transition = "opacity 500ms cubic-bezier(0.25,1,0.5,1)";
        main.style.opacity = "";
      }, 40);
      const clear = window.setTimeout(() => { main.style.transition = ""; }, 700);
      const stop = scrollFx(area);
      return () => { window.clearTimeout(t); window.clearTimeout(clear); stop(); };
    }
    return scrollFx(area);
  }, [path]);

  useEffect(() => {
    let hide = 0, clear = 0;
    const onToast = (e: Event) => {
      setMessage((e as CustomEvent<string>).detail);
      window.clearTimeout(hide);
      hide = window.setTimeout(() => setMessage(""), 2400);
    };
    const onBurst = () => {
      if (reducedMotion()) return;
      setBurst(true);
      window.clearTimeout(clear);
      clear = window.setTimeout(() => setBurst(false), 1100);
    };
    window.addEventListener(TOAST, onToast);
    window.addEventListener(BURST, onBurst);
    return () => {
      window.removeEventListener(TOAST, onToast); window.removeEventListener(BURST, onBurst);
      window.clearTimeout(hide); window.clearTimeout(clear);
    };
  }, []);

  return (
    <>
      <div className="mo-progress" aria-hidden><div id="mo-prog" /></div>
      <div className={`mo-burst${burst ? " on" : ""}`} aria-hidden />
      <div className={`mo-toast${message ? " on" : ""}`} role="status" aria-live="polite" data-testid="toast">{message}</div>
    </>
  );
}

/** A number that rolls to its value on a spring (theme spec §5.5). The server renders the value; the roll is motion. */
export function Counter({ value, className }: { value: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const first = useRef(true);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (first.current) { first.current = false; el.textContent = "0"; }
    return rollTo(el, value);
  }, [value]);
  return <span ref={ref} className={className} data-count={value} suppressHydrationWarning>{value}</span>;
}
