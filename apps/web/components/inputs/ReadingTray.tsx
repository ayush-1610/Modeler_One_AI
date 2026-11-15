"use client";

// The AI reading line (plan 2026-11-10, R3; plan 2026-11-14 slices 1–2): how far the reading agent is with the client's
// files, in one line in the Client files area, with the documents not yet read for data and the figures worth
// digitizing. Each file's own reading (what was found, why one failed, "Read again") is on that file's row in the files
// table (`AiReading`), the only list of files on Inputs: the tray keeps no list of its own. With AI off the line says
// so, and says the files were read without AI where the delivery read them.

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

const useQueue = (projectId: string) => useResource("/api/v1/projects/{project_id}/reading-queue", { project_id: projectId },
  { poll: (d) => d.agents.enabled && (d.counts.queued > 0 || d.counts.reading > 0), interval: 4000 });

/** Each file read brings data onto the cards: the page is read again when a reading finishes while it is open (the
 *  newest finish time, which the queue's pruning cannot cap); not on the first answer. Used by the Inputs workspace, so
 *  it holds on every area, not only while the Client files area shows the tray (plan 2026-11-14 slice 1). */
export function useReadingRefresh(projectId: string) {
  const data = useQueue(projectId).data;
  const refresh = useRefresh();
  const seen = useRef<string | null>(null);
  const newest = data ? data.items.reduce((m, i) => (i.finished_at && i.finished_at > m ? i.finished_at : m), "") : null;
  useEffect(() => {
    if (newest === null) return;
    if (seen.current !== null && newest !== seen.current) void refresh();
    seen.current = newest;
  }, [newest]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** One file's reading by the agent, under its row in the Client files table: its state, what it found, why it failed,
 *  and "Read again". Shown while AI reading is on, or once the agent finished with the file. */
export function AiReading({ projectId, sid }: { projectId: string; sid: string }) {
  const data = useQueue(projectId).data;
  const mutation = useMutation();
  const [problem, setProblem] = useState<string | null>(null);
  const item = data ? [...data.items].reverse().find((i) => i.sid === sid) : undefined;
  if (!data || !item || (!data.agents.enabled && item.state !== "done" && item.state !== "failed")) return null;

  async function again(id: string) {
    const { problem: failed } = await mutation.run(() => send("post", "/api/v1/projects/{project_id}/reading-queue/{item_id}:again",
                                                              { project_id: projectId, item_id: id }));
    setProblem(failed);   // on success the page's resources are read again
  }
  return (
    <div className="file-ai-reading" data-testid={`reading-item-${item.file}`}>
      <strong>AI reading</strong>
      <span className={`chip ${STATE_TONE[item.state]}`}>{STATE_LABEL[item.state]}</span>
      <span className="muted">
        {item.task === "read" ? "asked by a person" : item.task === "map" ? "read by code; laid out with the others" : "on arrival"}
        {item.sheets.length ? ` · ${item.sheets.join(", ")}` : ""}
        {item.state === "done" && ` · ${foundText(item.found)}`}
      </span>
      {data.mapped[item.sid] && (
        <span className="reading-tray-map" data-testid={`reading-map-${item.file}`}
              title="What the delivery found this file is about, each value quoted from it">{data.mapped[item.sid]}</span>
      )}
      {item.state === "failed" && <span className="reading-tray-why">{item.note || "failed"}</span>}
      {(item.state === "failed" || item.state === "done") && (
        <button type="button" className="btn small" disabled={mutation.busy} onClick={() => void again(item.id)}
                aria-label={`Read ${item.file} again with AI`} data-testid={`read-again-${item.file}`}>Read again</button>
      )}
      {problem && <span className="reading-tray-problem" role="alert">{problem}</span>}
    </div>
  );
}

/** The one line of AI reading in Client files. `readWithoutAi`: the files the delivery read by code, said in place of
 *  "waiting" while AI reading is off (so no file is called waiting and read at once: the 2026-11-14 audit). */
export function ReadingTray({ projectId, readWithoutAi = 0 }: { projectId: string; readWithoutAi?: number }) {
  const tray = useQueue(projectId);
  const mutation = useMutation();
  const [problem, setProblem] = useState<string | null>(null);
  const data = tray.data;

  if (!data) return null;
  const { counts, agents } = data;
  const backlog = data.unread_documents;
  const waiting = counts.queued + counts.reading;

  async function readLibrary() {
    const { data: read, problem: failed } = await mutation.run(() => send("post",
      "/api/v1/projects/{project_id}/documents:read-for-data", { project_id: projectId }));
    setProblem(failed ?? (read?.not_read.length ? `Not read: ${read.not_read.join("; ")}` : null));
  }

  const line = !data.items.length ? "no file queued for AI reading yet"
    : !agents.enabled && readWithoutAi ? `${plural(readWithoutAi, "file")} read without AI · AI reading is off`
      : trayLine(counts);
  return (
    <section className={`reading-tray${counts.failed ? " has-failed" : ""}`} data-testid="reading-tray">
      <div className="reading-tray-head">
        <strong>AI reading</strong>
        <span className="muted" data-testid="reading-tray-counts" role="status" aria-live="polite">{line}</span>
        <span className="chip neutral" data-testid="reading-tray-agent" title={agents.problem ?? undefined}>
          {agents.enabled ? `AI on${agents.model ? ` · ${agents.model}` : ""}` : "AI off"}
        </span>
      </div>
      {!agents.enabled && waiting > 0 && !readWithoutAi && (
        <p className="reading-tray-off" data-testid="reading-tray-off" title={agents.problem ?? undefined}>
          AI reading is off on this server: {plural(waiting, "file")} {waiting === 1 ? "waits" : "wait"} for it. Meanwhile, check
          each sheet&apos;s reading in the table below; your administrator can turn AI reading on.
        </p>
      )}
      {backlog.length > 0 && (
        <div className="reading-tray-backlog" data-testid="reading-tray-backlog">
          <span>
            {backlog.length === 1 ? "1 document" : `${backlog.length} documents`} in the project&apos;s library{" "}
            {backlog.length === 1 ? "was" : "were"} added without being read for data (before reading for data existed,
            or with it unticked): <span className="muted">{backlog.slice(0, 4).join(", ")}{backlog.length > 4 ? ", …" : ""}</span>
          </span>
          <button type="button" className="btn small primary" disabled={mutation.busy} onClick={() => void readLibrary()}
                  data-testid="read-library">
            Read {backlog.length === 1 ? "it" : `all ${backlog.length}`} for data
          </button>
        </div>
      )}
      {problem && <p className="reading-tray-problem" role="alert">{problem}</p>}
      {data.figures.length > 0 && (
        <div className="reading-tray-figures" data-testid="figure-suggestions">
          <strong>Figures worth digitizing</strong>{" "}
          <span className="muted">(no table in the client&apos;s files holds their values)</span>
          <ul>
            {data.figures.map((f) => f.blinded ? (
              // its file holds a blinded study's values (D-15): what it shows, its caption and Digitize wait for the plan
              <li key={`${f.sid}-${f.n}`} data-testid={`figure-${f.file}-${f.page}`}>
                <span>{f.file}, {f.file.toLowerCase().endsWith(".pdf") ? "p." : "part"} {f.page}: a figure</span>
                <span className="delivery-withheld" data-testid={`figure-withheld-${f.file}-${f.page}`}> · withheld (blinded): its file holds
                  the values of a study blinded until the plan is signed, and it can be digitized then</span>
              </li>
            ) : (
              <li key={`${f.sid}-${f.n}`} data-testid={`figure-${f.file}-${f.page}`}>
                <span>
                  {/* a Word file has no pages: its text is read in parts, which are not Word's pages */}
                  {f.file}, {f.file.toLowerCase().endsWith(".pdf") ? "p." : "part"} {f.page}:{" "}
                  {f.kind === "concentration_time" ? `concentration-time profile of study ${f.study_id}`
                    : `dissolution profile of ${f.product}${f.ph.length ? ` at pH ${f.ph.join(", ")}` : ""}${f.medium ? ` in ${f.medium}` : ""}`}
                </span>
                <span className="muted"> · “{f.quote}”</span>
                {f.digitizable ? (
                  // a full load: the Studies tab opens with the digitizer on the figure's page
                  <a className="btn small" data-testid={`digitize-${f.file}-${f.page}`}
                     href={`/projects/${encodeURIComponent(projectId)}/inputs?tab=studies&digitize=${f.doc_sha256}&page=${f.page}&study=${encodeURIComponent(f.study_id)}#observed-datasets`}>
                    Digitize
                  </a>
                ) : f.kind === "dissolution" ? (
                  <span className="muted"> · the digitizer makes concentration-time profiles: enter its % dissolved in the
                    product&apos;s dissolution data</span>
                ) : (
                  <span className="muted"> · a Word file: save this figure as an image or a PDF, add it with Add data, then
                    digitize it</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** The status line of "Add data" once files are added: how far the agent is, and where to see each file. */
export function ReadingStatus({ projectId, onOpen }: { projectId: string; onOpen?: () => void }) {
  const data = useQueue(projectId).data;
  if (!data || data.items.length === 0) return null;
  const waiting = data.counts.queued + data.counts.reading;
  return (
    <p className="add-data-reading muted" data-testid="add-data-reading">
      {!data.agents.enabled && waiting > 0
        ? `The reading agent is off on this server: ${plural(waiting, "file")} ${waiting === 1 ? "waits" : "wait"} to be read.`
        : waiting > 0 ? `The agent is reading the client's files: ${trayLine(data.counts)}.`
          : `The agent has read the client's files: ${trayLine(data.counts)}.`}{" "}
      <Link href={`/projects/${encodeURIComponent(projectId)}/inputs?tab=files`} onClick={onOpen}>See each file on Inputs</Link>
    </p>
  );
}
