"use client";

// What a decision did, said to a screen reader (plan 2026-11-14 slice 4; the design text's "After each decision": a polite
// live region announces it, "vessel_1…vessel_12 marked as not data. 33 loose numbers left."). One region per page part
// that makes decisions; `announce` reaches every region shown. The same words said twice are said again.

import { useEffect, useState } from "react";

const listeners = new Set<(text: string) => void>();

/** Say `text` in the live regions on the page. */
export function announce(text: string) {
  for (const l of listeners) l(text);
}

export function LiveRegion({ testId }: { testId?: string }) {
  const [text, setText] = useState("");
  useEffect(() => {
    const hear = (t: string) => setText((was) => (was === t ? `${t} ` : t));
    listeners.add(hear);
    return () => { listeners.delete(hear); };
  }, []);
  return <p className="sr-only" role="status" aria-live="polite" data-testid={testId}>{text}</p>;
}
