"use client";

// The one list of work for the Inputs page (plan 2026-11-14 §2 rule 1, slice 2): lib/inputsWork.ts built from the reads
// the page already makes, under the same keys (/inputs, /client-review, /delivery, /client-data), so it adds no request
// and no polling of its own: whichever read changes, every count changes with it. What holds up a subject signed on the
// delivery is on its card (/delivery/subjects/{type}/{subject}, 25-120 KB each): those cards are read once the page is
// idle, two at a time, under the key the open card uses, so a card shown in Client files is read once (the design text's
// "lazy subject cards"). Until a card is read its row says it is being checked.

import { useEffect, useMemo, useState } from "react";

import { useResource, useResources } from "@/lib/hooks";
import { buildWork, type CardLike, type InputsLike, type WorkModel } from "@/lib/inputsWork";

const CARD = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;

export type InputsWork = {
  model: WorkModel;
  /** every read the model is built from has answered (or failed): the page may choose its first area */
  loaded: boolean;
};

export function useInputsWork(projectId: string): InputsWork {
  const params = { project_id: projectId };
  const inputs = useResource("/api/v1/projects/{project_id}/inputs", params);
  const review = useResource("/api/v1/projects/{project_id}/client-review", params);
  const delivery = useResource("/api/v1/projects/{project_id}/delivery", params);
  const client = useResource("/api/v1/projects/{project_id}/client-data", params);
  const files = client.data?.files as { id: string; file: string; sha256: string }[] | undefined;

  // the delivery's subjects signed on the delivery and not signed yet (a blinded one is withheld: nothing to read)
  const rows = (delivery.data?.enabled ? delivery.data.subjects : [])
    .filter((r) => r.confirm_on === "delivery" && !r.blinded && !(r.confirmation?.current && r.confirmation.landed));
  const [idle, setIdle] = useState(false);
  const any = rows.length > 0;
  useEffect(() => {
    if (idle || !any) return;
    const w = window as Window & { requestIdleCallback?: (fn: () => void, o?: { timeout: number }) => number;
                                   cancelIdleCallback?: (handle: number) => void };
    if (w.requestIdleCallback && w.cancelIdleCallback) {
      const handle = w.requestIdleCallback(() => setIdle(true), { timeout: 1500 });
      return () => w.cancelIdleCallback!(handle);
    }
    const timer = window.setTimeout(() => setIdle(true), 200);
    return () => window.clearTimeout(timer);
  }, [idle, any]);
  const read = useResources(CARD, rows.map((r) => ({ project_id: projectId, type: r.subject_type, subject: r.subject })),
                            { enabled: idle, limit: 2, staleTime: 60_000 });
  // a card read is its subject's entry; one that failed is null (its row says so); one not read yet is absent
  const signature = read.map((q) => q.at).join("|");
  const cards = useMemo(() => {
    const out: Record<string, CardLike | null> = {};
    rows.forEach((r, i) => {
      const q = read[i];
      if (q?.data) out[`${r.subject_type}/${r.subject}`] = q.data as unknown as CardLike;
      else if (q?.problem) out[`${r.subject_type}/${r.subject}`] = null;
    });
    return out;
  }, [signature, rows.map((r) => r.subject).join("|")]); // eslint-disable-line react-hooks/exhaustive-deps

  const model = useMemo(() => buildWork({
    inputs: inputs.data as unknown as InputsLike | null, review: review.data, delivery: delivery.data, files: files ?? [], cards,
  }), [inputs.data, review.data, delivery.data, files, cards]);
  const answered = (r: { data: unknown; problem: string | null }) => r.data !== null || r.problem !== null;
  return { model, loaded: answered(inputs) && answered(review) && answered(delivery) };
}
