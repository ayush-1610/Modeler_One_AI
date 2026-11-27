"use client";

// The Data room's shared pieces (plan 2026-11-21 v2 §6, §10): the status tag and the section dot (a word as well as a
// colour, never colour alone), the source chip that opens the source drawer, a card, a table row whose details open on
// click, the one chart style, and the "paper" switch that turns every piece into its printed form for the report.

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { SECTION_STATE, STATUS, chipLabel, chipText, type Chip, type Section, type Status } from "@/lib/dataroom";
import { Icon } from "@/components/kit/icons";

// --- paper: the report prints what the page shows, without its controls ---------------------------------------------

const PaperContext = createContext(false);
export const PaperProvider = PaperContext.Provider;
/** Whether the room is drawn for paper (the evidence report): no buttons, chips written out, charts still. */
export const usePaper = () => useContext(PaperContext);

// --- status --------------------------------------------------------------------------------------------------------

export function StatusTag({ status }: { status: Status }) {
  const s = STATUS[status];
  return <span className={`dr-status ${status}`} title={s.means} data-status={status}><span className="dr-status-dot" aria-hidden />{s.word}</span>;
}

/** A section's status as a dot (its word for a screen reader, or beside it with `label`). While a run reads the
 *  delivery (`reading`), a section with nothing yet says it is being read (plan 2026-11-26 §9, slice 5c). */
export function Dot({ status, label, reading = false }: { status: Section["status"]; label?: boolean; reading?: boolean }) {
  const shown = reading && status === "empty";
  const word = shown ? READING : SECTION_STATE[status];
  return (
    <span className={`dr-dot-wrap${label ? " labelled" : ""}`} title={word}>
      <span className={`dr-dot ${shown ? "reading" : status}`} aria-hidden />
      {label ? <span className="dr-dot-word">{word}</span> : <span className="sr-only">{word}</span>}
    </span>
  );
}

export const READING = "Reading";

// --- sources ---------------------------------------------------------------------------------------------------------

const SourceContext = createContext<(chip: Chip) => void>(() => undefined);
export const SourceProvider = SourceContext.Provider;

/** A value's source: the file and its place; opens the page or the sheet with the place highlighted. */
export function SourceChip({ chip, testId }: { chip: Chip; testId?: string }) {
  const open = useContext(SourceContext);
  const paper = usePaper();
  if (paper) return <span className="dr-chip paper">{chipText(chip)}</span>;
  return (
    <button type="button" className="dr-chip" onClick={() => open(chip)} title={`Open ${chipText(chip)}`} data-testid={testId ?? "source-chip"}>
      <Icon name="file" size={13} />
      <span className="dr-chip-text">{chipLabel(chip)}</span>
    </button>
  );
}

/** The sources of a value: its first chip, and how many more (all of them on paper). */
export function Sources({ chips, max = 1 }: { chips: readonly Chip[]; max?: number }) {
  const paper = usePaper();
  if (!chips.length) return <span className="muted">—</span>;
  const shown = paper ? chips : chips.slice(0, max);
  return (
    <span className="dr-sources">
      {shown.map((c, i) => <SourceChip key={`${c.sha256}-${c.part}-${c.line}-${c.cell ?? ""}-${i}`} chip={c} />)}
      {chips.length > shown.length && <span className="dr-more">+{chips.length - shown.length}</span>}
    </span>
  );
}

// --- layout ----------------------------------------------------------------------------------------------------------

