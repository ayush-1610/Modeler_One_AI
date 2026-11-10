"use client";

// One dataset on its study's card, as data (plan 2026-11-05 §3.2, build C; the owner, 2026-11-05: "no data points, no
// graph, no metadata, no statistics"): the profile drawn (linear or log), code's statistics of each series
// (`modeler_project.dataset_points`: Cmax, tmax, AUC by the platform's NCA), the client's reported PK beside them, and
// the table of points. A blinded dataset (D-15) shows its times only.

import { useState } from "react";

import type { Schema } from "@/lib/api";

type Data = Schema<"DatasetPoints">;
type Series = Schema<"SeriesPoints">;

const W = 560, H = 230, PAD = { l: 56, r: 12, t: 12, b: 40 };
const CATEGORICAL = 8;    // series past this are drawn in one neutral ink (subjects), never in generated hues

const sig = (x: number | null | undefined, digits = 3) =>
  x === null || x === undefined || !Number.isFinite(x) ? "—" : Number(x.toPrecision(digits)).toLocaleString();

function ticks(lo: number, hi: number, n = 5): number[] {
  const span = hi - lo || 1;
  const step = 10 ** Math.floor(Math.log10(span / n));
  const nice = [1, 2, 2.5, 5, 10].map((m) => m * step).find((s) => span / s <= n) ?? step * 10;
  const out = [];
  for (let v = Math.ceil(lo / nice) * nice; v <= hi + nice * 1e-9; v += nice) out.push(Number(v.toPrecision(12)));
  return out;
}

function logTicks(lo: number, hi: number): number[] {
  const out = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e += 1) {
    for (const m of [1, 2, 5]) out.push(Number((m * 10 ** e).toPrecision(6)));
  }
  return out;
}

/** The profile: each series a line with its markers (mean ± its error as whiskers), points below the LLOQ as open
 *  markers on the axis. */
