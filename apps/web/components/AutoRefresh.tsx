"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

/** The longest wait between refreshes while `backoff` holds (the API did not answer). */
const MAX_BACKOFF_MS = 30_000;

// Re-fetches the current server component on an interval while `active` (e.g. a campaign is still running),
// so the campaign monitor fills in live as the single-node runner writes each round. A hidden tab is not refreshed; it
// refreshes once when it is shown again. With `backoff` (the page could not read the API) the interval doubles up to
// 30 s. With `giveUpAfterMs` it stops after that long and shows `gaveUp` instead of its children.
export function AutoRefresh({ active, intervalMs = 2500, backoff = false, giveUpAfterMs, gaveUp, children }: {
  active: boolean; intervalMs?: number; backoff?: boolean; giveUpAfterMs?: number; gaveUp?: ReactNode; children?: ReactNode;
}) {
  const router = useRouter();
  const [stopped, setStopped] = useState(false);
  useEffect(() => {
    if (!active || stopped) return;
    const started = Date.now();
    let wait = intervalMs;
    let timer = 0;
    const next = () => {
      timer = window.setTimeout(() => {
        if (giveUpAfterMs !== undefined && Date.now() - started >= giveUpAfterMs) { setStopped(true); return; }
        if (!document.hidden) router.refresh();
        if (backoff) wait = Math.min(MAX_BACKOFF_MS, wait * 2);
        next();
      }, wait);
    };
    next();
    const shown = () => { if (!document.hidden) router.refresh(); };
    document.addEventListener("visibilitychange", shown);
    return () => { window.clearTimeout(timer); document.removeEventListener("visibilitychange", shown); };
  }, [active, stopped, intervalMs, backoff, giveUpAfterMs, router]);
  return <>{stopped ? gaveUp : children}</>;
}
