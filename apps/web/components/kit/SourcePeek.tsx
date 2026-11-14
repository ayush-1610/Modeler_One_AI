"use client";

// The source peek (docs/plans/2026-11-03-inputs-and-client-data.md §3.3; the owner, 2026-11-03): a small icon at the top
// right of a parameter's card opens its source in the centre of the screen, over the page, which stays visible behind a
// dimmed backdrop (like Notion's centre peek). A sheet shows as its grid with the cited cells highlighted; a PDF, Word or
// text document shows its page with the quote marked; a source with no stored file shows its quote and its link. Every
// project page that shows a source opens it here.

import { useState } from "react";

import { Dialog } from "@/components/kit/Dialog";
import { useResource } from "@/lib/hooks";
import { Banner } from "@/components/kit";

export type PeekSource = {
  doc_sha256?: string | null;
  page?: number | null;
  quote?: string | null;
  title?: string | null;
  locator?: string | null;
  url?: string | null;
  doi?: string | null;
  pmid?: string | null;
};

const ROW = /^\[(.+?) row (\d+)\] (.*)$/;
const CELL = /^([A-Z]{1,3})(\d+)=(.*)$/s;

/** A workbook page (`[Sheet row 3] A3=… | B3=…` per row) as a grid: its sheet, its column letters and its rows. */
export function sheetGrid(text: string): { sheet: string; columns: string[]; rows: { n: number; cells: Record<string, string> }[] } | null {
  const rows: { n: number; cells: Record<string, string> }[] = [];
  const columns = new Set<string>();
  let sheet = "";
  for (const line of text.split("\n")) {
    const row = ROW.exec(line);
    if (!row) continue;
    sheet ||= row[1];
    const cells: Record<string, string> = {};
    for (const part of row[3].split(" | ")) {
      const cell = CELL.exec(part);
      if (!cell) continue;
      cells[cell[1]] = cell[3];
      columns.add(cell[1]);
    }
    rows.push({ n: Number(row[2]), cells });
  }
  if (!rows.length) return null;
  const order = (c: string) => [...c].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);
  return { sheet, columns: [...columns].sort((a, b) => order(a) - order(b)), rows };
}

/** The cells a quote cites: the `A3=` cells it names, or every cell of the rows it quotes whole. */
export function citedCells(quote: string | null | undefined): Set<string> {
  const out = new Set<string>();
  if (!quote) return out;
  for (const match of quote.matchAll(/\b([A-Z]{1,3})(\d+)=/g)) out.add(`${match[1]}${match[2]}`);
  for (const match of quote.matchAll(/!\$?([A-Z]{1,3})\$?(\d+)/g)) out.add(`${match[1]}${match[2]}`);
  return out;
}

/** Highlight `quote` inside `text`, tolerating whitespace differences (the citation check normalizes whitespace). */
export function highlight(text: string, quote: string | null | undefined) {
  if (!quote) return [text];
  const pattern = quote.trim().split(/\s+/).slice(0, 60).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
  const match = pattern ? new RegExp(pattern).exec(text) : null;
  if (!match) return [text];
  return [text.slice(0, match.index), <mark key="q">{match[0]}</mark>, text.slice(match.index + match[0].length)];
}

