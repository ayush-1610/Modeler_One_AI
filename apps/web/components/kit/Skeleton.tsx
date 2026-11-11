// What a page shows while it is read (audit item 9): the page's own shape (its head, the step bar, its cards) in skeleton
// rows with a light sweeping across. Never placeholder figures that could be taken for results, and nothing to click:
// the skeleton is decoration, and the one status line says the page is being read.

import type { ReactNode } from "react";

import { Hero, type HeroTone } from "@/components/kit";

/** Skeleton rows of the given widths (percent); `tall` is a card-sized block. */
export function Skeleton({ rows = [72, 88, 64], tall = false }: { rows?: number[]; tall?: boolean }) {
  return (
    <div className="skeleton" aria-hidden style={{ marginTop: 32 }}>
      {tall && <div className="skeleton-row tall" />}
      {rows.map((w, i) => <div key={i} className="skeleton-row" style={{ width: `${w}%` }} />)}
    </div>
  );
}

/** Where the project's four steps will be, while they are read (the Stepper streams in after the page's head). */
export function StepperSkeleton() {
  return (
    // in the step bar's own place and size (.stepper-wrap), so the page does not shift when the steps arrive
    <div className="stepper-wrap" aria-hidden data-testid="stepper-loading">
      <div className="skeleton"><div className="skeleton-row pill" /></div>
    </div>
  );
}

/** A whole page while it is read: its head (tone, pill and, where it never changes, its title), the step bar for a
 *  project's step pages, and its body as cards or rows. */
export function PageSkeleton({ tone, eyebrow, title = "Loading…", stepper = false, body = "rows", wide = false }: {
  tone?: HeroTone; eyebrow?: string; title?: ReactNode; stepper?: boolean;
  /** "cards": two columns of cards (a project's overview); "canvas": one large block (the plan); "rows": a list. */
  body?: "cards" | "canvas" | "rows";
  wide?: boolean;
}) {
  return (
    <main aria-busy="true" className={wide ? "wide" : undefined}>
      <Hero tone={tone} eyebrow={eyebrow} title={title}
            lede={<span className="page-loading" role="status" data-testid="page-loading">Reading the page from the API.</span>} />
      {stepper && <StepperSkeleton />}
      {body === "cards" && (
        <div className="skeleton skeleton-cols" aria-hidden style={{ marginTop: 32 }}>
          <div className="skeleton-row card" /><div className="skeleton-row card" />
        </div>
      )}
      {body === "canvas" && (
        <div className="skeleton" aria-hidden style={{ marginTop: 32 }}>
          <div className="skeleton-row card" style={{ height: 420 }} />
        </div>
      )}
      <Skeleton rows={[72, 88, 64]} tall={body === "rows"} />
    </main>
  );
}
