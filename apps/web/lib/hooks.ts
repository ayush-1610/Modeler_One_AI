// How a client page reads and changes the project (phase 7d, rule B6). A page reads a route with `useResource` and
// changes state with `useMutation`. A change that succeeds refreshes the resources on the page and the server-rendered
// parts of it, the phase rail among them, so a page cannot show a status its own change made stale.

import {
  keepPreviousData, useMutation as useQueryMutation, useQueries, useQuery, useQueryClient, type QueryClient,
} from "@tanstack/react-query";
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
};

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
    refetchInterval: poll ? (q) => (q.state.data !== undefined && poll(q.state.data) ? interval : false) : false,
    placeholderData: keepPrevious ? keepPreviousData : undefined,
  });
  return { data: result.data ?? null, problem: result.error?.message ?? null };
}

// the reads of `useResources` go out a few at a time, so the page's own reads are not queued behind them
let reading = 0;
const queued: (() => void)[] = [];
async function fewAtATime<T>(limit: number, read: () => Promise<T>): Promise<T> {
  while (reading >= limit) await new Promise<void>((go) => queued.push(go));
  reading += 1;
  try {
    return await read();
  } finally {
    reading -= 1;
    queued.shift()?.();
  }
}

/** Typed reads of one route for each of several parameters (the cards of a list), cached under the key `useResource`
 *  gives each, so a page that shows one of them reads it once. `limit` reads at most that many at a time; `enabled`
 *  holds them back (until the page is idle); `staleTime` keeps an answer that long before a new one is read. `at`
 *  changes whenever an answer or a problem arrives. */
export function useResources<R extends RouteFor<"get">>(
  route: R, list: Params<R>[], options: { enabled?: boolean; limit?: number; staleTime?: number } = {},
): (Resource<Data<R, "get">> & { at: number })[] {
  const { enabled = true, limit = 2, staleTime = 0 } = options;
  const results = useQueries({
    queries: list.map((params) => ({
      queryKey: [route, params, {}],
      queryFn: () => fewAtATime(limit, async () => {
        const env = await get(route, params);
        if (env.errors?.length || env.data === null) throw new ApiProblem(env.errors?.[0]?.message ?? "no answer");
        return env.data;
      }),
      enabled, staleTime,
    })),
  });
  return results.map((r) => ({ data: (r.data as Data<R, "get"> | undefined) ?? null, problem: r.error?.message ?? null,
                               at: Math.max(r.dataUpdatedAt, r.errorUpdatedAt) }));
}

/** Read a route once, through the page's cache under the key `useResource` gives it: the cached answer while it is
 *  younger than `staleTime` and not marked stale, else a new read (a check that must see what the server holds now,
 *  before a decision is sent). Throws the API's reason when it refuses. */
export function fetchResource<R extends RouteFor<"get">>(client: QueryClient, route: R, params: Params<R>, staleTime = 0): Promise<Data<R, "get">> {
  return client.fetchQuery({
    queryKey: [route, params, {}],
    queryFn: async () => {
      const env = await get(route, params);
      if (env.errors?.length || env.data === null) throw new ApiProblem(env.errors?.[0]?.message ?? "no answer");
      return env.data;
    },
    staleTime,
  });
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
