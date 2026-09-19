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
      const traces = series.flatMap((s) => {
        const main = {
          name: s.name,
          x: s.time_h,
          y: s.concentration,
          type: "scatter" as const,
          mode: s.kind === "observed" ? ("markers" as const) : ("lines" as const),
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
          margin: { l: 64, r: 16, t: 16, b: 48 },
          xaxis: { title: { text: "Time (h)" } },
          yaxis: { title: { text: `Plasma concentration (${unit})` }, type: logScale ? "log" : "linear" },
          legend: { orientation: "h" },
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
