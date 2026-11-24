"use client";

// The last resort: an error in the root layout itself (app/error.tsx covers the pages). It draws its own document, says
// nothing was changed, and offers to draw the page again or go to the start.

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body className="auth-body">
        <main className="auth-page" data-testid="global-error">
          <section className="auth-card">
            <h1>Modeler One could not be shown</h1>
            <p>Nothing was changed. Try again, or go back to the start.</p>
            {error.digest && <p className="muted">Reference <code>{error.digest}</code> in the web server&apos;s log.</p>}
            <div className="auth-acts">
              <button type="button" className="btn primary" onClick={reset}>Try again</button>
              <a className="btn" href="/">Back to the start</a>
            </div>
          </section>
        </main>
      </body>
    </html>
  );
}
