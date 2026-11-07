import { Hero } from "@/components/kit";

// What the page area shows while a server-rendered page is read (the campaign monitor, a project's run page): a plain
// statement, never placeholder figures that could be taken for results.
export default function Loading() {
  return (
    <main aria-busy="true">
      <Hero title="Loading…" lede={<span className="page-loading" role="status" data-testid="page-loading">Reading the page from the API.</span>} />
    </main>
  );
}
