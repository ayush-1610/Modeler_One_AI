"use client";

// A value's source, beside the value (contracts 2026-11-12 §8.10, §4.2): its table with the cell the value is anchored
// at and the cells of its time, unit and labels highlighted by role; for a PDF also the page, drawn with pdfjs, with
// the value's box over it (scaled by the page's size, as the digitizer draws its page); for prose the paragraph with
// the span marked. A region that holds a blinded study's values (D-15) comes with blank cells and no page: the page
// is not drawn, and the note says the values are withheld.

import { useEffect, useRef, useState } from "react";

import { BROWSER_TOKEN, path, type Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";

import { WITHHELD } from "./shared";

type Source = Schema<"DeliverySource">;
type Cell = Schema<"DeliverySourceCell">;

const SCALE = 1.5;          // the page is drawn at 1.5 px per point and shown at the width of its box
const ALL_ROWS = 30;        // a longer table shows its head and the rows around the highlighted cells
const AROUND = 4;

/** The role a highlighted cell is coloured by: the value, its time, its unit, or one of its labels. */
function tone(role: string | null): "value" | "time" | "unit" | "label" {
  const roles = (role ?? "").split(",").map((r) => r.trim());
  return roles.includes("value") ? "value" : roles.includes("time") ? "time" : roles.some((r) => r.includes("unit")) ? "unit" : "label";
}

const LEGEND: [ReturnType<typeof tone>, string][] = [["value", "the value"], ["time", "its time"], ["unit", "its unit"], ["label", "its labels"]];

function PdfPage({ projectId, source }: { projectId: string; source: Source }) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [drawn, setDrawn] = useState(false);
  const page = source.page as number;
  const [width, height] = source.page_size as number[];

  useEffect(() => {
    let live = true;
    setDrawn(false);
    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
        const url = path("/api/v1/projects/{project_id}/documents/{sha256}/raw", { project_id: projectId, sha256: source.sha256 });
        const pdf = await pdfjs.getDocument({ url, httpHeaders: { Authorization: `Bearer ${BROWSER_TOKEN}` } }).promise;
        const sheet = await pdf.getPage(Math.min(page, pdf.numPages));
        const viewport = sheet.getViewport({ scale: SCALE });
        // drawn off screen first, so a newer value's page never shows half of an older one
        const off = document.createElement("canvas");
        off.width = viewport.width;
        off.height = viewport.height;
        const ctx = off.getContext("2d");
        if (!ctx) return;
        await sheet.render({ canvasContext: ctx, viewport }).promise;
        if (!live || !canvas.current) return;
        canvas.current.width = off.width;
        canvas.current.height = off.height;
        canvas.current.getContext("2d")?.drawImage(off, 0, 0);
        setProblem(null);
        setDrawn(true);
      } catch (e) {
        if (live) setProblem(`The page could not be drawn: ${(e as Error).message}`);
      }
    })();
    return () => { live = false; };
  }, [projectId, source.sha256, page]);

  const box = source.box;
  return (
    <figure className="delivery-source-page" data-testid="source-page" data-drawn={drawn}>
      <div className="delivery-source-sheet">
        <canvas ref={canvas} aria-label={`${source.file}, page ${page}`} role="img" />
        {/* the value's place on the page: the box is in the page's own units, so it is placed by its share of the page */}
        {box && drawn && (
          <span className="delivery-source-box" data-testid="source-box" aria-hidden
                style={{ left: `${(box[0] / width) * 100}%`, top: `${(box[1] / height) * 100}%`,
                         width: `${((box[2] - box[0]) / width) * 100}%`, height: `${((box[3] - box[1]) / height) * 100}%` }} />
        )}
      </div>
      <figcaption className="muted">{source.file}, page {page}{box ? ": the value is in the box" : ""}</figcaption>
      {problem && <p className="delivery-problem" role="alert">{problem}</p>}
    </figure>
  );
}

