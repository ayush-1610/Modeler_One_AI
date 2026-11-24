"use client";

// The Data room's evidence sections (plan 2026-11-21 v2 §5, §8): drug substance and ADME as Property · Value · Source ·
// Status, the composition side by side, solubility per pH, dissolution per medium with the fitted release, each
// clinical study's design and subject flow, and the observed mean profiles with the exposure recomputed beside the
// client's. Every number is the engine's; the page only lays it out.

import { useMemo, useState } from "react";

import {
  METRIC, STATISTIC, num, numbersIn, propertyOf, roleHex, roleOf, valueText,
  type Dissolution as DissolutionView, type Room, type Study, type Value,
} from "@/lib/dataroom";

import { Card, Nothing, Plot, Row, Segmented, Sources, StatusTag, Table, rule, series, usePaper } from "./kit";

// --- values ------------------------------------------------------------------------------------------------------------

/** Whether a value has more to say than its row (on paper the row's source is written out already). */
function hasDetails(v: Value, paper: boolean): boolean {
  return Boolean((v.as_written && v.as_written !== String(v.value)) || v.rule || v.note || v.others.length || (!paper && v.sources.length)
                 || v.sources.length > 1);
}

function ValueDetails({ v }: { v: Value }) {
  const paper = usePaper();
  return (
    <dl className="dr-facts">
      {v.as_written && v.as_written !== String(v.value) && <div><dt>As written</dt><dd>{v.as_written}</dd></div>}
      {v.rule && <div className="wide"><dt>Rule</dt><dd>{v.rule}</dd></div>}
      {v.note && <div className="wide"><dt>Note</dt><dd>{v.note}</dd></div>}
      {v.sources.length > 0 && !paper && <div className="wide"><dt>{v.sources.length > 1 ? "Sources" : "Source"}</dt><dd><Sources chips={v.sources} max={6} /></dd></div>}
      {v.others.map((o, i) => (
        <div key={i} className="wide"><dt>Also read</dt><dd>{valueText(o.value, o.unit)} <Sources chips={o.sources} /></dd></div>
      ))}
    </dl>
  );
}

export function ValueTable({ values, label, testId }: { values: readonly Value[]; label: string; testId?: string }) {
  const paper = usePaper();
  return (
    <Table head={["Property", "Value", "Source", "Status"]} label={label} testId={testId}>
      {values.map((v, i) => (
        <Row key={`${v.key}-${i}`} testId={`value-${v.key}`} highlight={v.status === "conflict"} cells={[
          <span key="p">{propertyOf(v)}</span>,
          <span key="v" className="dr-value">{valueText(v.value, v.unit)}</span>,
          <Sources key="s" chips={v.sources} />,
          <StatusTag key="t" status={v.status} />,
        ]} details={hasDetails(v, paper) ? <ValueDetails v={v} /> : undefined} />
      ))}
    </Table>
  );
}

export function Values({ values, title, empty }: { values: readonly Value[]; title: string; empty: string }) {
  if (!values.length) return <Nothing>{empty}</Nothing>;
  return <Card title={title}><ValueTable values={values} label={title} /></Card>;
}

// --- formulation -------------------------------------------------------------------------------------------------------

