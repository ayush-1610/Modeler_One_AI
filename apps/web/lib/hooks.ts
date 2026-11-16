// How a client page reads and changes the project (phase 7d, rule B6). A page reads a route with `useResource` and
// changes state with `useMutation`. A change says what it made stale (`After`): its answer written into the page's
// cache, the reads it changed read again, and the server-rendered parts of the page (the step bar) drawn again where
// they show what changed, so a page cannot show a status its own change made stale, and a change costs the change and
// what it changed, not every read on the page (plan 2026-11-14 §2.1 "fewer refetches"; final review OWN-7, CODE-4).

import {
  keepPreviousData, useMutation as useQueryMutation, useQueries, useQuery, useQueryClient, type QueryClient, type QueryKey,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, createElement, useCallback, useContext, useState, type ReactNode } from "react";

import { get, type Data, type Envelope, type Params, type RouteFor } from "@/lib/api";

/** What the API said when it refused a call, or why it could not be reached. */
class ApiProblem extends Error {}

export type Resource<T> = {
  /** The answer (the page's view of it, when `select` is given); null while loading or when it failed. */
  data: T | null;
  /** Why it could not be read; the page shows it instead of sample data. */
  problem: string | null;
};

// --- a page whose reads are held for the visit --------------------------------------------------------------------------

// A page of many areas (Inputs) holds what it has read for the visit: an area shown again, or a second part of the page
// that reads the same route, is drawn from the cache with no request. What was read before the visit (an earlier visit
// of the page) is read again once, when first shown; a read a change marks stale is read again as always.
const Visit = createContext<number | null>(null);

/** Hold the reads of the parts inside for this visit of the page (from when it was first drawn). */
export function HeldReads({ children }: { children: ReactNode }) {
  const [from] = useState(() => Date.now());
  return createElement(Visit.Provider, { value: from }, children);
}

/** A cached answer, as far as its freshness goes. */
type Answered = { state: { dataUpdatedAt: number } };

/** How long an answer stays fresh: inside `HeldReads`, until a change marks it stale if it was read in this visit;
 *  elsewhere `otherwise` (0: every part that is drawn reads it again). */
function useFreshness(otherwise = 0): number | ((query: Answered) => number) {
  const from = useContext(Visit);
  return from === null ? otherwise : (query: Answered) => (query.state.dataUpdatedAt >= from ? Infinity : 0);
}

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
  const staleTime = useFreshness();
  const result = useQuery<Data<R, "get">, ApiProblem, T>({
    queryKey: [route, params, query ?? {}],
    queryFn: async () => {
      const env = await get(route, params, query);
      if (env.errors?.length || env.data === null) throw new ApiProblem(env.errors?.[0]?.message ?? "no answer");
      return env.data;
    },
    select,
    enabled,
    staleTime,
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
 *  holds them back (until the page is idle); `staleTime` keeps an answer that long before a new one is read (inside
 *  `HeldReads`, for the visit). `at` changes whenever an answer or a problem arrives. */
export function useResources<R extends RouteFor<"get">>(
  route: R, list: Params<R>[], options: { enabled?: boolean; limit?: number; staleTime?: number } = {},
): (Resource<Data<R, "get">> & { at: number })[] {
  const { enabled = true, limit = 2, staleTime = 0 } = options;
  const fresh = useFreshness(staleTime);
  const results = useQueries({
    queries: list.map((params) => ({
      queryKey: [route, params, {}],
      queryFn: () => fewAtATime(limit, async () => {
        const env = await get(route, params);
        if (env.errors?.length || env.data === null) throw new ApiProblem(env.errors?.[0]?.message ?? "no answer");
        return env.data;
      }),
      enabled, staleTime: fresh,
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

// --- what a change made stale -------------------------------------------------------------------------------------------

/** A read of the page, by its route: every answer of the route (whatever its parameters) is meant. */
export type Read = RouteFor<"get">;

/** Write an answer under its key, what the server holds now. A read of the same key still on its way (sent before the
 *  change: a poll, the page's idle reads, the end of a reading) is called off first: answered after the change, it
 *  would put back what the page showed before it (final review round 4: an approval's answer was overwritten by a read
 *  of the layout sent just before it, and the page stopped following the reading it had started). */
export function put<T>(client: QueryClient, key: QueryKey, data: T): void {
  void client.cancelQueries({ queryKey: key, exact: true });
  client.setQueryData(key, data);
}

/** Mark every answer of `routes` stale: those shown are read again (once each), the others when next shown. */
export function readAgain(client: QueryClient, routes: readonly Read[]): Promise<void> {
  if (!routes.length) return Promise.resolve();
  const named = new Set<string>(routes);
  return client.invalidateQueries({ predicate: (q) => named.has(q.queryKey[0] as string) });
}

/** What a change made stale, said where the change is made. `write`: the answer, written into the page's cache (what
 *  the server holds now, so nothing is read for it). `reads`: the reads it changed, by route; `keys`: one answer of a
 *  route it changed (one card of many). `server`: the parts of the page drawn on the server show what it changed (a page
 *  drawn on the server, a step bar the change moves), so they are drawn again. A dry run that changes nothing says `{}`. */
export type After<T = unknown> = {
  write?: (data: T, client: QueryClient) => void;
  reads?: readonly Read[];
  keys?: readonly QueryKey[];
  server?: boolean;
};

/** The outcome of a change: the answer's data, or the API's reason it refused. */
export type Outcome<T> = { data: T | null; problem: string | null };

type Change = { call: () => Promise<Envelope<unknown>>; after: After<never> };

/** Change state through the API. `run(() => send(...), after)` answers the outcome; when the change succeeds, what it
 *  made stale (`after`) is written and read again before `run` returns. */
export function useMutation() {
  const client = useQueryClient();
  const router = useRouter();
  const { mutateAsync, isPending } = useQueryMutation<unknown, ApiProblem, Change>({
    mutationFn: async ({ call }) => {
      const env = await call();
      if (env.errors?.length) throw new ApiProblem(env.errors[0].message);
      return env.data;
    },
    onSuccess: async (data, { after }) => {
      (after as After<unknown>).write?.(data, client);
      if (after.server) router.refresh();
      await Promise.all([readAgain(client, after.reads ?? []),
                         ...(after.keys ?? []).map((queryKey) => client.invalidateQueries({ queryKey, exact: true }))]);
    },
  });
  const run = useCallback(
    async <T>(call: () => Promise<Envelope<T>>, after: After<T>): Promise<Outcome<T>> => {
      try {
        return { data: (await mutateAsync({ call, after: after as After<never> })) as T | null, problem: null };
      } catch (err) {
        return { data: null, problem: err instanceof Error ? err.message : String(err) };
      }
    },
    [mutateAsync],
  );
  return { run, busy: isPending };
}