function Grid({ source }: { source: Source }) {
  const scroller = useRef<HTMLDivElement | null>(null);
  // a wide or long table opens with the value's cell in view: the box scrolls inside itself, the page stays where it is
  useEffect(() => {
    const box = scroller.current, cell = box?.querySelector<HTMLElement>('[data-testid="source-cell-value"]');
    if (!box || !cell) return;
    box.scrollLeft = Math.max(0, cell.offsetLeft - (box.clientWidth - cell.offsetWidth) / 2);
    box.scrollTop = Math.max(0, cell.offsetTop - (box.clientHeight - cell.offsetHeight) / 2);
  }, [source]);
  const at = new Map(source.cells.map((c) => [`${c.row}:${c.column}`, c]));
  const context = (above: boolean) => source.cells.filter((c) => (above ? c.row < 1 : c.row > source.n_rows));
  const marked = new Set(source.cells.filter((c) => c.highlighted && c.row >= 1 && c.row <= source.n_rows).map((c) => c.row));
  const rows: number[] = [];
  for (let r = 1; r <= source.n_rows; r += 1) {
    const near = [...marked].some((m) => Math.abs(m - r) <= AROUND);
    if (source.n_rows <= ALL_ROWS || r <= 3 || near) rows.push(r);
  }
  const cellProps = (c: Cell | undefined) => (c?.highlighted
    ? { className: `hl ${tone(c.role)}`, title: `${c.role ?? "highlighted"}: ${c.text}`, "data-role": c.role ?? "", "data-highlighted": "true",
        "data-testid": tone(c.role) === "value" ? "source-cell-value" : `source-cell-${tone(c.role)}` }
    : c?.text ? { title: c.text } : {});
  const line = (c: Cell) => (
    <p key={c.locator} className="delivery-source-line"><span {...cellProps(c)}>{c.text || (source.blinded ? WITHHELD : "")}</span></p>
  );
  return (
    <>
      {context(true).map(line)}
      <div className="delivery-source-grid" ref={scroller} role="region" aria-label={`The table ${source.title || "of the value"}`} tabIndex={0}>
        <table>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r} className={i > 0 && rows[i - 1] !== r - 1 ? "gap" : undefined}>
                <th scope="row">{r}</th>
                {Array.from({ length: source.n_cols }, (_, k) => {
                  const c = at.get(`${r}:${k + 1}`);
                  return <td key={k} {...cellProps(c)}>{c?.text ?? ""}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length < source.n_rows && <p className="muted fs-12 m-0">{rows.length} of {source.n_rows} rows shown: the head and the rows around the highlighted cells.</p>}
      {context(false).map(line)}
    </>
  );
}

/** The source of one value: `valueId` is the ledger's id of the value. */
export function ValueSource({ projectId, valueId, onClose }: { projectId: string; valueId: string; onClose?: () => void }) {
  const read = useResource("/api/v1/projects/{project_id}/delivery/source", { project_id: projectId }, { query: { value: valueId } });
  const source = read.data;
  return (
    <aside className="delivery-source" data-testid={`delivery-source-${valueId}`} aria-label="The value's source">
      <div className="delivery-source-head">
        <strong>{source ? source.title || source.file : "The source"}</strong>
        {source && <span className="muted">{source.file}{source.page !== null ? `, page ${source.page}` : ""}</span>}
        {onClose && <button type="button" className="link-btn" onClick={onClose} data-testid={`delivery-source-close-${valueId}`}>Close the source</button>}
      </div>
      {read.problem && <p className="delivery-problem" role="alert">{read.problem}</p>}
      {!source && !read.problem && <p className="muted m-0">Reading the source…</p>}
      {source && (
        <>
          {source.blinded && (
            <p className="delivery-withheld" data-testid="source-withheld">
              {WITHHELD}: this place holds a blinded study&apos;s values, so its numbers are left blank and its page is
              not drawn until the MAP is signed.
            </p>
          )}
          <div className={source.page !== null && !source.blinded ? "delivery-source-body with-page" : "delivery-source-body"}>
            <div className="delivery-source-cells">
              {source.kind === "grid" ? <Grid source={source} /> : (
                <p className="delivery-source-text" data-testid="source-text">
                  {source.span ? (
                    <>{source.text.slice(0, source.span[0])}<mark data-testid="source-span">{source.text.slice(source.span[0], source.span[1])}</mark>{source.text.slice(source.span[1])}</>
                  ) : source.text}
                </p>
              )}
              {source.kind === "grid" && (
                <p className="delivery-source-legend">
                  {LEGEND.map(([role, label]) => <span key={role}><i className={`hl ${role}`} aria-hidden />{label}</span>)}
                </p>
              )}
            </div>
            {source.page !== null && source.page_size && !source.blinded && <PdfPage projectId={projectId} source={source} />}
          </div>
        </>
      )}
    </aside>
  );
}