export function Formulation({ room }: { room: Room }) {
  const products = useMemo(() => {
    const named = room.question?.products?.map((p) => p.name) ?? [];
    const found = [...new Set(room.composition.flatMap((c) => Object.keys(c.amounts)))];
    return [...named.filter((n) => found.includes(n)), ...found.filter((n) => !named.includes(n))];
  }, [room]);
  return (
    <>
      {room.composition.length > 0 ? (
        <Card title="Composition, side by side" testId="composition"
              aside={<span className="muted dr-small">{room.composition.filter((c) => c.changed).length} rows change between products</span>}>
          <Table head={["Component", ...products]} label="The composition of each product">
            {room.composition.map((c) => (
              <Row key={c.component} highlight={c.changed} testId={`component-${c.component}`} cells={[
                <span key="c" className="dr-file"><span className="dr-file-name">{c.component}{c.changed && <span className="dr-tag warn small">Changed</span>}</span>
                  {c.function && <span className="dr-file-kind">{c.function}</span>}</span>,
                ...products.map((p) => <span key={p} className="tnum">{c.amounts[p] ?? "—"}</span>),
              ]} details={<dl className="dr-facts"><div className="wide"><dt>Sources</dt><dd><Sources chips={c.sources} max={4} /></dd></div></dl>} />
            ))}
          </Table>
        </Card>
      ) : <Nothing>No composition table was read.</Nothing>}
      {room.products.length > 0 && <Card title="Products and batches"><ValueTable values={room.products} label="Products and batches" /></Card>}
    </>
  );
}

// --- solubility --------------------------------------------------------------------------------------------------------

export function Solubility({ room }: { room: Room }) {
  const rows = [...room.solubility].sort((a, b) => (a.ph ?? 99) - (b.ph ?? 99));
  const paper = usePaper();
  const traces = useMemo(() => [{
    type: "bar", x: rows.map((r) => `${r.ph !== null ? `pH ${num(r.ph)}` : ""} ${r.medium}`.trim()),
    y: rows.map((r) => r.solubility_mg_ml), marker: { color: "#4B2A99", opacity: 0.85 }, name: "Solubility",
    text: rows.map((r) => (r.volume_for_dose_ml !== null ? `dose in ${num(r.volume_for_dose_ml, 3)} mL` : "")),
    textposition: "outside", cliponaxis: false, hovertemplate: "%{x}: %{y} mg/mL<extra></extra>",
  }], [rows]);
  if (!rows.length) return <Nothing>No solubility table was read.</Nothing>;
  return (
    <>
      <Card title="Solubility by pH" testId="solubility-chart"
            aside={<span className="muted dr-small">Log scale · above each bar, the volume the dose needs</span>}>
        <Plot label="Solubility per medium, log scale" traces={traces} height={paper ? 260 : 300}
              layout={{ showlegend: false, yaxis: { type: "log", title: { text: "Solubility (mg/mL)" } }, xaxis: { title: { text: "" } } }} />
      </Card>
      <Card title="What it means for the dose">
        <Table head={["Medium", "Solubility", "Volume for the dose", "Dose dissolved in 250 mL"]} label="Solubility and the dose">
          {rows.map((r) => (
            <Row key={`${r.medium}-${r.ph}`} cells={[
              <span key="m">{r.medium}{r.ph !== null && <span className="muted"> · pH {num(r.ph)}</span>}
                {r.ph_by_convention && <span className="muted" data-testid="ph-by-convention"> (by convention, not stated)</span>}
                {r.ph === null && r.ph_convention != null && (
                  <span className="muted" data-testid="ph-convention-pending"> · pH {num(r.ph_convention)} by convention, not stated: confirm it under Decisions</span>
                )}</span>,
              <span key="s" className="dr-value">{r.as_written} <Sources chips={r.sources} /></span>,
              <span key="v" className="tnum">{r.volume_for_dose_ml !== null ? `${num(r.volume_for_dose_ml, 3)} mL` : "—"}</span>,
              <span key="g" className="tnum">{r.fraction_in_glass !== null ? `${num(r.fraction_in_glass * 100, 3)} %` : "—"}</span>,
            ]} />
          ))}
        </Table>
      </Card>
    </>
  );
}

// --- dissolution -------------------------------------------------------------------------------------------------------

function mediumKey(d: DissolutionView) {
  return `${d.ph ?? ""}|${d.medium.toLowerCase()}`;
}

