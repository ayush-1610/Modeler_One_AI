import { Hero } from "@/components/kit";

// What the page area shows while a server-rendered page is read (the campaign monitor, a project's run page): skeleton
// rows with a light sweeping across, never placeholder figures that could be taken for results.
export default function Loading() {
  return (
    <main aria-busy="true">
      <Hero title="Loading…" lede={<span className="page-loading" role="status" data-testid="page-loading">Reading the page from the API.</span>} />
      <div className="skeleton" aria-hidden style={{ marginTop: 32 }}>
        <div className="skeleton-row tall" />
        <div className="skeleton-row" style={{ width: "72%" }} />
        <div className="skeleton-row" style={{ width: "88%" }} />
        <div className="skeleton-row" style={{ width: "64%" }} />
      </div>
    </main>
  );
}
