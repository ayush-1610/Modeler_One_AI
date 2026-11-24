// Help (the redesign's P-30; the owner, 2026-11-24: the pages we are missing, and the steps for the AI model keys):
// the user guide, docs/USING_THE_TOOL.md, drawn from the repository the server runs, so the page and the guide never
// differ. Its contents on the side; each section has its own address (/help#<section>).

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { Hero } from "@/components/kit";
import { markdown } from "@/lib/markdown";

export const metadata = { title: "Help · Modeler One" };

const GUIDE = "docs/USING_THE_TOOL.md";

async function guide(): Promise<string | null> {
  // `next start` runs in apps/web; the guide is two folders up, in the same checkout (or rsync copy) the server runs
  for (const root of [join(process.cwd(), "..", ".."), process.cwd()]) {
    try {
      return await readFile(join(root, GUIDE), "utf-8");
    } catch {
      /* try the next place */
    }
  }
  return null;
}

export default async function HelpPage() {
  const source = await guide();
  if (source === null) {
    return (
      <main data-testid="help-page">
        <Hero eyebrow="Help" title="Using Modeler One" />
        <div className="banner err" role="alert">The guide ({GUIDE}) is not on this server. It is in the repository.</div>
      </main>
    );
  }
  const { body, headings } = markdown(source.replace(/^# .*\n/, ""));
  const sections = headings.filter((h) => h.level === 2);
  return (
    <main data-testid="help-page">
      <Hero eyebrow="Help" title="Using Modeler One"
            lede="The user guide: running the tool, the Data room, the AI models and their keys, Inputs, Review & sign." />
      <div className="help-layout">
        <nav className="help-toc" aria-label="Sections of the guide" data-testid="help-toc">
          <ul>{sections.map((h) => <li key={h.id}><a href={`#${h.id}`}>{h.text}</a></li>)}</ul>
        </nav>
        <article className="help-body" data-testid="help-body">{body}</article>
      </div>
    </main>
  );
}
