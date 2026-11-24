"use client";

// An action's result in one calm sentence (design-review/DESIGN_SYSTEM.md; decision G1-2: no decorative motion). It
// replaced kit/Motion in the console redesign's slice 9: the burst, the rolling count and the springs are gone.

import { useEffect, useState } from "react";

const TOAST = "console-toast";

/** One calm sentence for an action's result, at the bottom of the screen, gone after 4 s. */
export function toast(message: string) {
  window.dispatchEvent(new CustomEvent(TOAST, { detail: message }));
}

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
  return <div className={`toast${message ? " on" : ""}`} role="status" aria-live="polite" data-testid="toast">{message}</div>;
}
