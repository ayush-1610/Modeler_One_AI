// How a client page reads and changes the project (phase 7d, rule B6). A page reads a route with `useResource` and
// changes state with `useMutation`. A change says what it made stale (`After`): its answer written into the page's
// cache, the reads it changed read again, and the server-rendered parts of the page (the step bar) drawn again where
// they show what changed, so a page cannot show a status its own change made stale, and a change costs the change and
// what it changed, not every read on the page (plan 2026-11-14 §2.1 "fewer refetches"; final review OWN-7, CODE-4).

import {
  hashKey, keepPreviousData, useMutation as useQueryMutation, useQueries, useQuery, useQueryClient, type QueryClient, type QueryKey,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, createElement, useCallback, useContext, useState, type ReactNode } from "react";

import { get, type Data, type Envelope, type Params, type RouteFor } from "@/lib/api";
import { afterAnswer, type ReadOnItsWay } from "@/lib/freshness";

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

// --- when each read was asked for ---------------------------------------------------------------------------------------

/** One clock for reads and decisions (monotonic, so a clock change never orders them wrongly). */
export const now = () => performance.now();

// One moment per task (final review round 6): what a change does in one go (its answer written, the reads it marks stale
// sent, one after the other in the same task) is of one moment, so a rule that later asks whether an answer was read
// since then counts every one of them, whichever went out first.
let task: number | null = null;
/** The moment of the task the page is in: the time of its first `moment()`, the same for the rest of the task. */
export function moment(): number {
  if (task === null) {
    task = now();
    queueMicrotask(() => { task = null; });
  }
  return task;
}

// The latest read of each answer (by its key's hash): when it was asked for and when its request went out, with a token
// that tells it from a read that replaced it, and the moment it was asked in. Written by the reads of this file
// (`useResource`, `useResources`, `fetchResource`), the only reads of the page's cache. `written`: the moment a change's
// answer was written under the key (`put`): the server's answer after the change, so it holds the change.
const reads = new Map<string, ReadOnItsWay & { token: object; at: number }>();
const written = new Map<string, number>();

/** Mark a read of `key` asked for now; `out()` when its request goes out (a read of `useResources` may wait its turn). */
function asking(key: QueryKey): { out: () => void } {
  const hash = hashKey(key);
  const token = {};
  reads.set(hash, { asked: now(), sent: null, token, at: moment() });
  return { out: () => { const r = reads.get(hash); if (r?.token === token) r.sent = now(); } };
}

/** The moment the answer under `hash` was last read in (asked for) or written by a change (-1: never by this page). */
const heldAt = (hash: string) => Math.max(reads.get(hash)?.at ?? -1, written.get(hash) ?? -1);

/** The moment the answer under `key` was last read in or written by a change (null: never by this page): what a rule
 *  that follows a change this answer shows counts as current from (`followBlinding`, components/delivery/writes.ts). */
