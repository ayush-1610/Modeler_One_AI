// What a page shows while it is read (audit item 9): the page's own shape (its head, the step bar, its cards) in skeleton
// rows with a light sweeping across. Never placeholder figures that could be taken for results, and nothing to click:
// the skeleton is decoration, and the one status line says the page is being read.

import type { ReactNode } from "react";

import { Hero, type HeroTone } from "@/components/kit";

/** Skeleton rows of the given widths (percent); `tall` is a card-sized block. */
export function Skeleton({ rows = [72, 88, 64], tall = false }: { rows?: number[]; tall?: boolean }) {
  return (
    <div className="skeleton mt-32" aria-hidden>
      {tall && <div className="skeleton-row tall" />}
      {rows.map((w, i) => <div key={i} className="skeleton-row" style={{ width: `${w}%` }} />)}
    </div>
  );
}

/** A whole page while it is read: its head (tone and, where it never changes, its title) and its body as cards
 *  or rows. */
export function PageSkeleton({ tone, eyebrow, title = "Loading…", body = "rows", wide = false }: {
  tone?: HeroTone; eyebrow?: string; title?: ReactNode;
  /** "cards": two columns of cards (a project's overview); "canvas": one large block (the plan); "rows": a list. */
  body?: "cards" | "canvas" | "rows";
  wide?: boolean;
}) {
  return (
    <main aria-busy="true" className={wide ? "wide" : undefined}>
      <Hero tone={tone} eyebrow={eyebrow} title={title}
            lede={<span className="page-loading" role="status" data-testid="page-loading">Reading the page from the API.</span>} />
      {body === "cards" && (
        <div className="skeleton skeleton-cols mt-32" aria-hidden>
          <div className="skeleton-row card" /><div className="skeleton-row card" />
        </div>
      )}
      {body === "canvas" && (
        <div className="skeleton mt-32" aria-hidden>
          <div className="skeleton-row card h-420" />
        </div>
      )}
      <Skeleton rows={[72, 88, 64]} tall={body === "rows"} />
    </main>
  );
}
