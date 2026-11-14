"use client";

// The one list of work for the Inputs page (plan 2026-11-14 §2 rule 1, slice 2): lib/inputsWork.ts built from the reads
// the page already makes, under the same keys (/inputs, /client-review, /delivery, /client-data), so it adds no request
// and no polling of its own: whichever read changes, every count changes with it.

import { useMemo } from "react";

import { useResource } from "@/lib/hooks";
import { buildWork, type InputsLike, type WorkModel } from "@/lib/inputsWork";

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
  const model = useMemo(() => buildWork({
    inputs: inputs.data as unknown as InputsLike | null, review: review.data, delivery: delivery.data, files: files ?? [],
  }), [inputs.data, review.data, delivery.data, files]);
  const answered = (r: { data: unknown; problem: string | null }) => r.data !== null || r.problem !== null;
  return { model, loaded: answered(inputs) && answered(review) && answered(delivery) };
}