function DissolutionCard({ room, views }: { room: Room; views: DissolutionView[] }) {
  const first = views[0];
  const traces = useMemo(() => views.flatMap((d) => {
    const colour = roleHex(roleOf(room, d.product));
    const name = d.product || d.batch;
    const out = [series(`${name} (${d.batch})`, [...d.times_min], d.mean.map((m) => (Number.isFinite(m) ? m : null)), colour, {
      error_y: { type: "data", array: d.sd.map((s) => s ?? 0), visible: true, thickness: 1, width: 3, color: colour },
      hovertemplate: `${name}<br>%{x} min: %{y:.1f} %<extra>n = ${d.n_units}</extra>`, legendgroup: d.id })];
    if (d.weibull_curve.length) {
      out.push({ type: "scatter", mode: "lines", name: `${name}, Weibull fit`, x: d.weibull_curve.map((p) => p[0]),
                 y: d.weibull_curve.map((p) => p[1]), line: { color: colour, width: 1.2, dash: "dash" }, legendgroup: d.id,
                 showlegend: false, hoverinfo: "skip" });
    }
    return out;
  }), [room, views]);
  const method = [first.apparatus, first.rpm !== null ? `${num(first.rpm)} rpm` : "", first.volume_ml !== null ? `${num(first.volume_ml)} mL` : ""]
    .filter(Boolean).join(" · ");
  const f2 = room.f2.filter((f) => views.some((v) => v.id === f.test));
  const byId = Object.fromEntries(room.dissolution.map((d) => [d.id, d]));
  return (
    <Card title={first.medium || (first.ph !== null ? `pH ${num(first.ph)}` : "Medium not stated")} testId={`dissolution-${first.ph ?? "medium"}`}
          aside={<span className="muted dr-small">{method}</span>}>
      {first.ph_by_convention && first.ph !== null && (
        <p className="muted dr-small" data-testid="ph-by-convention">pH {num(first.ph)} by convention, not stated (confirmed for this project).</p>
      )}
      {first.ph === null && first.ph_convention != null && (
        <p className="muted dr-small" data-testid="ph-convention-pending">pH {num(first.ph_convention)} by convention, not stated: confirm it under Decisions.</p>
      )}
      <Plot label={`Dissolution in ${first.medium}`} traces={traces} testId="dissolution-chart"
            layout={{ xaxis: { title: { text: "Time (min)" }, rangemode: "tozero" }, yaxis: { title: { text: "Dissolved (%)" }, range: [0, 105] } }} />
      <ul className="dr-profiles">
        {views.map((d) => {
          const differs = d.problems.filter((p) => p.code === "MEAN_ROW_DIFFERS");
          const checked = d.client_mean.some((x) => x !== null);
          return (
            <li key={d.id} data-testid={`profile-${d.batch}`}>
              <span className="dr-swatch" style={{ background: roleHex(roleOf(room, d.product)) }} aria-hidden />
              <span className="dr-profile-name"><strong>{d.product || "Product not named"}</strong>
                <span className="muted"> · batch {d.batch} · {d.n_units} units</span></span>
              <span className="dr-profile-facts">
                {d.weibull.t50_min !== null && d.weibull.t50_min !== undefined && (
                  <span>Weibull t50 {num(Number(d.weibull.t50_min), 3)} min, shape {num(Number(d.weibull.shape), 3)}</span>)}
                {d.very_rapid && <span className="dr-tag ok small">≥ 85 % in 15 min</span>}
                {d.plateau && <span className="dr-tag warn small" data-testid="plateau">Levels off at {num(Math.max(...d.mean), 3)} %</span>}
                {checked && (differs.length
                  ? differs.map((p, i) => <span key={i} className="dr-tag bad small" title={p.message}>Client&apos;s mean row: {p.message}</span>)
                  : <span className="dr-tag quiet small">Client&apos;s mean row matches</span>)}
                <Sources chips={d.sources} />
              </span>
            </li>
          );
        })}
      </ul>
      {f2.length > 0 && (
        <ul className="dr-list dr-f2" aria-label="Similarity">
          {f2.map((f) => (
            <li key={`${f.test}-${f.reference}`} data-testid="f2">
              <span><strong>{byId[f.test]?.product || byId[f.test]?.batch}</strong> against {byId[f.reference]?.product || byId[f.reference]?.batch}:{" "}
                {f.applicable && f.value !== null ? <>f2 {num(f.value, 3)}, {f.similar ? "similar" : "not similar"}</> : f.reasons.join("; ")}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function Dissolution({ room }: { room: Room }) {
  const media = useMemo(() => {
    const out = new Map<string, DissolutionView[]>();
    for (const d of [...room.dissolution].sort((a, b) => (b.ph ?? 0) - (a.ph ?? 0))) {
      out.set(mediumKey(d), [...(out.get(mediumKey(d)) ?? []), d]);
    }
    return [...out.values()];
  }, [room]);
  if (!media.length) return <Nothing>No dissolution table was read.</Nothing>;
  return <>{media.map((views) => <DissolutionCard key={mediumKey(views[0])} room={room} views={views} />)}</>;
}

// --- clinical ----------------------------------------------------------------------------------------------------------

const DEMOGRAPHIC: [string, string, string][] = [["age", "Age", "years"], ["weight", "Weight", "kg"], ["height", "Height", "cm"],
                                                  ["bmi", "BMI", "kg/m²"]];

function demographics(study: Study): { label: string; text: string }[] {
  const d = Object.fromEntries(study.facts.filter((v) => v.key.includes(".demographics.")).map((v) => [v.key.split(".").pop()!, v.value]));
  const out = DEMOGRAPHIC.filter(([k]) => d[`${k}_mean`] !== undefined).map(([k, label, unit]) => ({
    label, text: `${num(Number(d[`${k}_mean`]), 3)} ± ${num(Number(d[`${k}_sd`]), 2)} ${unit} (${num(Number(d[`${k}_min`]), 3)}–${num(Number(d[`${k}_max`]), 3)})`,
  }));
  if (d.male !== undefined || d.female !== undefined) out.push({ label: "Sex", text: `${d.male ?? 0} male, ${d.female ?? 0} female` });
  return out;
}

function Flow({ study }: { study: Study }) {
  const dosed = study.sets.find((s) => s.name === "dosed")?.subjects.length ?? 0;
  const order = ["dosed", ...study.periods.map((p) => `dosed:${p}`), "completed", "client_statistical", "modeling", "auc"];
  const sets = order.map((n) => study.sets.find((s) => s.name === n)).filter((s): s is NonNullable<typeof s> => Boolean(s));
  const out = Object.entries(study.excluded).sort(([a], [b]) => Number(a) - Number(b));
  return (
    <div className="dr-flow" data-testid="subject-flow">
      {sets.map((s) => (
        <div key={s.name} className={`dr-bar${s.name === "modeling" ? " key" : ""}${s.source === "sponsor" ? " client" : ""}`}
             title={s.rule} data-testid={`set-${s.name}`}>
          <span className="dr-bar-label">{s.label}</span>
          <span className="dr-bar-track"><span className="dr-bar-fill" style={{ width: `${dosed ? (100 * s.subjects.length) / dosed : 0}%` }} /></span>
          <span className="dr-bar-n">{s.subjects.length}</span>
        </div>
      ))}
      {out.length > 0 && (
        <div className="dr-out">
          <h4>Who is out, and why</h4>
          <ul>{out.map(([s, why]) => <li key={s} data-testid={`excluded-${s}`}><strong>Subject {s}</strong> · {why}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

function StudyCard({ room, study }: { room: Room; study: Study }) {
  const paper = usePaper();
  const [all, setAll] = useState(false);
  const facts = study.facts.filter((v) => !v.key.includes(".demographics."));
  const shown = all || paper ? facts : facts.slice(0, 6);
  const dem = demographics(study);
  return (
    <>
      <Card title={`Study ${study.study_id}`} testId={`study-${study.study_id}`}
            aside={study.arms.length > 0 ? (
              <ul className="dr-arms">
                {study.arms.map((a) => (
                  <li key={a.treatment}><span className="dr-swatch" style={{ background: roleHex(a.role || roleOf(room, a.product)) }} aria-hidden />
                    <span><strong>{a.treatment}</strong> {a.product || a.meaning}{a.role && <span className="muted"> · {a.role}</span>}
                      {a.tied && <span className="muted dr-small" data-testid="arm-tied"> · tied by code: {a.tied}</span>}</span></li>
                ))}
              </ul>
            ) : undefined}>
        {facts.length > 0 ? <ValueTable values={shown} label={`The design of ${study.study_id}`} /> : <Nothing>No design facts were quoted.</Nothing>}
        {!paper && facts.length > 6 && (
          <button type="button" className="dr-link" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${facts.length} facts`}</button>
        )}
        {dem.length > 0 && (
          <dl className="dr-facts dr-dem" aria-label="Demographics">
            {dem.map((d) => <div key={d.label}><dt>{d.label}</dt><dd>{d.text}</dd></div>)}
          </dl>
        )}
      </Card>
      <Card title="Subject flow" aside={<span className="muted dr-small">Bars against the subjects dosed · hover a bar for its rule</span>}>
        <Flow study={study} />
      </Card>
    </>
  );
}

export function Clinical({ room }: { room: Room }) {
  if (!room.studies.length) return <Nothing>No concentration table was read, so no study is assembled yet.</Nothing>;
  return <>{room.studies.map((s) => <StudyCard key={s.study_id} room={room} study={s} />)}</>;
}

/** A message of the engine as a sentence: a capital first, a full stop last. */
const sentence = (text: string) => `${text[0]?.toUpperCase() ?? ""}${text.slice(1)}${/[.!?]$/.test(text) ? "" : "."}`;

// --- observed PK -------------------------------------------------------------------------------------------------------

function ProfileChart({ room, study }: { room: Room; study: Study }) {
  const [stat, setStat] = useState<"arithmetic" | "geometric">("arithmetic");
  const [scale, setScale] = useState<"linear" | "log">("linear");
  // the profiles of the analysis set the modeler chose (the suggestion, the modeling set, until one is chosen): the room
  // keeps one per set and arm
  const set = room.decisions.find((d) => d.id === `analysis-set:${study.study_id}`)?.chosen ?? "modeling";
  const shown = study.profiles.filter((p) => p.analysis_set === set);
  // the meals as the PK-Sim event holds them ("4; 10", hours after the dose), else as the study wrote them
  const event = room.inputs.find((r) => r.block === "event" && r.owner === study.study_id && typeof r.value === "string");
  const meals = study.facts.find((v) => v.key.startsWith("study.meal_times"));
  const mealTimes = event ? String(event.value).split(";").map(Number).filter(Number.isFinite)
    : meals ? numbersIn(meals.as_written || String(meals.value)) : [];
  const traces = useMemo(() => shown.map((p) => {
    const arm = study.arms.find((a) => a.treatment === p.treatment);
    const colour = roleHex(arm?.role || roleOf(room, arm?.product ?? ""));
    const name = `${p.treatment}${arm?.product ? ` · ${arm.product}` : ""}`;
    const pts = p.points;
    const y = pts.map((x) => (stat === "arithmetic" ? x.mean : x.geomean));
    return series(name, pts.map((x) => x.time_h), scale === "log" ? y.map((v) => (v && v > 0 ? v : null)) : y, colour, {
      ...(stat === "arithmetic" ? { error_y: { type: "data", array: pts.map((x) => x.sd ?? 0), visible: true, thickness: 1, width: 3, color: colour } } : {}),
      customdata: pts.map((x) => (stat === "arithmetic" ? x.n : x.n_geo)),
      hovertemplate: `${name}<br>%{x} h: %{y:.3g} ${study.concentration_unit}<br>N = %{customdata}<extra></extra>`,
    });
  }), [room, study, stat, scale]); // eslint-disable-line react-hooks/exhaustive-deps
  const marks = mealTimes.map((t) => rule(t, "meal"));
  return (
    <Card title={`${study.study_id}: mean profiles, ${study.sets.find((s) => s.name === set)?.label.toLowerCase() ?? "modeling set"}`}
          testId={`profiles-${study.study_id}`}
          aside={(
            <div className="dr-toggles">
              <Segmented label="Mean" value={stat} onChange={setStat} options={[["arithmetic", "Arithmetic ± SD"], ["geometric", "Geometric"]]} />
              <Segmented label="Scale" value={scale} onChange={setScale} options={[["linear", "Linear"], ["log", "Log"]]} />
            </div>
          )}>
      <Plot label={`Mean concentration profiles of ${study.study_id}`} traces={traces} testId="profile-chart"
            layout={{ shapes: marks.map((m) => m.shape), annotations: marks.map((m) => m.note),
                      xaxis: { title: { text: "Time after the dose (h)" }, rangemode: "tozero" },
                      yaxis: { title: { text: `Concentration (${study.concentration_unit || "unit not stated"})` }, type: scale } }} />
      <p className="dr-note">
        Below the LLOQ{study.lloq !== null ? ` (${num(study.lloq)} ${study.concentration_unit})` : ""}: 0 in the arithmetic mean, left out of the
        geometric mean. N at each time is shown on hover.
      </p>
    </Card>
  );
}

function Exposures({ study }: { study: Study }) {
  const rows = study.exposures.filter((e) => e.statistic !== "median");
  const method = study.problems.find((p) => p.code === "CLIENT_NCA_METHOD");
  const differs = study.problems.filter((p) => p.code === "NCA_DIFFERS");
  return (
    <Card title="Exposure, ours beside the client's" testId={`exposure-${study.study_id}`}>
      <Table head={["Metric", "Ours", "Client's", "Difference"]} label={`Exposure per arm of ${study.study_id}`}>
        {rows.map((e) => {
          const off = e.difference_percent !== null && Math.abs(e.difference_percent) > 1;
          return (
            <Row key={`${e.treatment}-${e.metric}-${e.statistic}`} highlight={off} cells={[
              <span key="m">{METRIC[e.metric] ?? e.metric} · {e.treatment}<span className="dr-file-kind">{STATISTIC[e.statistic] ?? e.statistic}, N = {e.n}</span></span>,
              <span key="o" className="tnum">{valueText(e.value, e.unit)}</span>,
              <span key="c" className="tnum">{e.client !== null ? valueText(e.client, e.unit) : "—"}</span>,
              <span key="d" className={`tnum${off ? " dr-bad" : ""}`}>{e.difference_percent !== null
                ? (e.metric === "tmax" ? `${num(e.difference_percent)} h` : `${e.difference_percent > 0 ? "+" : ""}${num(e.difference_percent, 2)} %`) : "—"}</span>,
            ]} />
          );
        })}
      </Table>
      <p className="dr-note" data-testid="nca-method">
        {method ? sentence(method.message) : "Ours: linear-up/log-down NCA per subject (below the LLOQ: 0 before the first quantifiable sample, left out after it)."}
        {" "}Cmax and Tmax are over the modeling set, AUC over the AUC set.
      </p>
      {differs.length > 0 && (
        <ul className="dr-list">{differs.map((p, i) => <li key={i} className="dr-flag"><StatusTag status="conflict" /><span className="dr-flag-body">{p.message}</span></li>)}</ul>
      )}
    </Card>
  );
}

export function Observed({ room }: { room: Room }) {
  const studies = room.studies.filter((s) => s.profiles.length);
  if (!studies.length) return <Nothing>No mean profile yet: it comes from a concentration table read for a study.</Nothing>;
  return <>{studies.map((s) => <div key={s.study_id} className="dr-stack"><ProfileChart room={room} study={s} /><Exposures study={s} /></div>)}</>;
}
