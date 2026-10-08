"use client";

import { useEffect, useState } from "react";

import type { DocumentView } from "@/lib/brief";
import { get, type Schema } from "@/lib/api";

type Page = Schema<"DocumentPage">;

/** Highlight `quote` inside `text`, tolerating whitespace differences (the citation check normalizes whitespace). */
function highlight(text: string, quote: string | null) {
  if (!quote) return [text];
  const pattern = quote.trim().split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
  const match = new RegExp(pattern).exec(text);
  if (!match) return [text];
  return [text.slice(0, match.index), <mark key="q">{match[0]}</mark>, text.slice(match.index + match[0].length)];
}

/** The source beside the brief: any uploaded document, page by page, with the cited quote marked. */
export function DocumentViewer({
  projectId, documents, focus,
}: {
  projectId: string;
  documents: DocumentView[];
  focus: { sha256: string; page: number; quote: string | null } | null;
}) {
  const [sha, setSha] = useState<string | null>(focus?.sha256 ?? documents[0]?.sha256 ?? null);
  const [pageNo, setPageNo] = useState<number>(focus?.page ?? 1);
  const [page, setPage] = useState<Page | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (focus) {
      setSha(focus.sha256);
      setPageNo(focus.page);
    }
  }, [focus]);

  useEffect(() => {
    if (!sha && documents[0]) setSha(documents[0].sha256);
  }, [documents, sha]);

  useEffect(() => {
    if (!sha) return;
    let cancelled = false;
    get("/api/v1/projects/{project_id}/documents/{sha256}/pages/{page}", { project_id: projectId, sha256: sha, page: String(pageNo) }).then((env) => {
      if (cancelled) return;
      if (env.errors?.length || !env.data) setProblem(env.errors?.[0]?.message ?? "page not found");
      else { setProblem(null); setPage(env.data); }
    });
    return () => { cancelled = true; };
  }, [projectId, sha, pageNo]);

  const doc = documents.find((d) => d.sha256 === sha);
  const quote = focus && focus.sha256 === sha && focus.page === pageNo ? focus.quote : null;

  return (
    <section className="card doc-viewer">
      <div className="spread" style={{ marginBottom: 8 }}>
        <select value={sha ?? ""} onChange={(e) => { setSha(e.target.value); setPageNo(1); }} aria-label="Document">
          {documents.map((d) => (
            <option key={d.sha256} value={d.sha256}>{d.name} · {d.role.replace("_", " ")}</option>
          ))}
        </select>
        {doc && (
          <span className="row" style={{ gap: 6 }}>
            <button className="btn" disabled={pageNo <= 1} onClick={() => setPageNo(pageNo - 1)}>‹</button>
            <span className="muted" style={{ fontVariantNumeric: "tabular-nums" }}>p. {pageNo} / {doc.n_pages}</span>
            <button className="btn" disabled={pageNo >= doc.n_pages} onClick={() => setPageNo(pageNo + 1)}>›</button>
            <a className="btn" href={`/api/v1/projects/${projectId}/documents/${doc.sha256}/raw`} target="_blank"
               rel="noreferrer">Original</a>
          </span>
        )}
      </div>
      {doc?.warnings.map((w) => <div key={w} className="banner warn" style={{ marginBottom: 8 }}>{w}</div>)}
      {problem && <div className="banner err">{problem}</div>}
      <pre className="doc-page">{page ? highlight(page.text, quote) : "…"}</pre>
    </section>
  );
}
