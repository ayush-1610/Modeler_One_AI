"use client";

// The console's chart (design-review/DESIGN_SYSTEM.md §5.8, the redesign's slice 6): concentration against time, the
// model's prediction as lines (blue) and what was measured as points (amber), with a 5th–95th percentile band where a
// series carries one. The scale switches between log and linear (log by default, as PK plots are read); the same
// numbers are a table under it, for a screen reader or a check by eye. Plotly is loaded on demand.

import { useEffect, useRef, useState } from "react";

export type Series = {
  name: string;
  time_h: number[];
  concentration: number[];
  unit: string;
  kind: "simulated" | "observed";
  lower?: number[];
  upper?: number[];
};

const fmt = (v: number) => (v === 0 ? "0" : Math.abs(v) >= 1000 || Math.abs(v) < 0.01 ? v.toExponential(2) : String(+v.toPrecision(3)));

export function Chart({ series, label, empty, testId }: {
  series: Series[];
  /** The chart's accessible name ("Goodness of fit: predicted and observed concentrations"). */
  label: string;
  /** What is said when there is nothing to draw. */
  empty: string;
  testId?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState<"log" | "linear">("log");

  useEffect(() => {
    if (!series.length) return;
    let cancelled = false;
    import("plotly.js-dist-min").then((Plotly) => {
      if (cancelled || !container.current) return;
      // the series colours off the design tokens, so the chart says what the rest of the interface says
      const css = getComputedStyle(document.documentElement);
      const sim = css.getPropertyValue("--sim").trim() || "#2563EB";
      const obs = css.getPropertyValue("--obs").trim() || "#EA580C";
      const ink = css.getPropertyValue("--ink-dim").trim() || "#6e6e73";
      const grid = css.getPropertyValue("--line").trim() || "#e3e3e8";
      const font = getComputedStyle(document.body).fontFamily || "system-ui, sans-serif";   // the page's own type
      const traces = series.flatMap((s) => {
        const colour = s.kind === "observed" ? obs : sim;
        const main = {
          name: s.name, x: s.time_h, y: s.concentration, type: "scatter" as const,
          mode: s.kind === "observed" ? ("markers" as const) : ("lines" as const),
          line: { color: colour, width: 2 },
          marker: { color: colour, size: 7, line: { color: "rgba(0,0,0,0.35)", width: 1 } },
        };
        if (!s.lower || !s.upper) return [main];
        const band = {
          name: `${s.name} 5th–95th percentile`, x: [...s.time_h, ...[...s.time_h].reverse()],
          y: [...s.upper, ...[...s.lower].reverse()], type: "scatter" as const, fill: "toself" as const,
          line: { width: 0 }, opacity: 0.2, hoverinfo: "skip" as const,
        };
        return [band, main];
      });
      const unit = series[0]?.unit ?? "";
      void Plotly.react(container.current, traces, {
        autosize: true, margin: { l: 64, r: 16, t: 8, b: 48 }, font: { color: ink, family: font, size: 12 },
        xaxis: { title: { text: "Time (h)" }, gridcolor: grid, zerolinecolor: grid },
        yaxis: { title: { text: `Plasma concentration (${unit})` }, type: scale, gridcolor: grid, zerolinecolor: grid },
        legend: { orientation: "h", y: -0.22 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      }, { responsive: true, displaylogo: false }).then(() => {
        // the column is sized after this effect runs; Plotly measures the settled width
        if (container.current) Plotly.Plots.resize(container.current);
      });
    });
    return () => { cancelled = true; };
  }, [series, scale]);

  if (!series.length) return <p className="muted m-0" data-testid={testId}>{empty}</p>;
  return (
    <figure className="chart m-0" data-testid={testId}>
      <div className="chart-tools">
        <div className="view-switch" role="group" aria-label="Concentration scale">
          {(["log", "linear"] as const).map((s) => (
            <button key={s} type="button" aria-pressed={scale === s} onClick={() => setScale(s)} data-testid={`chart-scale-${s}`}>
              {s === "log" ? "Log" : "Linear"}
            </button>
          ))}
        </div>
      </div>
      <div ref={container} className="chart-plot" role="img" aria-label={label} />
      <details className="chart-data">
        <summary>The numbers as a table</summary>
        <div className="tbl-scroll">
          <table>
            <caption className="sr-only">{label}</caption>
            <thead><tr><th scope="col">Series</th><th scope="col" className="num">Time (h)</th>
              <th scope="col" className="num">Concentration ({series[0]?.unit})</th></tr></thead>
            <tbody>
              {series.flatMap((s) => s.time_h.map((t, i) => (
                <tr key={`${s.name}-${i}`}><td>{i === 0 ? s.name : ""}</td><td className="num">{fmt(t)}</td>
                  <td className="num">{fmt(s.concentration[i])}</td></tr>
              )))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
