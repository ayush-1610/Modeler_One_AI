"use client";

// What the person's other projects of the same drug found (plan 2026-11-05 §3.3: "reuse what other projects of the same
// drug found, with the person's consent per project"): literature and public-source values only, a client's data never
// leaving its project. "Use them" is the consent: each value is proposed here anew with its source, to decide as any.

import { send } from "@/lib/api";
import { useResource } from "@/lib/hooks";

import type { Run } from "./InputsTodo";

export function ValueReuse({ projectId, run }: { projectId: string; run: Run }) {
  const offers = useResource("/api/v1/projects/{project_id}/value-reuse", { project_id: projectId });
  const list = offers.data?.offers ?? [];
  if (!list.length) return null;
  return (
    <section className="value-reuse" data-testid="value-reuse">
      <h3>The same drug in your other projects</h3>
      <p className="muted">Values from the literature and public sources only; a client&apos;s data stays in its project.
        Each value comes with its source and quote, to decide here like any other.</p>
      <ul>
        {list.map((o) => (
          <li key={o.project_id} data-testid={`reuse-${o.project_id}`}>
            <strong>{o.name}</strong>: {o.values} value{o.values === 1 ? "" : "s"}
            <span className="muted"> ({o.what.slice(0, 4).join(", ")}{o.what.length > 4 ? ", …" : ""})</span>{" "}
            <button type="button" className="btn small" data-testid={`reuse-use-${o.project_id}`}
                    onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/value-reuse",
                                                       { project_id: projectId }, { project_id: o.project_id }),
                                            `${o.values} value${o.values === 1 ? "" : "s"} from ${o.name} proposed here, with their sources.`)}>
              Use them</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
