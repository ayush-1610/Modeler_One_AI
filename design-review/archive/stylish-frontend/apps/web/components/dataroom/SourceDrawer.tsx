"use client";

// The source viewer (plan 2026-11-21 v2 §10): a drawer along the right edge with the page as it was read and the value's
// place highlighted on it (a cell's box, or its line's), or the sheet's or the body's numbered lines with the line and
// the cell marked; the file's name and the place above it. The page is the reading copy the API draws again from the
// file's bytes, so a box (points, top-left origin) falls where it was read.

import { useEffect, useMemo, useRef, useState } from "react";

import { Dialog } from "@/components/kit/Dialog";
import { apiFile, path } from "@/lib/api";
import { baseName, placeOf, type Chip } from "@/lib/dataroom";
import { useResource } from "@/lib/hooks";

const FILE = "/api/v1/projects/{project_id}/dataroom/files/{sha256}" as const;
const PAGE = "/api/v1/projects/{project_id}/dataroom/files/{sha256}/pages/{page}.png" as const;
const PART = "/api/v1/projects/{project_id}/dataroom/files/{sha256}/parts/{part}" as const;

type Box = [number, number, number, number];

function union(boxes: (Box | null | undefined)[]): Box | null {
  const got = boxes.filter((b): b is Box => Boolean(b));
  if (!got.length) return null;
  return [Math.min(...got.map((b) => b[0])), Math.min(...got.map((b) => b[1])), Math.max(...got.map((b) => b[2])),
          Math.max(...got.map((b) => b[3]))];
}

function PageView({ projectId, chip, page }: { projectId: string; chip: Chip; page: number }) {
  const info = useResource(FILE, { project_id: projectId, sha256: chip.sha256 });
  // a quote's chip has no box: its line's cells give it (the page's numbered lines, as the agents read them)
  const lines = useResource(PART, { project_id: projectId, sha256: chip.sha256, part: chip.part }, { enabled: !chip.box });
  const [src, setSrc] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    let gone = false;
    setSrc(null);
    void apiFile(path(PAGE, { project_id: projectId, sha256: chip.sha256, page: String(page) }, { scale: "2" })).then((got) => {
      if (gone) return;
      if (got.file) { url = URL.createObjectURL(got.file); setSrc(url); } else setProblem(got.problem);
    });
    return () => { gone = true; if (url) URL.revokeObjectURL(url); };
  }, [projectId, chip.sha256, page]);
  const size = info.data?.pages.find((p) => p.page === page);
  const box: Box | null = (chip.box as Box | null) ?? union(lines.data?.lines.find((l) => l.number === chip.line)?.cells
    .filter((c, i) => chip.cell === null || chip.cell === undefined || i + 1 === chip.cell).map((c) => c.box as Box | null) ?? []);
  const mark = useRef<HTMLDivElement>(null);
  useEffect(() => { mark.current?.scrollIntoView({ block: "center" }); }, [src, box?.[1]]);
  if (problem) return <div className="banner err">{problem}</div>;
  return (
    <div className="dr-page" data-testid="source-page">
      {src ? <img src={src} alt={`Page ${page} of ${baseName(chip.file)}`} /> : <p className="muted">Drawing the page…</p>}
      {src && size && box && (
        <div ref={mark} className="dr-page-mark" data-testid="source-highlight" style={{
          left: `${(box[0] / size.width) * 100 - 0.6}%`, top: `${(box[1] / size.height) * 100 - 0.4}%`,
          width: `${((box[2] - box[0]) / size.width) * 100 + 1.2}%`, height: `${((box[3] - box[1]) / size.height) * 100 + 0.8}%` }} />
      )}
    </div>
  );
}

function LinesView({ projectId, chip }: { projectId: string; chip: Chip }) {
  const part = useResource(PART, { project_id: projectId, sha256: chip.sha256, part: chip.part });
  const mark = useRef<HTMLTableRowElement>(null);
  useEffect(() => { mark.current?.scrollIntoView({ block: "center" }); }, [part.data]);
  if (part.problem) return <div className="banner err">{part.problem}</div>;
  if (!part.data) return <p className="muted">Reading the file…</p>;
  const lo = Math.max(1, chip.line - 40), hi = chip.line + 40;
  const shown = part.data.lines.filter((l) => l.number >= lo && l.number <= hi);
  return (
    <div className="dr-lines" role="region" aria-label="The file's lines" tabIndex={0} data-testid="source-lines">
      <table>
        <tbody>
          {shown.map((l) => (
            <tr key={l.number} ref={l.number === chip.line ? mark : undefined} className={l.number === chip.line ? "on" : undefined}>
              <th scope="row">{l.number}</th>
              {l.cells.map((c, i) => {
                const on = l.number === chip.line && (chip.cell === null || chip.cell === undefined || chip.cell === i + 1);
                return <td key={i} className={on ? "cell-on" : undefined} data-testid={on ? "source-cell" : undefined}>{c.text}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SourceDrawer({ projectId, chip, onClose }: { projectId: string; chip: Chip; onClose: () => void }) {
  const page = useMemo(() => { const m = /^p(\d+)$/.exec(chip.part); return m ? Number(m[1]) : null; }, [chip.part]);
  const sheet = chip.part.startsWith("sheet:") ? chip.part.slice(6) : null;
  return (
    <Dialog title={baseName(chip.file)} size="drawer" onClose={onClose} dismiss testId="source-drawer">
      <p className="dr-drawer-where">
        {sheet ? `Sheet ${sheet} · ` : ""}{placeOf(chip)}
        <span className="dr-drawer-path">{chip.file}</span>
      </p>
      {/* a quote's words (a cell's text is highlighted in its place below) */}
      {chip.text && (chip.cell === null || chip.cell === undefined) && <blockquote className="dr-drawer-quote">{chip.text}</blockquote>}
      <div className="dr-drawer-body">
        {page !== null ? <PageView projectId={projectId} chip={chip} page={page} /> : <LinesView projectId={projectId} chip={chip} />}
      </div>
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose} data-testid="source-drawer-close">Close</button>
      </div>
    </Dialog>
  );
}
