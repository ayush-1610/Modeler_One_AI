"use client";

// The bar of a batch (plan 2026-11-14 slice 4; the design text's kit `BulkBar`): how many rows are picked, what is done
// with them and the one reason, kept in view at the bottom of its table while the person scrolls it (on a phone too).
// Shown only while something is picked.

import type { ReactNode } from "react";

export function BulkBar({ count, noun, many, onClear, label, testId, children }: {
  count: number;
  /** what a row is: "file", "group of loose numbers" */
  noun: string;
  many?: string;
  onClear: () => void;
  /** the bar's name, read as a region ("Link the picked files") */
  label: string;
  testId?: string;
  /** the batch's choices and its reason form */
  children: ReactNode;
}) {
  if (!count) return null;
  return (
    <div className="bulk-bar" role="region" aria-label={label} data-testid={testId}>
      <div className="bulk-bar-head">
        <strong data-testid={testId && `${testId}-count`}>{count} {count === 1 ? noun : many ?? `${noun}s`} picked</strong>
        <button type="button" className="link-btn" onClick={onClear} data-testid={testId && `${testId}-clear`}>Clear</button>
      </div>
      {children}
    </div>
  );
}
