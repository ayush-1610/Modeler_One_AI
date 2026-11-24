"use client";

// The product's mark. The console's navigation itself is components/shell (the redesign, slice 1); this file keeps the
// mark because the evidence report's cover draws it too (components/dataroom/Report.tsx).

import { useId } from "react";

/** The product's mark, "Dose to curve" (plan 2026-11-21 v2 §10, option A): a concentration curve rising from a dose
 *  point and settling, one line through small nodes, indigo to magenta, on a transparent background (no box). The same
 *  mark is the app's icon (app/icon.svg). `light`: the same mark in white for the console's navy top bar (design option 5,
 *  2026-11-24), where the indigo line would vanish. */
export function Logo({ size = 28, light = false }: { size?: number; light?: boolean }) {
  // each mark its own gradient: a second mark on the page (the report's cover) must not lean on the sidebar's, which
  // print hides
  const gradient = `mo-la-${useId().replace(/:/g, "")}`;
  if (light) return (
    <svg className="brand-logo" aria-hidden viewBox="0 0 64 64" width={size} height={size}>
      <path d="M8 50 C 13 50, 15 17, 23 17 S 36 40, 58 46" fill="none" stroke="#FFFFFF" strokeWidth="5" strokeLinecap="round" />
      <circle cx="8" cy="50" r="5" fill="#FFFFFF" />
      <circle cx="23" cy="17" r="4" fill="#001B94" stroke="#FFFFFF" strokeWidth="3" />
      <circle cx="42" cy="38.6" r="3.4" fill="#001B94" stroke="#F5B8DA" strokeWidth="3" />
    </svg>
  );
  return (
    <svg className="brand-logo" aria-hidden viewBox="0 0 64 64" width={size} height={size}>
      <defs>
        <linearGradient id={gradient} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#3B1F7A" /><stop offset="1" stopColor="#C2307A" />
        </linearGradient>
      </defs>
      <path d="M8 50 C 13 50, 15 17, 23 17 S 36 40, 58 46" fill="none" stroke={`url(#${gradient})`} strokeWidth="5" strokeLinecap="round" />
      <circle cx="8" cy="50" r="5" fill="#3B1F7A" />
      <circle cx="23" cy="17" r="4" fill="#fff" stroke="#5B2C9C" strokeWidth="3" />
      <circle cx="42" cy="38.6" r="3.4" fill="#fff" stroke="#A8307F" strokeWidth="3" />
    </svg>
  );
}
