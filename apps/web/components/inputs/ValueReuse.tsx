"use client";

// What the person's other projects of the same drug found (plan 2026-11-05 §3.3: "reuse what other projects of the same
// drug found, with the person's consent per project"): literature and public-source values only, a client's data never
// leaving its project. "Use them" is the consent: each value is proposed here anew with its source, to decide as any.
// Each button is named with the project it takes from (the acceptance pass, slice 10: two offers read "Use them" twice).

import { send } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { idWords } from "@/lib/words";

import { REUSED } from "./after";
import type { Run } from "./InputsTodo";

export function ValueReuse({ projectId, run }: { projectId: string; run: Run }) {
  const offers = useResource("/api/v1/projects/{project_id}/value-reuse", { project_id: projectId });
  const list = offers.data?.offers ?? [];
  if (!list.length) return null;
  // two projects of the drug may share a name: then each says its id too, on the page and in its button's name
  const named = (o: (typeof list)[number]) => (list.filter((x) => x.name === o.name).length > 1 ? `${o.name} (${o.project_id})` : o.name);
  const count = (n: number) => `${n} value${n === 1 ? "" : "s"}`;
  return (
    <section className="value-reuse" data-testid="value-reuse">
      <h3>The same drug in your other projects</h3>
      <p className="muted">Values from the literature and public sources only; a client&apos;s data stays in its project.
        Each value comes with its source and quote, to decide here like any other.</p>
      <ul>
        {list.map((o) => (
          <li key={o.project_id} data-testid={`reuse-${o.project_id}`}>
            <strong>{named(o)}</strong>: {count(o.values)}
            <span className="muted"> ({o.what.slice(0, 4).map(idWords).join(", ")}{o.what.length > 4 ? ", …" : ""})</span>{" "}
            <button type="button" className="btn small" data-testid={`reuse-use-${o.project_id}`}
                    aria-label={`Use them: the ${count(o.values)} from ${named(o)}`}
                    onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/value-reuse",
                                                       { project_id: projectId }, { project_id: o.project_id }),
                                            `${count(o.values)} from ${o.name} proposed here, with their sources.`, REUSED)}>
              Use them</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
