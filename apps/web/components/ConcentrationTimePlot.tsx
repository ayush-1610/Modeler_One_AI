"use client";

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

export function ConcentrationTimePlot({ series }: { series: Series[] }) {
  const container = useRef<HTMLDivElement>(null);
  const [logScale, setLogScale] = useState(true);

  useEffect(() => {
    let cancelled = false;
    import("plotly.js-dist-min").then((Plotly) => {
      if (cancelled || !container.current) return;
      // Read the series colours off the design tokens so the plot says the same thing as the rest of the
      // interface: teal is the model's prediction, amber is what was measured in the clinic.
      const css = getComputedStyle(document.documentElement);
      const sim = css.getPropertyValue("--sim").trim() || "#5bd1c4";
      const obs = css.getPropertyValue("--obs").trim() || "#f2a65a";
      const ink = css.getPropertyValue("--ink-dim").trim() || "#8ea3b3";
      const grid = css.getPropertyValue("--line").trim() || "#223040";

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
      void Plotly.react(
        container.current,
        traces,
        {
          autosize: true,
          margin: { l: 64, r: 16, t: 8, b: 48 },
          font: { color: ink, family: "var(--font-sans), system-ui, sans-serif", size: 12 },
          xaxis: { title: { text: "Time (h)" }, gridcolor: grid, zerolinecolor: grid },
          yaxis: { title: { text: `Plasma concentration (${unit})` }, type: logScale ? "log" : "linear",
                   gridcolor: grid, zerolinecolor: grid },
          legend: { orientation: "h", y: -0.22 },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
        },
        { responsive: true, displaylogo: false },
      ).then(() => {
        // the grid column is sized after this effect runs; force Plotly to measure the settled width
        if (container.current) Plotly.Plots.resize(container.current);
      });
    });
    return () => {
      cancelled = true;
    };
  }, [series, logScale]);

  return (
    <figure style={{ margin: 0 }}>
      <label style={{ display: "inline-flex", gap: 6, alignItems: "center", marginBottom: 8 }}>
        <input id="log-scale" type="checkbox" checked={logScale} onChange={(e) => setLogScale(e.target.checked)} />
        Log scale
      </label>
      <div ref={container} style={{ width: "100%", height: 360 }} />
    </figure>
  );
}
