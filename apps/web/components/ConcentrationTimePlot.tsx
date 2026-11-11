"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

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

const KIND = { simulated: "Predicted", observed: "Observed" } as const;

/** A colour token (#rrggbb, #rgb or rgb()) at the given alpha, for Plotly, which reads no CSS color-mix(). */
function withAlpha(colour: string, alpha: number): string {
  const hex = colour.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)?.[1];
  const rgb = hex
    ? (hex.length === 3 ? [...hex].map((c) => parseInt(c + c, 16)) : [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)))
    : colour.match(/\d+(\.\d+)?/g)?.slice(0, 3).map(Number);
  return rgb?.length === 3 ? `rgba(${rgb.join(", ")}, ${alpha})` : colour;
}

/** A number as the table prints it: four significant figures (the full series is the API's own JSON). */
const sig = (v: number) => (Number.isFinite(v) ? Number(v.toPrecision(4)).toString() : "");

/** The series' legend name: Predicted / Observed, with the study when the chart holds more than one. */
function seriesName(s: Series, several: boolean) {
  return several ? `${KIND[s.kind]} · ${s.name}` : KIND[s.kind];
}

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

      const several = new Set(series.map((s) => s.name)).size > 1;
      const traces = series.flatMap((s) => {
        const colour = s.kind === "observed" ? obs : sim;
        const name = seriesName(s, several);
        const main = {
          name,
          legendgroup: name,
          // the study is named on hover even when the legend says only Predicted / Observed
          hovertemplate: `${s.name}<br>%{x} h, %{y:.4g} ${s.unit}<extra>${KIND[s.kind]}</extra>`,
          x: s.time_h,
          y: s.concentration,
          type: "scatter" as const,
          mode: s.kind === "observed" ? ("markers" as const) : ("lines" as const),
          line: { color: colour, width: 2 },
          marker: { color: colour, size: 7, line: { color: "rgba(0,0,0,0.35)", width: 1 } },
        };
        if (!s.lower || !s.upper) return [main];
        const band = {
          name: `${name} 5th-95th percentile`,
          legendgroup: name,
          showlegend: false,
          x: [...s.time_h, ...[...s.time_h].reverse()],
          y: [...s.upper, ...[...s.lower].reverse()],
          type: "scatter" as const,
          fill: "toself" as const,
          // the band in the series' own colour (the token), not the next colour of Plotly's default palette
          fillcolor: withAlpha(colour, 0.18),
          line: { width: 0, color: colour },
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
          // powers of ten, never SI suffixes: a '100µ' tick beside a µmol/l title reads as 100 µmol/l
          xaxis: { title: { text: "Time (h)" }, gridcolor: grid, zerolinecolor: grid, exponentformat: "power" },
          yaxis: { title: { text: `Plasma concentration (${unit})` }, type: logScale ? "log" : "linear",
                   uirevision: logScale ? "log" : "linear", gridcolor: grid, zerolinecolor: grid, exponentformat: "power" },
          legend: { orientation: "h", y: -0.22 },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
        },
        // only the download stays in the modebar
        { responsive: true, displaylogo: false,
          modeBarButtonsToRemove: ["zoom2d", "pan2d", "select2d", "lasso2d", "zoomIn2d", "zoomOut2d", "autoScale2d",
                                   "resetScale2d", "hoverClosestCartesian", "hoverCompareCartesian", "toggleSpikelines"] },
      ).then(() => {
        // the grid column is sized after this effect runs; force Plotly to measure the settled width
        if (container.current) Plotly.Plots.resize(container.current);
      });
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => {
      cancelled = true;
    };
  }, [series, logScale]);

  const unit = series[0]?.unit ?? "";
  const several = new Set(series.map((s) => s.name)).size > 1;
  const kinds = [...new Set(series.map((s) => KIND[s.kind].toLowerCase()))].join(" and ");
  const times = series.flatMap((s) => s.time_h);
  const span = times.length ? `${sig(Math.min(...times))} to ${sig(Math.max(...times))} h` : "no points";
  const summary = series.length
    ? `Plasma concentration (${unit}) against time: ${series.length} series (${kinds}), ${span}, ${logScale ? "log" : "linear"} scale`
    : "No series to plot yet";
  // the caption names only what is drawn: a chart with no observed series never says "observed (points)"
  const predicted = series.some((s) => s.kind === "simulated");
  const observed = series.some((s) => s.kind === "observed");
  const band = series.some((s) => s.kind === "simulated" && s.lower && s.upper) ? ", with the 5th-95th percentile band" : "";
  const drawn = [predicted && `Predicted (line${band})`, observed && (predicted ? "observed (points)" : "Observed (points)")]
    .filter(Boolean).join(" and ");
  const summaryId = useId();

  return (
    // the figure is named by its caption and described by the summary; the chart surface carries no role="img", which
    // would hide the modebar's download control inside it from assistive technology (audit 2 review)
    <figure className="m-0" data-testid="gof-figure" aria-describedby={summaryId}>
      <figcaption className="muted mb-8" data-testid="gof-caption">
        {series.length
          ? <>{drawn} plasma concentration in {unit || "the series' unit"} against time in hours, on a {logScale ? "log" : "linear"} scale.</>
          : "No series to plot yet."}
      </figcaption>
      <p className="sr-only" id={summaryId} data-testid="gof-summary">{summary}</p>
      <label className="inline-flex gap-6 items-center mb-8">
        <input id="log-scale" type="checkbox" checked={logScale} onChange={(e) => setLogScale(e.target.checked)} />
        Log scale
      </label>
      {failed && (
        <p className="banner err" role="alert" data-testid="plot-failed">The plot could not be loaded; reload the page.</p>
      )}
      <div ref={container} className="w-full h-360" hidden={failed} data-testid="gof-plot" />
      {series.length > 0 && (
        // the chart's text alternative: every point it draws, series by series (as the dataset cards do)
        <details className="dataset-points" data-testid="gof-data">
          <summary>The data ({series.length} series)</summary>
          {series.map((s, i) => (
            <div className="table-scroll" key={`${s.kind}-${s.name}-${i}`}>
              <table>
                <caption>{seriesName(s, several)}{several ? "" : ` · ${s.name}`}</caption>
                <thead><tr><th className="num">Time (h)</th><th className="num">Concentration ({s.unit})</th>
                  {s.lower && s.upper && <><th className="num">5th percentile</th><th className="num">95th percentile</th></>}</tr></thead>
                <tbody>
                  {s.time_h.map((t, k) => (
                    <tr key={k}><td className="num">{sig(t)}</td><td className="num">{sig(s.concentration[k])}</td>
                      {s.lower && s.upper && <><td className="num">{sig(s.lower[k])}</td><td className="num">{sig(s.upper[k])}</td></>}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </details>
      )}
    </figure>
  );
}
