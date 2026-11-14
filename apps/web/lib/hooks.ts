// How a client page reads and changes the project (phase 7d, rule B6). A page reads a route with `useResource` and
// changes state with `useMutation`. A change that succeeds refreshes the resources on the page and the server-rendered
// parts of it, the phase rail among them, so a page cannot show a status its own change made stale.

import { keepPreviousData, useMutation as useQueryMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { get, type Data, type Envelope, type Params, type RouteFor } from "@/lib/api";

/** What the API said when it refused a call, or why it could not be reached. */
class ApiProblem extends Error {}

export type Resource<T> = {
  /** The answer (the page's view of it, when `select` is given); null while loading or when it failed. */
  data: T | null;
  /** Why it could not be read; the page shows it instead of sample data. */
  problem: string | null;
  /** When the answer on screen was read (ms since the epoch); null before the first answer. */
  updatedAt: number | null;
  /** The last read failed although an earlier answer is still shown: that answer may be out of date. */
  stale: boolean;
};

/** The longest wait between reads of a polled resource while the API does not answer. */
const MAX_BACKOFF_MS = 30_000;

type ResourceOptions<D, T> = {
  query?: Record<string, string | undefined>;
  /** The page's view of the answer, e.g. `(d) => narrow<BriefView>(d)` where stored content is typed by the page. */
  select?: (data: D) => T;
  /** Read again every `interval` ms while this holds (an agent or extraction still running). */
  poll?: (data: D) => boolean;
  interval?: number;
  /** Read only when this holds (e.g. once a document is chosen). */
  enabled?: boolean;
  /** Keep showing the previous answer while the next one loads (paging through a document). */
  keepPrevious?: boolean;
};

/** A typed read of a route, cached for the page: `useResource("/api/v1/projects/{project_id}/brief", { project_id })`. */
export function useResource<R extends RouteFor<"get">, T = Data<R, "get">>(
  route: R, params: Params<R>, options: ResourceOptions<Data<R, "get">, T> = {},
): Resource<T> {
  const { query, select, poll, interval = 3000, enabled = true, keepPrevious = false } = options;
  const result = useQuery<Data<R, "get">, ApiProblem, T>({
    queryKey: [route, params, query ?? {}],
    queryFn: async () => {
      const env = await get(route, params, query);
      if (env.errors?.length || env.data === null) throw new ApiProblem(env.errors?.[0]?.message ?? "no answer");
      return env.data;
    },
    select,
    enabled,
    // a polled read that failed keeps trying, at a doubling interval up to 30 s, so a page (the decision pop-up, the
    // sidebar's liveness, a run's progress) recovers by itself once the API answers again; it never stops for good
    refetchInterval: poll ? (q) => {
      if (q.state.status === "error") return Math.min(MAX_BACKOFF_MS, interval * 2 ** Math.max(1, q.state.fetchFailureCount));
      return q.state.data !== undefined && poll(q.state.data) ? interval : false;
    } : false,
    placeholderData: keepPrevious ? keepPreviousData : undefined,
  });
  return {
    data: result.data ?? null,
    problem: result.error?.message ?? null,
    updatedAt: result.dataUpdatedAt || null,
    stale: result.isError && result.data !== undefined,
  };
}

/** Read the page's resources again, after a refusal that says the server moved on (a run already going elsewhere). */
export function useRefresh() {
  const client = useQueryClient();
  return useCallback(() => client.invalidateQueries(), [client]);
}

/** The outcome of a change: the answer's data, or the API's reason it refused. */
export type Outcome<T> = { data: T | null; problem: string | null };

type Change = { call: () => Promise<Envelope<unknown>>; refresh: boolean };

/** Change state through the API. `run(() => send(...))` answers the outcome; when the change succeeds, the page's
 *  resources are read again and its server-rendered parts (the phase rail) re-rendered before `run` returns, unless
 *  `{ refresh: false }` (a dry run that changes nothing). */
export function useMutation() {
  const client = useQueryClient();
  const router = useRouter();
  const { mutateAsync, isPending } = useQueryMutation<unknown, ApiProblem, Change>({
    mutationFn: async ({ call }) => {
      const env = await call();
      if (env.errors?.length) throw new ApiProblem(env.errors[0].message);
      return env.data;
    },
    onSuccess: async (_data, { refresh }) => {
      if (!refresh) return;
      router.refresh();
      await client.invalidateQueries();
    },
  });
  const run = useCallback(
    async <T>(call: () => Promise<Envelope<T>>, { refresh = true }: { refresh?: boolean } = {}): Promise<Outcome<T>> => {
      try {
        return { data: (await mutateAsync({ call, refresh })) as T | null, problem: null };
      } catch (err) {
        return { data: null, problem: err instanceof Error ? err.message : String(err) };
      }
    },
    [mutateAsync],
  );
  return { run, busy: isPending };
}