export function readMoment(key: QueryKey): number | null {
  const at = heldAt(hashKey(key));
  return at < 0 ? null : at;
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
    queryFn: async ({ queryKey }) => {
      asking(queryKey).out();
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
      queryFn: ({ queryKey }: { queryKey: QueryKey }) => {
        const read = asking(queryKey);
        return fewAtATime(limit, async () => {
          read.out();
          const env = await get(route, params);
          if (env.errors?.length || env.data === null) throw new ApiProblem(env.errors?.[0]?.message ?? "no answer");
          return env.data;
        });
      },
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
    queryFn: async ({ queryKey }) => {
      asking(queryKey).out();
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

// When each decision was sent, kept with its answer (the object the API answered with, as `run` returns it), and the
// decision whose answer its `After` is writing now: what `put` compares a read on its way with.
const decidedAt = new WeakMap<object, number>();
let writing: number | null = null;

/** Write an answer under its key, what the server holds now. A read of the same key still on its way is settled by
 *  when it was asked for (`afterAnswer`, lib/freshness.ts): one asked for before the decision was sent (a poll, the
 *  page's idle reads, the end of a reading) is called off, so it cannot put back what the page showed before (final
 *  review round 4: an approval's answer was overwritten by a read of the layout sent just before it, and the page
 *  stopped following the reading it had started); one asked for since and not sent yet goes out after the answer and is
 *  left to land; one sent since may have been answered before the decision or after it, so it is called off and the
 *  answer read once more (final review round 5: round 4 called it off and kept the decision's answer, which could be the
 *  older). `sent`: when the decision was sent, where the answer's own record of it is not at hand. */
export function put<T>(client: QueryClient, key: QueryKey, data: T, sent?: number): void {
  const query = client.getQueryCache().find({ queryKey: key, exact: true });
  // a read on its way that this file did not ask for (none, today) is taken as asked for before the decision
  const read = query && query.state.fetchStatus !== "idle" ? reads.get(query.queryHash) ?? { asked: -Infinity, sent: -Infinity } : null;
  const decided = sent ?? (typeof data === "object" && data !== null ? decidedAt.get(data) : undefined) ?? writing;
  const step = afterAnswer(read, decided ?? null);
  if (step === "cancel" || step === "again") void client.cancelQueries({ queryKey: key, exact: true });
  client.setQueryData(key, data);
  written.set(query?.queryHash ?? hashKey(key), moment());
  if (step === "again") void client.invalidateQueries({ queryKey: key, exact: true });
}

/** Mark every answer of `routes` stale: those shown are read again (once each), the others when next shown. `since`
 *  (a `moment()` from when a change was answered): an answer read in that moment or since, on its way since, or written
 *  by a change since, already holds the change, so it is not read again (one that failed is). `projectId`: only that
 *  project's answers. */
export function readAgain(client: QueryClient, routes: readonly Read[], since?: number, projectId?: string): Promise<void> {
  if (!routes.length) return Promise.resolve();
  const named = new Set<string>(routes);
  const current = (hash: string, failed: boolean) => since !== undefined && !failed && heldAt(hash) >= since;
  const mine = (key: QueryKey) => projectId === undefined || (key[1] as { project_id?: string } | undefined)?.project_id === projectId;
  return client.invalidateQueries({ predicate: (q) => named.has(q.queryKey[0] as string) && mine(q.queryKey)
                                                    && !current(q.queryHash, q.state.status === "error") });
}

/** What a change made stale, said where the change is made. `write`: the answer, written into the page's cache (what
 *  the server holds now, so nothing is read for it). `reads`: the reads it changed, by route; `keys`: one answer of a
 *  route it changed (one card of many). `server`: the parts of the page drawn on the server show what it changed (a page
 *  drawn on the server, a step bar the change moves), so they are drawn again. A dry run that changes nothing says `{}`. */
export type After<T = unknown> = {
  /** may answer a promise: what it reads after the answer is written (the delivery page, then the cards whose rows it
   *  changed), waited for as `reads` are */
  write?: (data: T, client: QueryClient) => void | Promise<void>;
  reads?: readonly Read[];
  keys?: readonly QueryKey[];
  server?: boolean;
};

/** The outcome of a change: the answer's data, or the API's reason it refused. */
export type Outcome<T> = { data: T | null; problem: string | null };

type Change = { call: () => Promise<Envelope<unknown>>; after: After<never>; sent?: number };

/** Change state through the API. `run(() => send(...), after)` answers the outcome; when the change succeeds, what it
 *  made stale (`after`) is written and read again before `run` returns. When the change was sent is kept with its
 *  answer, so a read of the same answer still on its way is told apart from it (`put`). */
export function useMutation() {
  const client = useQueryClient();
  const router = useRouter();
  const { mutateAsync, isPending } = useQueryMutation<unknown, ApiProblem, Change>({
    mutationFn: async (change) => {
      change.sent = now();
      const env = await change.call();
      if (env.errors?.length) throw new ApiProblem(env.errors[0].message);
      if (typeof env.data === "object" && env.data !== null) decidedAt.set(env.data, change.sent);
      return env.data;
    },
    onSuccess: async (data, { after, sent }) => {
      let follows: void | Promise<void>;
      writing = sent ?? null;
      try {
        follows = (after as After<unknown>).write?.(data, client);
      } finally {
        writing = null;
      }
      if (after.server) router.refresh();
      await Promise.all([follows, readAgain(client, after.reads ?? []),
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
