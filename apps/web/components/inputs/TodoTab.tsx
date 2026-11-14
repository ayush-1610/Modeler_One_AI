"use client";

// The To do area (plan 2026-11-14 slice 1): what the old rail's side held, now the first area and full width. What is
// still missing to run, by the area it is settled in (each item opens there); what to ask the client; the inputs ready
// once nothing is missing; and the model checks with where values come from. Slice 2 builds it from the one list of work
// (lib/inputsWork.ts) instead of the /inputs to-do alone.

import Link from "next/link";

import { STEP_ROUTES } from "@/lib/pipeline";

import { ClientRequest } from "./ClientRequest";
import { LABEL, TITLE, type TodoItem } from "./InputsTodo";

type Check = { check: string; ok: boolean; detail: string[] };
export type Readiness = { ready: boolean; checks: Check[]; engine_dry_run: string };
type Area = { id: string; label: string };

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function TodoTab({ projectId, todo, areas, groupTitle, readiness, selectionRule, onOpen }: {
  projectId: string;
  /** the /inputs to-do, in the order it is settled */
  todo: TodoItem[];
  /** the input areas, in the area bar's order */
  areas: Area[];
  /** the title of a client-data group to confirm, by its id */
  groupTitle: (id: string) => string | undefined;
  readiness: Readiness | null | undefined;
  selectionRule: string;
  onOpen: (item: TodoItem) => void;
}) {
  const open = readiness ? readiness.checks.filter((c) => !c.ok).length : 0;
  const byArea = areas.map((a) => [a, todo.filter((t) => (t.tab ?? "compound") === a.id)] as const).filter(([, items]) => items.length);
  return (
    <>
      {todo.length > 0 ? (
        <section className="card todo-missing" data-testid="still-missing">
          <h2 className="mt-0">Still missing to run ({todo.length})</h2>
          <p className="muted m-0-0-8">Each item opens in the area where it is settled.</p>
          {byArea.map(([area, items]) => (
            <div key={area.id} className="todo-area">
              <h3>{area.label} <span className="muted">· {items.length}</span></h3>
              <ul className="missing-list">
                {items.map((t, i) => (
                  <li key={`${t.kind}-${t.target}-${i}`}>
                    <button type="button" className="link-btn" onClick={() => onOpen(t)} data-testid={`missing-${t.kind}-${t.target}`}>
                      {TITLE[t.kind]}{t.kind === "confirm" ? ` · ${groupTitle(t.target) ?? t.target}`
                        : t.kind !== "datasets" && t.kind !== "check" ? ` · ${LABEL[t.target] ?? t.target}` : ""}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <ClientRequest projectId={projectId} />
        </section>
      ) : readiness?.ready ? (
        <section className="card todo-ready" data-testid="inputs-ready">
          <h2 className="mt-0">Inputs are ready</h2>
          <p className="m-0-0-8">Everything S0 needs is here, and every planned simulation builds.</p>
          <Link className="btn primary" href={STEP_ROUTES.review(projectId)}>Go to Review &amp; sign</Link>
        </section>
      ) : (
        <section className="card" data-testid="assembling"><p className="m-0">The inputs are being put together.</p></section>
      )}
      {/* the checks and where values come from, folded: the list above is what the area is for (2026-11-11 audit, item 4) */}
      <details className="card inputs-more" data-testid="inputs-more">
        <summary>
          <span className="inputs-more-title">Readiness and sources</span>
          {readiness && <span className={`chip ${open ? "high" : "low"}`}>{open ? `${plural(open, "check")} open` : "all checks ok"}</span>}
        </summary>
        {readiness && (
          <>
            <ul className="checks" data-testid="readiness">
              {readiness.checks.map((c) => (
                <li key={c.check} data-testid={`check-${c.check}`}>
                  <span className={`chip ${c.ok ? "low" : "high"}`}>{c.ok ? "ok" : "open"}</span> {c.check}
                </li>
              ))}
            </ul>
            <p className="muted fs-12 m-6-0-0">PK-Sim dry run: {readiness.engine_dry_run}</p>
          </>
        )}
        <h3 className="m-14-0-4">Where values come from</h3>
        <p className="m-0 fs-13">The client&apos;s files and figures; PubChem, the FDA label and ChEMBL, read by code at the
          project&apos;s start; the literature agent; and the published OSP model of the drug. Every value not excluded flows
          in; where sources give several, one is kept by source and grade (the client&apos;s first, then the literature by
          grade) and the others stay listed for the review. Values are never averaged.</p>
        <p className="muted fs-12 m-6-0-0" data-testid="selection-rule">Source selection rules: {selectionRule}</p>
      </details>
    </>
  );
}
