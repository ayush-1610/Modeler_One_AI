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
      Plotly.react(
        container.current,
        traces,
        {
          margin: { l: 64, r: 16, t: 16, b: 48 },
          xaxis: { title: { text: "Time (h)" } },
          yaxis: { title: { text: `Plasma concentration (${unit})` }, type: logScale ? "log" : "linear" },
          legend: { orientation: "h" },
        },
        { responsive: true, displaylogo: false },
      );
    });
    return () => {
      cancelled = true;
    };
  }, [series, logScale]);

  return (
    <figure>
      <label>
        <input id="log-scale" type="checkbox" checked={logScale} onChange={(e) => setLogScale(e.target.checked)} /> Log
        scale
      </label>
      <div ref={container} style={{ width: "100%", minHeight: 360 }} />
    </figure>
  );
}
