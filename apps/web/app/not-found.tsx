import Link from "next/link";

// An address with no page behind it (a mistyped link, or a page the redesign has retired).
export default function NotFound() {
  return (
    <main className="page-state" data-testid="page-not-found">
      <h1>There is no page here</h1>
      <p>The address may be mistyped, or the page may have been retired in the redesign. Every project is reached from the
        projects list.</p>
      <div className="row">
        <Link className="btn primary" href="/">Projects</Link>
        <Link className="btn" href="/projects/start">Start from a proposal</Link>
      </div>
    </main>
  );
}
