"use client";

// Action results and the old motion system's last callers (console redesign slice 1, decision G1-2: no decorative
// motion). What remains: `toast`, one calm sentence for an action's result, in a polite live region; `celebrate` and
// `Counter` are kept for their callers and do nothing decorative (no burst, no rolling number). The scroll progress bar,
// magnetic surfaces, scroll reveal and page transition are gone (lib/motion.ts with them).

import { useEffect, useState } from "react";

const TOAST = "mo-toast";

/** One calm sentence for an action's result, at the bottom of the screen, gone after 4 s. */
export function toast(message: string) {
  window.dispatchEvent(new CustomEvent(TOAST, { detail: message }));
}

/** Kept for its callers (after a signature or a completion): the console celebrates nothing; the result is said in words. */
export function celebrate() {}

/** The region every toast is spoken and shown in. Mounted once in the root layout. */
export function Toaster() {
  const [message, setMessage] = useState("");
  useEffect(() => {
    let hide = 0;
    const onToast = (e: Event) => {
      setMessage((e as CustomEvent<string>).detail);
      window.clearTimeout(hide);
      hide = window.setTimeout(() => setMessage(""), 4000);
    };
    window.addEventListener(TOAST, onToast);
    return () => { window.removeEventListener(TOAST, onToast); window.clearTimeout(hide); };
  }, []);
  return <div className={`mo-toast${message ? " on" : ""}`} role="status" aria-live="polite" data-testid="toast">{message}</div>;
}

/** A number, as it is (the rolling count is gone). */
export function Counter({ value, className }: { value: number; className?: string }) {
  return <span className={className} data-count={value}>{value}</span>;
}
