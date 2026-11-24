// A small Markdown reader for the product's own guides (docs/USING_THE_TOOL.md on /help): headings with anchors,
// paragraphs, nested lists, code blocks, tables, **bold**, `code` and [links](...). Only the repository's own files are
// drawn with it, never a client's or a model's text; it builds React elements, never raw HTML.

import type { ReactNode } from "react";

export type Heading = { level: number; text: string; id: string };

export function slug(text: string): string {
  return text.toLowerCase().replace(/[`*]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

/** Inline marks: `code`, **bold**, [text](href). */
export function inline(text: string, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0;
  let n = 0;
  for (const m of text.matchAll(pattern)) {
    if (m.index! > last) out.push(text.slice(last, m.index));
    const token = m[0];
    const k = `${key}-${n++}`;
    if (token.startsWith("`")) out.push(<code key={k}>{token.slice(1, -1)}</code>);
    else if (token.startsWith("**")) out.push(<strong key={k}>{inline(token.slice(2, -2), k)}</strong>);
    else {
      const [, label, href] = token.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/)!;
      const safe = /^(https?:\/\/|\/|#)/.test(href!) ? href : undefined;           // no javascript: or relative files
      out.push(safe ? <a key={k} href={safe}>{label}</a> : <span key={k}>{label}</span>);
    }
    last = m.index! + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Line = { indent: number; text: string };

const LIST = /^(\s*)([-*]|\d+\.)\s+(.*)$/;

function list(lines: Line[], start: number, indent: number, key: string): [ReactNode, number] {
  const ordered = /^\d+\./.test(lines[start]!.text.trim().split(/\s/)[0]!);
  const items: ReactNode[] = [];
  let i = start;
  while (i < lines.length) {
    const m = lines[i]!.text.match(LIST);
    if (!m || m[1]!.length !== indent) break;
    let body = m[3]!;
    const children: ReactNode[] = [];
    i++;
    while (i < lines.length && lines[i]!.text.trim() !== "") {
      const sub = lines[i]!.text.match(LIST);
      if (sub && sub[1]!.length > indent) {
        const [node, next] = list(lines, i, sub[1]!.length, `${key}-${i}`);
        children.push(node);
        i = next;
      } else if (!sub && lines[i]!.indent > indent) {
        body += " " + lines[i]!.text.trim();                         // the item's text, wrapped onto the next line
        i++;
      } else break;
    }
    items.push(<li key={`${key}-${i}`}>{inline(body, `${key}-${i}`)}{children}</li>);
    if (i < lines.length && lines[i]!.text.trim() === "" && lines[i + 1]?.text.match(LIST)?.[1]?.length === indent) i++;
  }
  return [ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>, i];
}

/** The document as React elements, and its headings (for a table of contents). */
export function markdown(source: string): { body: ReactNode[]; headings: Heading[] } {
  const lines: Line[] = source.replace(/\r/g, "").split("\n").map((text) => ({ text, indent: text.length - text.trimStart().length }));
  const body: ReactNode[] = [];
  const headings: Heading[] = [];
  let i = 0;
  while (i < lines.length) {
    const text = lines[i]!.text;
    const key = `b${i}`;
    if (text.trim() === "") { i++; continue; }
    const heading = text.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = heading[1]!.length;
      const title = heading[2]!.trim();
      const id = slug(title);
      headings.push({ level, text: title.replace(/[`*]/g, ""), id });
      const Tag = `h${Math.min(level + 1, 6)}` as "h2";
      body.push(<Tag key={key} id={id}>{inline(title, key)}</Tag>);
      i++;
      continue;
    }
    if (text.trimStart().startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i]!.text.trimStart().startsWith("```")) code.push(lines[i++]!.text);
      i++;
      body.push(<pre key={key}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    if (text.trimStart().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i]!.text.trimStart().startsWith("|")) {
        const cells = lines[i]!.text.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      const [head, ...rest] = rows;
      body.push(
        <div className="table-scroll" key={key}>
          <table>
            <thead><tr>{head!.map((c, j) => <th key={j}>{inline(c, `${key}h${j}`)}</th>)}</tr></thead>
            <tbody>{rest.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c, `${key}r${k}c${j}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    const item = text.match(LIST);
    if (item) {
      const [node, next] = list(lines, i, item[1]!.length, key);
      body.push(node);
      i = next;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i]!.text.trim() !== "" && !/^(#{1,4}\s|```|\|)/.test(lines[i]!.text.trimStart())
           && !(para.length && LIST.test(lines[i]!.text))) para.push(lines[i++]!.text.trim());
    body.push(<p key={key}>{inline(para.join(" "), key)}</p>);
  }
  return { body, headings };
}
