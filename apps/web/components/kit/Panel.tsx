import type { ReactNode } from "react";

// A panel of a page: an optional heading and the page's action for it, then what it holds. It replaced
// `components/ui.tsx` `Card` in the console redesign's slice 9 (the same markup, `.card`).

export function Panel({ title, action, children }: { title?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || action) && (
        <div className="spread mb-12">
          {title && <h2 className="m-0">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
