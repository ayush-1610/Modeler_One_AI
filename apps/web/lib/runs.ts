// An agent run's times in words (Agent activity, the console redesign's slice 7), for the server and browser alike.

/** How long a run took ("3 min 20 s"); "running" until it finished. */
export function duration(started: string, finished: string | null | undefined): string {
  if (!finished) return "running";
  const s = Math.max(0, Math.round((Date.parse(finished) - Date.parse(started)) / 1000));
  return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;
}
