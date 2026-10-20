"use client";

// A page that failed while it was drawn says so, with what the browser was told, instead of a blank area or sample
// data. "Try again" draws it once more; nothing is changed on the server.

import Link from "next/link";

export default function PageError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="page-state" data-testid="page-error">
      <h1>This page could not be shown</h1>
      <div className="banner err" role="alert">
        {error.message || "The page stopped while it was drawn."}
        {error.digest && <> (reference <code>{error.digest}</code> in the web server&apos;s log)</>}
      </div>
      <p>Nothing was changed. Try again, or go back to the projects.</p>
      <div className="row">
        <button type="button" className="btn primary" onClick={reset}>Try again</button>
        <Link className="btn" href="/">Projects</Link>
      </div>
    </main>
  );
}
