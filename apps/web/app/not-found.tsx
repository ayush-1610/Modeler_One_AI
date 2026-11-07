import Link from "next/link";

import { Hero } from "@/components/kit";

// An address with no page behind it (a mistyped link, or a page the redesign has retired).
export default function NotFound() {
  return (
    <main data-testid="page-not-found">
      <Hero tone="projects" eyebrow="404" title="There is no page here"
            lede="The address may be mistyped, or the page may have been retired in the redesign. Every project is reached from the projects list."
            actions={<>
              <Link className="btn primary" href="/">Projects</Link>
              <Link className="btn" href="/projects/start">Start from a proposal</Link>
            </>} />
    </main>
  );
}
