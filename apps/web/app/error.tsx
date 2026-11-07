"use client";

// A page that failed while it was drawn says so, with what the browser was told, instead of a blank area or sample
// data. "Try again" draws it once more; nothing is changed on the server.

import Link from "next/link";

import { Hero } from "@/components/kit";

export default function PageError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main data-testid="page-error">
      <Hero tone="inbox" eyebrow="Something went wrong" title="This page could not be shown"
            lede="Nothing was changed. Try again, or go back to the projects."
            actions={<>
              <button type="button" className="btn primary" onClick={reset}>Try again</button>
              <Link className="btn" href="/">Projects</Link>
            </>} />
      <div className="banner err page-state-detail" role="alert">
        {error.message || "The page stopped while it was drawn."}
        {error.digest && <> (reference <code>{error.digest}</code> in the web server&apos;s log)</>}
      </div>
    </main>
  );
}