function Grid({ text, quote, locator }: { text: string; quote?: string | null; locator?: string | null }) {
  const grid = sheetGrid(text);
  if (!grid) return <pre className="doc-page">{highlight(text, quote)}</pre>;
  const cited = citedCells(`${quote ?? ""} ${locator ?? ""}`);
  return (
    <div className="peek-grid" role="region" aria-label={`Sheet ${grid.sheet}`} tabIndex={0}>
      <table>
        <thead>
          <tr><th scope="col"><span className="sr-only">Row</span></th>{grid.columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr>
        </thead>
        <tbody>
          {grid.rows.map((r) => (
            <tr key={r.n}>
              <th scope="row">{r.n}</th>
              {grid.columns.map((c) => {
                const on = cited.has(`${c}${r.n}`);
                return <td key={c} className={on ? "cited" : undefined} aria-label={on ? `${c}${r.n}, cited` : undefined}>{r.cells[c] ?? ""}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StoredPage({ projectId, source }: { projectId: string; source: PeekSource & { doc_sha256: string } }) {
  const [pageNo, setPageNo] = useState(source.page ?? 1);
  const docs = useResource("/api/v1/projects/{project_id}/documents", { project_id: projectId });
  const { data: page, problem } = useResource("/api/v1/projects/{project_id}/documents/{sha256}/pages/{page}",
    { project_id: projectId, sha256: source.doc_sha256, page: String(pageNo) }, { keepPrevious: true });
  const doc = docs.data?.documents.find((d) => d.sha256 === source.doc_sha256);
  const table = doc ? ["csv", "xlsx", "xls"].includes(doc.kind) : false;
  const quote = pageNo === (source.page ?? 1) ? source.quote : null;
  return (
    <>
      <div className="peek-bar">
        <span className="peek-file">{doc?.name ?? source.title ?? "the stored document"}</span>
        {doc && doc.n_pages > 1 && (
          <span className="row gap-6">
            <button type="button" className="btn small" aria-label="Previous page" disabled={pageNo <= 1} onClick={() => setPageNo(pageNo - 1)}>‹</button>
            <span className="muted tnum">{table ? "part" : "p."} {pageNo} / {doc.n_pages}</span>
            <button type="button" className="btn small" aria-label="Next page" disabled={pageNo >= doc.n_pages} onClick={() => setPageNo(pageNo + 1)}>›</button>
          </span>
        )}
        <a className="btn small" href={`/api/v1/projects/${projectId}/documents/${source.doc_sha256}/raw`} target="_blank" rel="noreferrer">
          Open the original</a>
      </div>
      {doc?.warnings.map((w) => <Banner key={w} tone="warn">{w}</Banner>)}
      {problem && <Banner tone="err">{problem}</Banner>}
      {!page ? <p className="muted">Loading the source…</p>
        : table ? <Grid text={page.text} quote={quote} locator={source.locator} />
          : <pre className="doc-page">{highlight(page.text, quote)}</pre>}
    </>
  );
}

/** The centre peek itself: the source over the dimmed page, closed with Escape, the backdrop or Close. */
export function SourcePeek({ projectId, source, label, onClose }: {
  projectId: string; source: PeekSource; label?: string; onClose: () => void;
}) {
  const where = [source.title, source.page ? `page ${source.page}` : "", source.locator].filter(Boolean).join(" · ");
  const link = source.url || (source.doi ? `https://doi.org/${source.doi}` : source.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${source.pmid}/` : "");
  return (
    <Dialog title={label ? `Source of ${label}` : "The source"} size="peek" onClose={onClose} testId="source-peek" dismiss>
      {where && <p className="muted peek-where">{where}</p>}
      <div className="peek-body">
        {source.doc_sha256 ? <StoredPage projectId={projectId} source={{ ...source, doc_sha256: source.doc_sha256 }} />
          : (
            <>
              {source.quote ? <blockquote className="peek-quote"><mark>{source.quote}</mark></blockquote>
                : <p className="muted">No stored file and no quote: this value was typed or taken from a database record.</p>}
              {link && <a className="btn small" href={link} target="_blank" rel="noreferrer">Open at the source</a>}
            </>
          )}
      </div>
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose} data-testid="source-peek-close">Close</button>
      </div>
    </Dialog>
  );
}

/** The small icon at the top right of a card that opens its source in the centre peek. */
export function PeekButton({ projectId, source, label, testId }: {
  projectId: string; source: PeekSource | null | undefined; label: string; testId?: string;
}) {
  const [open, setOpen] = useState(false);
  if (!source || !(source.doc_sha256 || source.quote || source.url || source.doi || source.pmid)) return null;
  return (
    <>
      <button type="button" className="peek-btn" aria-label={`Open the source of ${label}`} title="Open the source"
              data-testid={testId} onClick={() => setOpen(true)}>
        <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6"
             strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="14" height="14" rx="2.5" />
          <rect x="6.5" y="6.5" width="7" height="7" rx="1.2" />
        </svg>
      </button>
      {open && <SourcePeek projectId={projectId} source={source} label={label} onClose={() => setOpen(false)} />}
    </>
  );
}
