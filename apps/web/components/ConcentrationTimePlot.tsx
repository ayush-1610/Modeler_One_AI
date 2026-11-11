"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export type Series = {
  name: string;
  time_h: number[];
  concentration: number[];
  unit: string;
  kind: "simulated" | "observed";
  lower?: number[];
  upper?: number[];
};

type Plotly = typeof import("plotly.js-dist-min");

export function ConcentrationTimePlot({ series: given }: { series: Series[] }) {
  const container = useRef<HTMLDivElement>(null);
  const plotly = useRef<Plotly | null>(null);
  const [logScale, setLogScale] = useState(true);
  const [failed, setFailed] = useState(false);
  // keyed on the content: a running campaign's page refreshes every few seconds with an equal but new array, which must
  // not re-plot (nor move the chart under the pointer)
  const key = JSON.stringify(given);
  const series = useMemo(() => JSON.parse(key) as Series[], [key]);

  // the plot is released when the page goes
  useEffect(() => {
    const el = container.current;
    return () => { if (plotly.current && el) plotly.current.purge(el); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    import("plotly.js-dist-min").then((Plotly) => {
      if (cancelled || !container.current) return;
      plotly.current = Plotly;
      // Read the series colours off the design tokens so the plot says the same thing as the rest of the
      // interface: blue is the model's prediction, amber is what was measured in the clinic.
      const css = getComputedStyle(document.documentElement);
      const sim = css.getPropertyValue("--sim").trim() || "#0071e3";
      const obs = css.getPropertyValue("--obs").trim() || "#b25000";
      const ink = css.getPropertyValue("--ink-dim").trim() || "#6e6e73";
      const grid = css.getPropertyValue("--line").trim() || "#e3e3e8";

      const traces = series.flatMap((s) => {
        const colour = s.kind === "observed" ? obs : sim;
        const main = {
          name: s.name,
          x: s.time_h,
          y: s.concentration,
          type: "scatter" as const,
          mode: s.kind === "observed" ? ("markers" as const) : ("lines" as const),
          line: { color: colour, width: 2 },
          marker: { color: colour, size: 7, line: { color: "rgba(0,0,0,0.35)", width: 1 } },
        };
        if (!s.lower || !s.upper) return [main];
        const band = {
          name: `${s.name} 5th-95th percentile`,
          x: [...s.time_h, ...[...s.time_h].reverse()],
          y: [...s.upper, ...[...s.lower].reverse()],
          type: "scatter" as const,
          fill: "toself" as const,
          line: { width: 0 },
          opacity: 0.2,
          hoverinfo: "skip" as const,
        };
        return [band, main];
      });
      const unit = series[0]?.unit ?? "";
      return Plotly.react(
        container.current,
        traces,
        {
          // Plotly keeps the person's zoom and pan across new data; a change of scale resets the y axis only
          uirevision: "gof",
          autosize: true,
          margin: { l: 64, r: 16, t: 8, b: 48 },
          font: { color: ink, family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, system-ui, sans-serif", size: 12 },
          xaxis: { title: { text: "Time (h)" }, gridcolor: grid, zerolinecolor: grid },
          yaxis: { title: { text: `Plasma concentration (${unit})` }, type: logScale ? "log" : "linear",
                   uirevision: logScale ? "log" : "linear", gridcolor: grid, zerolinecolor: grid },
          legend: { orientation: "h", y: -0.22 },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
        },
        { responsive: true, displaylogo: false },
      ).then(() => {
        // the grid column is sized after this effect runs; force Plotly to measure the settled width
        if (container.current) Plotly.Plots.resize(container.current);
      });
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => {
      cancelled = true;
    };
  }, [series, logScale]);

  return (
    <figure className="m-0">
      <label className="inline-flex gap-6 items-center mb-8">
        <input id="log-scale" type="checkbox" checked={logScale} onChange={(e) => setLogScale(e.target.checked)} />
        Log scale
      </label>
      {failed && (
        <p className="banner err" role="status" data-testid="plot-failed">The plot could not be loaded; reload the page.</p>
      )}
      <div ref={container} className="w-full h-360" hidden={failed} />
    </figure>
  );
}
