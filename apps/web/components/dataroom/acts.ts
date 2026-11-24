"use client";

// What the modeler changes in the Data room, each through its typed route (lib/api.ts). Every change answers the room
// as it now is, which is written into the page's cache (`After.write`), so nothing is read again for it; the "Send to
// the model" plan is read again, since any change may unblock it.

import { createContext, useContext } from "react";

import { send, type Schema } from "@/lib/api";
import type { Room } from "@/lib/dataroom";
import { put, useMutation, type After } from "@/lib/hooks";

export const ROOM = "/api/v1/projects/{project_id}/dataroom" as const;
export const RUN = "/api/v1/projects/{project_id}/dataroom/run" as const;
export const RESUME = "/api/v1/projects/{project_id}/dataroom/run:resume" as const;
export const ESTIMATE = "/api/v1/projects/{project_id}/dataroom/run/estimate" as const;
export const UPLOADS = "/api/v1/projects/{project_id}/dataroom/uploads" as const;
export const PUBLICATION = "/api/v1/projects/{project_id}/dataroom/publication" as const;

type Outcome = { problem: string | null };

export type Acts = {
  busy: boolean;
  question: (card: Schema<"QuestionCard">, confirmed: boolean, reason?: string) => Promise<Outcome>;
  decide: (id: string, chosen: string, reason: string) => Promise<Outcome>;
  enter: (key: string, label: string, value: number | string, unit: string, reason: string) => Promise<Outcome>;
  request: (id: string, change: { wording?: string; status?: Schema<"DataRequest">["status"] }) => Promise<Outcome>;
};

export function useActs(projectId: string): Acts {
  const { run, busy } = useMutation();
  const params = { project_id: projectId };
  const after: After<Room> = { write: (data, client) => put(client, [ROOM, params, {}], data), reads: [PUBLICATION] };
  return {
    busy,
    question: (card, confirmed, reason = "") =>
      run(() => send("put", "/api/v1/projects/{project_id}/dataroom/question", params, { card, confirmed, reason }), after),
    decide: (id, chosen, reason) =>
      run(() => send("post", "/api/v1/projects/{project_id}/dataroom/decisions/{decision_id}", { ...params, decision_id: id },
                     { chosen, reason }), after),
    enter: (key, label, value, unit, reason) =>
      run(() => send("post", "/api/v1/projects/{project_id}/dataroom/entered", params, { key, label, value, unit, reason }), after),
    request: (id, change) =>
      run(() => send("patch", "/api/v1/projects/{project_id}/dataroom/requests/{request_id}", { ...params, request_id: id },
                     { wording: change.wording ?? null, status: change.status ?? null }), after),
  };
}

export const ActsContext = createContext<Acts | null>(null);
/** The room's changes (none on paper: the report changes nothing). */
export const useRoomActs = () => useContext(ActsContext);
