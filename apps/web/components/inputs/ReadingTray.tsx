"use client";

// The reading tray (plan 2026-11-10, R3): every client file the reading agent is to read, is reading or has read, with
// what was found and why one failed, on Inputs above the areas. A file that failed is read again from here. With agents
// off the tray says so: the files wait, and each is read with the forms on its tab meanwhile.

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { send } from "@/lib/api";
import { useMutation, useRefresh, useResource } from "@/lib/hooks";

const FOUND: [string, string][] = [
  ["datasets", "dataset"], ["facts", "study fact"], ["dissolution_rows", "dissolution row"], ["links", "study link"],
  ["sorted", "sheet sorted"], ["sheets_proposed", "sheet reading"], ["sheets_adopted", "sheet read"],
];
const STATE_LABEL = { queued: "waiting", reading: "reading", done: "read", failed: "failed" } as const;
const STATE_TONE = { queued: "neutral", reading: "medium", done: "low", failed: "high" } as const;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

type Found = Record<string, number>;

/** What a reading found, in words ("2 datasets, 3 study facts"); "nothing proposed" when it found nothing. */
export function foundText(found: Found): string {
  const parts = FOUND.filter(([key]) => found[key]).map(([key, word]) => plural(found[key], word));
  return parts.length ? parts.join(", ") : "nothing proposed";
}

/** The tray's counts in one line: "3 of 17 read · 1 reading · 13 waiting · 0 failed". */
export function trayLine(counts: Record<string, number>): string {
  const total = (counts.queued ?? 0) + (counts.reading ?? 0) + (counts.done ?? 0) + (counts.failed ?? 0);
  return [`${counts.done ?? 0} of ${total} read`, counts.reading ? `${counts.reading} reading` : "",
          counts.queued ? `${counts.queued} waiting` : "", counts.failed ? `${counts.failed} failed` : ""]
    .filter(Boolean).join(" · ");
}

export function ReadingTray({ projectId }: { projectId: string }) {
  const tray = useResource("/api/v1/projects/{project_id}/reading-queue", { project_id: projectId },
    { poll: (d) => d.agents.enabled && (d.counts.queued > 0 || d.counts.reading > 0), interval: 4000 });
  const mutation = useMutation();
  const refresh = useRefresh();
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const seen = useRef<string | null>(null);
  const data = tray.data;

  // each file read brings data onto the cards: the page is read again when a reading finishes while it is open (the
  // newest finish time, which the queue's pruning cannot cap); not on the first answer
  const newest = data ? data.items.reduce((m, i) => (i.finished_at && i.finished_at > m ? i.finished_at : m), "") : null;
  useEffect(() => {
    if (newest === null) return;
    if (seen.current !== null && newest !== seen.current) void refresh();
    seen.current = newest;
  }, [newest]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!data || data.items.length === 0) return null;
  const { counts, agents } = data;
  const waiting = counts.queued + counts.reading;
  // each file once, at its latest reading: what is being read and waits first, then what finished most recently
  const order = { reading: 0, queued: 1, failed: 2, done: 3 } as const;
  const latest = new Map(data.items.map((i) => [i.sid, i]));
  const items = [...latest.values()].reverse().sort((a, b) => order[a.state] - order[b.state]);

  async function again(id: string) {
    const { problem: failed } = await mutation.run(() => send("post", "/api/v1/projects/{project_id}/reading-queue/{item_id}:again",
                                                              { project_id: projectId, item_id: id }));
    setProblem(failed);   // on success the page's resources, the tray among them, are read again
  }

  return (
    <section className={`reading-tray${counts.failed ? " has-failed" : ""}`} data-testid="reading-tray">
      <div className="reading-tray-head">
        <strong>The client&apos;s files, read by the agent</strong>
        <span className="muted" data-testid="reading-tray-counts" role="status" aria-live="polite">{trayLine(counts)}</span>
        <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)}
                data-testid="reading-tray-toggle">
          {open ? "Hide the files" : "Show each file"}
        </button>
      </div>
      {!agents.enabled && waiting > 0 && (
        <p className="reading-tray-off" data-testid="reading-tray-off" title={agents.problem ?? undefined}>
          The reading agent is off on this server: {plural(waiting, "file")}{" "}
          {waiting === 1 ? "waits" : "wait"} and {waiting === 1 ? "is" : "are"} read once it is on. Meanwhile, read each
          sheet with its form in the area of its data, or ask your administrator to turn the agents on.
        </p>
      )}
      {problem && <p className="reading-tray-problem" role="alert">{problem}</p>}
      {open && (
        <ul className="reading-tray-list" data-testid="reading-tray-list">
          {items.map((item) => (
            <li key={item.id} data-testid={`reading-item-${item.file}`}>
              <span className={`chip ${STATE_TONE[item.state]}`}>{STATE_LABEL[item.state]}</span>
              <span className="reading-tray-file">{item.file}</span>
              <span className="muted">
                {item.task === "read" ? "a person's Read" : "on arrival"}
                {item.sheets.length ? ` · ${item.sheets.join(", ")}` : ""}
                {item.state === "done" && ` · ${foundText(item.found)}`}
              </span>
              {item.state === "failed" && <span className="reading-tray-why">{item.note || "failed"}</span>}
              {(item.state === "failed" || item.state === "done") && (
                <button type="button" className="btn small" disabled={mutation.busy} onClick={() => void again(item.id)}
                        aria-label={`Read ${item.file} again`} data-testid={`read-again-${item.file}`}>
                  Read again
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** The status line of "Add data" once files are added: how far the agent is, and where to see each file. */
export function ReadingStatus({ projectId, onOpen }: { projectId: string; onOpen?: () => void }) {
  const tray = useResource("/api/v1/projects/{project_id}/reading-queue", { project_id: projectId },
    { poll: (d) => d.agents.enabled && (d.counts.queued > 0 || d.counts.reading > 0), interval: 4000 });
  const data = tray.data;
  if (!data || data.items.length === 0) return null;
  const waiting = data.counts.queued + data.counts.reading;
  return (
    <p className="add-data-reading muted" data-testid="add-data-reading">
      {!data.agents.enabled && waiting > 0
        ? `The reading agent is off on this server: ${plural(waiting, "file")} ${waiting === 1 ? "waits" : "wait"} to be read.`
        : waiting > 0 ? `The agent is reading the client's files: ${trayLine(data.counts)}.`
          : `The agent has read the client's files: ${trayLine(data.counts)}.`}{" "}
      <Link href={`/projects/${encodeURIComponent(projectId)}/inputs`} onClick={onOpen}>See each file on Inputs</Link>
    </p>
  );
}