export function Card({ title, aside, children, testId, className }: {
  title?: ReactNode; aside?: ReactNode; children: ReactNode; testId?: string; className?: string;
}) {
  return (
    <section className={`dr-card${className ? ` ${className}` : ""}`} data-testid={testId}>
      {(title || aside) && (
        <header className="dr-card-head">
          {title && <h3 className="dr-card-title">{title}</h3>}
          {aside && <div className="dr-card-aside">{aside}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/** What a section shows when it has nothing yet. */
export function Nothing({ children }: { children: ReactNode }) {
  return <p className="dr-nothing">{children}</p>;
}

/** A table row whose details open beneath it on click (the default table shows four columns at most: plan §10). On
 *  paper every row is shown with its details. */
// the table's column names, which a row's cells carry, so a phone shows each cell with its name (the head is hidden there)
const HeadContext = createContext<string[]>([]);

export function Row({ cells, details, testId, highlight }: {
  cells: ReactNode[]; details?: ReactNode; testId?: string; highlight?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const paper = usePaper();
  const head = useContext(HeadContext);
  const expandable = Boolean(details) && !paper;
  return (
    <>
      <tr className={`${expandable ? "dr-row-open" : ""}${open ? " open" : ""}${highlight ? " dr-row-mark" : ""}`} data-testid={testId}
          onClick={expandable ? (e) => { if (!(e.target as Element).closest("button, a, input, select, textarea")) setOpen(!open); } : undefined}>
        {cells.map((c, i) => (
          <td key={i} data-label={i > 0 ? head[i] : undefined}>
            {i === 0 && expandable ? (
              <button type="button" className="dr-row-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
                <span className="dr-caret" aria-hidden><Icon name={open ? "chevd" : "chevr"} size={14} /></span>{c}
              </button>
            ) : c}
          </td>
        ))}
      </tr>
      {details && (open || paper) && (
        <tr className="dr-detail"><td colSpan={cells.length}>{details}</td></tr>
      )}
    </>
  );
}

export function Table({ head, children, label, testId }: { head: string[]; children: ReactNode; label: string; testId?: string }) {
  return (
    <div className="dr-table-wrap">
      <table className="dr-table" data-testid={testId}>
        <caption className="sr-only">{label}</caption>
        <thead><tr>{head.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody><HeadContext.Provider value={head}>{children}</HeadContext.Provider></tbody>
      </table>
    </div>
  );
}

/** A segmented choice (arithmetic or geometric, linear or log). */
export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: [T, string][]; onChange: (v: T) => void; label: string;
}) {
  const paper = usePaper();
  if (paper) return null;
  return (
    <div className="dr-seg" role="group" aria-label={label}>
      {options.map(([id, word]) => (
        <button key={id} type="button" aria-pressed={value === id} className={value === id ? "on" : ""} onClick={() => onChange(id)}>{word}</button>
      ))}
    </div>
  );
}

// --- the one chart style (plan §10: thin lines, dots at the data, events as a dashed rule, units on the axes) -----------

type Trace = Record<string, unknown>;

export function Plot({ traces, layout, height = 320, testId, label }: {
  traces: Trace[]; layout: Record<string, unknown>; height?: number; testId?: string; label: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const paper = usePaper();
  useEffect(() => {
    let gone = false;
    void import("plotly.js-dist-min").then((Plotly) => {
      if (gone || !box.current) return;
      // the page's own type and secondary ink (app/layout.tsx, app/styles/tokens.css), so the chart reads as the page does
      const ink = getComputedStyle(document.documentElement).getPropertyValue("--c-ink-3").trim() || "#52525B";
      const font = { family: getComputedStyle(document.body).fontFamily || "system-ui, sans-serif", size: 13, color: ink };
      const axis = { gridcolor: "rgba(0,0,0,0.06)", zerolinecolor: "rgba(0,0,0,0.12)", linecolor: "rgba(0,0,0,0.18)",
                     tickfont: { size: 12 }, title: { font: { size: 13 } }, automargin: true };
      const given = layout as { xaxis?: Record<string, unknown>; yaxis?: Record<string, unknown> };
      void Plotly.react(box.current, traces as never, {
        autosize: true, height, font, margin: { l: 56, r: 12, t: 16, b: 56 }, paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)", hoverlabel: { font: { size: 13 } }, showlegend: true,
        legend: { orientation: "h", y: -0.3, x: 0, font: { size: 12 } }, ...layout,
        xaxis: { ...axis, ...given.xaxis }, yaxis: { ...axis, ...given.yaxis },
      } as never, { responsive: true, displaylogo: false, displayModeBar: false, staticPlot: paper } as never).then(() => {
        if (box.current) Plotly.Plots.resize(box.current);
      });
    });
    return () => { gone = true; };
  }, [traces, layout, height, paper]);
  return <div ref={box} className="dr-plot" style={{ minHeight: height }} role="img" aria-label={label} data-testid={testId} />;
}

/** A line series with dots at the data (and SD bars when given), in a product's colour. */
export function series(name: string, x: number[], y: (number | null)[], colour: string, extra: Trace = {}): Trace {
  return { type: "scatter", mode: "lines+markers", name, x, y, line: { color: colour, width: 1.6 },
           marker: { color: colour, size: 6 }, connectgaps: true, ...extra };
}

/** A dashed vertical rule with its label (a meal after the dose). */
export function rule(x: number, label: string): { shape: Record<string, unknown>; note: Record<string, unknown> } {
  return {
    shape: { type: "line", xref: "x", yref: "paper", x0: x, x1: x, y0: 0, y1: 1, line: { color: "#A1A1AA", width: 1, dash: "dash" } },
    note: { x, y: 1, xref: "x", yref: "paper", text: label, showarrow: false, yanchor: "bottom", font: { size: 11, color: "#52525B" } },
  };
}
