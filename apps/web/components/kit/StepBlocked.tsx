"use client";

// A step that cannot open yet says why and where to go (the 2026-11-11 audit, item 2). It reads the project's steps and
// lists what the earlier step still waits on, each in words, with one way forward, instead of an error on an empty page.

import Link from "next/link";
import type { ReactNode } from "react";

import { useResource } from "@/lib/hooks";
import { STEP_ROUTES, type StepId } from "@/lib/pipeline";
import { plain } from "@/lib/plain";

const ORDER: StepId[] = ["start", "inputs", "review", "run"];

export function StepBlocked({ projectId, step, title, detail, fallback, testId }: {
  projectId: string;
  /** The step this page belongs to; the first earlier step that is not done is the one to finish. */
  step: StepId;
  title: string;
  /** What the API said, kept as the record of why (shown small, under the list). */
  detail?: string | null;
  /** What is said when every earlier step is done but this one still cannot start (what it lacks, in words). */
  fallback?: ReactNode;
  testId?: string;
}) {
  const steps = useResource("/api/v1/projects/{project_id}/steps", { project_id: projectId }, { select: (d) => d.steps.map((s) => ({ ...s, reasons: s.reasons.map(plain) })) });
  const before = (steps.data ?? []).filter((s) => ORDER.indexOf(s.step) < ORDER.indexOf(step));
  const waiting = before.find((s) => s.state !== "done") ?? null;
  return (
    <section className="card step-blocked" data-testid={testId ?? "step-blocked"}>
      <h2>{title}</h2>
      {waiting ? (
        <>
          <p className="muted">{waiting.label} is not finished.{" "}
            {waiting.reasons.length ? `${waiting.reasons.length} ${waiting.reasons.length === 1 ? "thing still needs" : "things still need"} you there:`
              : "It has not been worked on yet."}</p>
          {waiting.reasons.length > 0 && <ul>{waiting.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
          <Link className="btn primary" href={STEP_ROUTES[waiting.step](projectId)} data-testid="step-blocked-go">
            Go to {waiting.label}
          </Link>
        </>
      ) : steps.data ? (
        fallback ?? <p className="muted">The earlier steps are done; this step is being prepared.</p>
      ) : (
        <p className="muted">Reading where the project stands…</p>
      )}
      {detail && <p className="step-blocked-detail">{plain(detail)}</p>}
    </section>
  );
}