function ProfileChart({ data, label }: { data: Data; label: string }) {
  const [log, setLog] = useState(false);
  const series = data.series;
  const many = series.length > CATEGORICAL;
  const shown = (v: number | null) => v !== null && (!log || v > 0);
  const all = series.flatMap((s) => s.values.flatMap((v, i) => {
    const e = s.error?.[i] ?? 0;
    return v === null ? [] : [v + e, Math.max(v - e, 0)];
  })).filter((v) => !log || v > 0);
  const times = series.flatMap((s) => s.times);
  if (!all.length || !times.length) return null;
  const tMax = Math.max(...times), tMin = Math.min(0, ...times);
  const yLo = log ? Math.min(...all) : 0, yHi = Math.max(...all, data.lloq ?? 0);
  const x = (t: number) => PAD.l + ((t - tMin) / (tMax - tMin || 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => {
    const f = log ? (Math.log10(v) - Math.log10(yLo)) / (Math.log10(yHi) - Math.log10(yLo) || 1) : v / (yHi || 1);
    return H - PAD.b - Math.min(Math.max(f, 0), 1) * (H - PAD.t - PAD.b);
  };
  const yTicks = log ? logTicks(yLo, yHi) : ticks(0, yHi);
  const color = (i: number) => (many ? "var(--series-neutral)" : `var(--series-${(i % CATEGORICAL) + 1})`);
  return (
    <figure className="profile-chart" data-testid="profile-chart">
      <div className="profile-chart-bar">
        <span className="muted">{label}</span>
        <span className="seg" role="group" aria-label="y scale">
          <button type="button" aria-pressed={!log} onClick={() => setLog(false)}>Linear</button>
          <button type="button" aria-pressed={log} onClick={() => setLog(true)} data-testid="chart-log">Log</button>
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label}, ${log ? "log" : "linear"} scale`}>
        {yTicks.filter((v) => !log || (v >= yLo / 1.0001 && v <= yHi * 1.0001)).map((v) => (
          <g key={v} className="grid">
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} />
            <text x={PAD.l - 6} y={y(v) + 4} textAnchor="end">{sig(v, 3)}</text>
          </g>
        ))}
        {ticks(tMin, tMax).map((t) => (
          <text key={t} className="tick" x={x(t)} y={H - PAD.b + 16} textAnchor="middle">{sig(t, 3)}</text>
        ))}
        <text className="axis-label" x={(W + PAD.l) / 2} y={H - 4} textAnchor="middle">time ({data.time_unit})</text>
        <text className="axis-label" transform={`translate(12 ${(H - PAD.b) / 2}) rotate(-90)`} textAnchor="middle">{data.unit}</text>
        {data.lloq !== null && data.lloq !== undefined && (!log || data.lloq > 0) && (
          <g className="lloq"><line x1={PAD.l} x2={W - PAD.r} y1={y(data.lloq)} y2={y(data.lloq)} />
            <text x={W - PAD.r} y={y(data.lloq) - 4} textAnchor="end">LLOQ {sig(data.lloq)}</text></g>
        )}
        {series.map((s, i) => {
          const pts = s.times.map((t, k) => [t, s.values[k]] as const).filter(([, v]) => shown(v));
          return (
            <g key={s.name || i} className={many ? "series many" : "series"} style={{ color: color(i) }}>
              <polyline points={pts.map(([t, v]) => `${x(t).toFixed(1)},${y(v as number).toFixed(1)}`).join(" ")} />
              {!many && s.error && s.times.map((t, k) => {
                const v = s.values[k], e = s.error?.[k];
                if (v === null || e === undefined || !e) return null;
                const lo = Math.max(v - e, log ? yLo : 0);
                return <line key={`e${k}`} className="whisker" x1={x(t)} x2={x(t)} y1={y(lo)} y2={y(v + e)} />;
              })}
              {s.times.map((t, k) => {
                const v = s.values[k];
                if (v === null) {
                  return (
                    <circle key={k} className="blq" cx={x(t)} cy={data.lloq && (!log || data.lloq > 0) ? y(data.lloq) : H - PAD.b} r={4}>
                      <title>{`${s.name}: ${sig(t)} ${data.time_unit}, below the LLOQ`}</title>
                    </circle>
                  );
                }
                if (!shown(v)) return null;
                return (
                  <circle key={k} className="pt" cx={x(t)} cy={y(v)} r={many ? 2.5 : 4}>
                    <title>{`${s.name}: ${sig(t)} ${data.time_unit}, ${sig(v)} ${data.unit}${s.error?.[k] ? ` ± ${sig(s.error[k])} (${s.error_kind})` : ""}`}</title>
                  </circle>
                );
              })}
            </g>
          );
        })}
      </svg>
      <figcaption className="profile-legend">
        {many ? <span><i className="swatch" style={{ background: "var(--series-neutral)" }} />{series.length} subjects, each a line</span>
          : series.map((s, i) => (
            <span key={s.name || i}><i className="swatch" style={{ background: color(i) }} />{s.name || s.statistic.replace("_", " ")}
              {s.error_kind !== "none" && s.error ? ` ± ${s.error_kind}` : ""}{s.n ? ` (n ${s.n})` : ""}</span>
          ))}
        {series.some((s) => s.values.some((v) => v === null)) && <span><i className="swatch blq" />below the LLOQ</span>}
      </figcaption>
    </figure>
  );
}

function Stats({ data }: { data: Data }) {
  const rows = data.series.filter((s) => s.stats);
  if (!rows.length && !data.reported.length) return null;
  const auc = `${data.unit}·${data.time_unit}`;
  return (
    <div className="dataset-stats">
      {rows.length > 0 && (
        <div className="table-scroll">
          <table data-testid="dataset-stats">
            <caption>Computed by code from the points (the platform&apos;s NCA: linear-up / log-down; points below the LLOQ left out)</caption>
            <thead><tr><th>Series</th><th className="num">Cmax ({data.unit})</th><th className="num">tmax ({data.time_unit})</th>
              <th className="num">AUC0–last ({auc})</th><th className="num">t½ ({data.time_unit})</th><th className="num">AUC0–∞ ({auc})</th>
              <th className="num">points</th></tr></thead>
            <tbody>
              {rows.map((s: Series, i) => {
                const st = s.stats as Record<string, number | null>;
                return (
                  <tr key={s.name || i}>
                    <td>{s.name || s.statistic.replace("_", " ")}</td>
                    <td className="num">{sig(st.c_max)}</td><td className="num">{sig(st.t_max)}</td>
                    <td className="num">{sig(st.auc_last)}</td><td className="num">{sig(st.t_half)}</td>
                    <td className="num">{sig(st.auc_inf)}</td>
                    <td className="num">{st.points}{st.blq ? ` (+${st.blq} BLQ)` : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {data.reported.length > 0 && (
        <table data-testid="dataset-reported">
          <caption>Reported by the client</caption>
          <thead><tr><th>Parameter</th><th className="num">Value</th><th>Unit</th><th>Statistic</th></tr></thead>
          <tbody>
            {data.reported.map((r, i) => (
              <tr key={i}><td>{String(r.parameter)}</td><td className="num">{r.value === null ? "withheld" : sig(Number(r.value))}</td>
                <td>{String(r.unit ?? "")}</td><td>{String(r.statistic ?? "").replace("_", " ")}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Points({ data }: { data: Data }) {
  const times = [...new Set(data.series.flatMap((s) => s.times))].sort((a, b) => a - b);
  const cell = (s: Series, t: number) => {
    const k = s.times.indexOf(t);
    if (k < 0) return "";
    const v = s.values[k];
    if (v === null) return data.blinded ? "withheld" : "BLQ";
    return `${sig(v, 4)}${s.error?.[k] ? ` ± ${sig(s.error[k], 3)}` : ""}`;
  };
  return (
    <details className="dataset-points">
      <summary>Table of points ({times.length} times × {data.series.length} series)</summary>
      <div className="table-scroll">
        <table data-testid="dataset-points">
          <thead><tr><th className="num">time ({data.time_unit})</th>
            {data.series.map((s, i) => <th key={s.name || i} className="num">{s.name || s.statistic.replace("_", " ")} ({data.unit})</th>)}</tr></thead>
          <tbody>
            {times.map((t) => (
              <tr key={t}><td className="num">{sig(t, 4)}</td>{data.series.map((s, i) => <td key={i} className="num">{cell(s, t)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** A dataset as data on its study's card: chart, statistics, the client's reported PK and the table of points. */
export function DatasetView({ data, label, unsaved = false }: {
  data: Data; label: string;
  /** A sheet not saved yet: withheld while blinding is on because what it is for is not given (D-15). */
  unsaved?: boolean;
}) {
  return (
    <div className="dataset-view" data-testid="dataset-view">
      {data.blinded ? (
        <p className="muted" data-testid="dataset-blinded">Its values are withheld until the MAP is signed
          ({unsaved ? "blinding is on and what this study is for is not given yet" : "an external validation study"},
          D-15): the times and the metadata are shown, not the concentrations.</p>
      ) : data.kind === "profile" ? <ProfileChart data={data} label={label} /> : null}
      {!data.blinded && <Stats data={data} />}
      {data.series.length > 0 && <Points data={data} />}
    </div>
  );
}

type Profile = import("@/components/client/types").Profile;

/** A dissolution profile on its product's card (build C): the mean % dissolved with its spread, PK-Sim's Weibull fit,
 *  the conditions, and the table of points. */
export function ReleaseView({ p }: { p: Profile }) {
  const tMax = Math.max(...p.times_min, 1);
  const x = (t: number) => PAD.l + (t / tMax) * (W - PAD.l - PAD.r);
  const y = (v: number) => H - PAD.b - (Math.min(Math.max(v, 0), 110) / 110) * (H - PAD.t - PAD.b);
  const fit = p.fit && p.fit.t50_min && p.fit.shape ? p.fit : null;
  const curve = fit ? Array.from({ length: 61 }, (_, i) => {
    const t = (tMax * i) / 60, s = Math.max(t - fit.lag_min, 0);
    return `${x(t).toFixed(1)},${y(100 * (1 - Math.exp(-Math.LN2 * (s / (fit.t50_min as number)) ** (fit.shape as number)))).toFixed(1)}`;
  }).join(" ") : "";
  const conditions = Object.entries(p.key ?? {}).filter(([, v]) => v !== null && v !== "" && v !== undefined);
  return (
    <div className="dataset-view" data-testid="release-view">
      <figure className="profile-chart">
        <div className="profile-chart-bar"><span className="muted">{p.label}</span></div>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`release of ${p.label}`}>
          {[0, 25, 50, 75, 100].map((v) => (
            <g key={v} className="grid"><line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} />
              <text x={PAD.l - 6} y={y(v) + 4} textAnchor="end">{v}</text></g>
          ))}
          {ticks(0, tMax).map((t) => <text key={t} className="tick" x={x(t)} y={H - PAD.b + 16} textAnchor="middle">{sig(t)}</text>)}
          <text className="axis-label" x={(W + PAD.l) / 2} y={H - 4} textAnchor="middle">time (min)</text>
          <text className="axis-label" transform={`translate(12 ${(H - PAD.b) / 2}) rotate(-90)`} textAnchor="middle">% dissolved</text>
          {curve && <g className="series" style={{ color: "var(--series-2)" }}><polyline points={curve} /></g>}
          <g className="series" style={{ color: "var(--series-1)" }}>
            {p.times_min.map((t, i) => {
              const sd = p.cv[i] !== null && p.cv[i] !== undefined ? (p.cv[i] as number) * p.mean[i] / 100 : 0;
              return (
                <g key={t}>
                  {sd > 0 && <line className="whisker" x1={x(t)} x2={x(t)} y1={y(p.mean[i] - sd)} y2={y(p.mean[i] + sd)} />}
                  <circle className="pt" cx={x(t)} cy={y(p.mean[i])} r={4}>
                    <title>{`${sig(t)} min: ${sig(p.mean[i])} % dissolved${p.cv[i] !== null ? ` (CV ${sig(p.cv[i])} %)` : ""}`}</title>
                  </circle>
                </g>
              );
            })}
          </g>
        </svg>
        <figcaption className="profile-legend">
          <span><i className="swatch" style={{ background: "var(--series-1)" }} />mean of {p.n} vessels ± SD (from the CV)</span>
          {fit && <span><i className="swatch" style={{ background: "var(--series-2)" }} />PK-Sim Weibull fit</span>}
        </figcaption>
      </figure>
      {conditions.length > 0 && (
        <p className="muted" style={{ margin: 0, fontSize: 12 }} data-testid="release-conditions">
          {conditions.map(([k, v]) => `${k.replace(/_/g, " ")} ${String(v)}`).join(" · ")}</p>
      )}
      {fit && (
        <p style={{ margin: 0, fontSize: 13 }} data-testid="release-fit">Weibull fit: t50 {sig(fit.t50_min)} min
          {fit.se_t50 !== null ? ` ± ${sig(fit.se_t50, 2)}` : ""} · shape {sig(fit.shape)}{fit.se_shape !== null ? ` ± ${sig(fit.se_shape, 2)}` : ""}
          {" "}· RMSE {sig(fit.rmse_percent)} % · {fit.n_points} points{fit.engine_confirmed ? "" : " · equation not yet compared with PK-Sim's own curve"}</p>
      )}
      <details className="dataset-points">
        <summary>Table of points ({p.times_min.length} times)</summary>
        <div className="table-scroll">
          <table><thead><tr><th className="num">time (min)</th><th className="num">mean % dissolved</th><th className="num">CV %</th></tr></thead>
            <tbody>{p.times_min.map((t, i) => (
              <tr key={t}><td className="num">{sig(t, 4)}</td><td className="num">{sig(p.mean[i], 4)}</td>
                <td className="num">{p.cv[i] === null ? "—" : sig(p.cv[i], 3)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </details>
      {p.flags.length > 0 && <ul className="flags">{p.flags.map((f) => <li key={f}>{f}</li>)}</ul>}
    </div>
  );
}
