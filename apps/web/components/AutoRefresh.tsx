"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// Re-fetches the current server component on an interval while `active` (e.g. a campaign is still running),
// so the campaign monitor fills in live as the single-node runner writes each round.
export function AutoRefresh({ active, intervalMs = 2500 }: { active: boolean; intervalMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(id);
  }, [active, intervalMs, router]);
  return null;
}
