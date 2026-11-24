import Link from "next/link";

import { PageShell } from "@/components/kit";
import { HELP_TOPICS } from "@/lib/help";

/** Help (P-30): the topics on the left, the one open on the right. */
export function HelpPage({ topic }: { topic: string }) {
  const open = HELP_TOPICS.find((t) => t.id === topic) ?? HELP_TOPICS[0]!;
  return (
    <main>
      <PageShell title="Help" lede="How Modeler One works, in plain words.">
        <div className="help-layout">
          <nav className="help-topics" aria-label="Help topics">
            {HELP_TOPICS.map((t) => (
              <Link key={t.id} href={t.id === "start" ? "/help" : `/help/${t.id}`} aria-current={t.id === open.id ? "page" : undefined}
                    data-testid={`help-${t.id}`}>{t.title}</Link>
            ))}
          </nav>
          <section className="panel help-body" aria-labelledby="help-title">
            <div className="panel-head"><h2 id="help-title">{open.title}</h2></div>
            <div className="panel-body">{open.body.map((p) => <p key={p}>{p}</p>)}</div>
          </section>
        </div>
      </PageShell>
    </main>
  );
}
