"use client";

import { useMemo, useState } from "react";

import { Card } from "@/components/ui";
import { uploadStudies } from "@/lib/writes";

const SAMPLE_CSV = `time_min,conc_umol_l
60,43.5
90,32.0
120,25.5
180,18.5
240,13.5
360,8.4
480,5.2
720,2.0`;

type Table = { headers: string[]; rows: string[][] };

function parseTable(text: string): Table {
  const lines = text.trim().split(/\r?\n/).filter((l) => l.trim());
  if (lines.length === 0) return { headers: [], rows: [] };
  const delim = lines[0].includes("\t") ? "\t" : lines[0].includes(";") ? ";" : ",";
  const cells = lines.map((l) => l.split(delim).map((c) => c.trim()));
  return { headers: cells[0], rows: cells.slice(1) };
}

function guess(headers: string[], words: string[], fallback: number) {
  const i = headers.findIndex((h) => words.some((w) => h.toLowerCase().includes(w)));
  return i >= 0 ? i : Math.min(fallback, Math.max(headers.length - 1, 0));
}

export function DataIntake({ projectId }: { projectId: string }) {
  const [text, setText] = useState("");
  const [studyId, setStudyId] = useState("");
  const [route, setRoute] = useState("iv_infusion");
  const [dose, setDose] = useState("250");
  const [infusion, setInfusion] = useState("60");
  const [timeUnit, setTimeUnit] = useState("min");
  const [unit, setUnit] = useState("µmol/l");
  const [timeCol, setTimeCol] = useState(0);
  const [concCol, setConcCol] = useState(1);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ kind: "ok" | "err"; message: string } | null>(null);

  const table = useMemo(() => parseTable(text), [text]);

  function load(sample: string) {
    const t = parseTable(sample);
    setText(sample);
    setTimeCol(guess(t.headers, ["time", "hr", "min"], 0));
    setConcCol(guess(t.headers, ["conc", "value", "cp", "plasma"], 1));
    setResult(null);
  }

  // rows where both mapped cells are numeric — what actually becomes the observed profile
  const profile = useMemo(() => {
    const times: number[] = [];
    const values: number[] = [];
    for (const r of table.rows) {
      const t = Number(r[timeCol]);
      const v = Number(r[concCol]);
      if (Number.isFinite(t) && Number.isFinite(v)) {
        times.push(t);
        values.push(v);
      }
    }
    return { times, values };
  }, [table, timeCol, concCol]);

  const ready = profile.times.length >= 2 && studyId.trim().length > 0 && Number(dose) > 0;

  async function save() {
    setBusy(true);
    setResult(null);
    try {
      const study = {
        study_id: studyId.trim(),
        reference: "Uploaded via data intake",
        route,
        dose_mg: Number(dose),
        infusion_time_min: route.startsWith("iv") ? Number(infusion) || null : null,
        formulation: "solution",
        food_state: "fasted",
        n_timepoints: profile.times.length,
        profile: { times: profile.times, values: profile.values, time_unit: timeUnit, unit },
      };
      const env = await uploadStudies(projectId, [study]);
      if (env.errors?.length) setResult({ kind: "err", message: env.errors[0].message });
      else setResult({ kind: "ok", message: `Saved "${study.study_id}" with ${profile.times.length} points. It is now part of this project's observed data.` });
    } catch {
      setResult({ kind: "err", message: "Could not reach the API to save the study." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cols-2 cols-intake">
      <Card title="1 · Paste or upload the observed data">
        <p className="muted" style={{ marginTop: 0 }}>
          A clinical concentration-time profile as CSV (or tab/semicolon separated). The first row is the header.
        </p>
        <div className="row" style={{ marginBottom: 10 }}>
          <input
            type="file"
            accept=".csv,.tsv,.txt"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) load(await f.text());
            }}
          />
          <button className="btn" onClick={() => load(SAMPLE_CSV)}>Use example data</button>
        </div>
        <div className="field">
          <textarea rows={12} value={text} onChange={(e) => setText(e.target.value)}
            placeholder={"time_min,conc_umol_l\n60,43.5\n120,25.5"}
            style={{ fontFamily: "var(--mono, monospace)", fontSize: 12 }} />
        </div>
        {table.headers.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr>{table.headers.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
              <tbody>
                {table.rows.slice(0, 6).map((r, i) => (
                  <tr key={i}>{r.map((c, j) => <td key={j} className="num">{c}</td>)}</tr>
                ))}
              </tbody>
            </table>
            {table.rows.length > 6 && <p className="muted" style={{ fontSize: 12 }}>…{table.rows.length - 6} more rows</p>}
          </div>
        )}
      </Card>

      <Card title="2 · Map the columns and confirm"
        action={profile.times.length > 0 ? <span className="chip low">{profile.times.length} points</span> : null}>
        {table.headers.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>Paste or upload data on the left to map its columns.</p>
        ) : (
          <>
            <div className="field">
              <label>Time column</label>
              <select value={timeCol} onChange={(e) => setTimeCol(Number(e.target.value))}>
                {table.headers.map((h, i) => <option key={i} value={i}>{h}</option>)}
              </select>
            </div>
            <div className="field">
              <label>Time unit</label>
              <select value={timeUnit} onChange={(e) => setTimeUnit(e.target.value)}>
                <option value="min">minutes</option>
                <option value="h">hours</option>
              </select>
            </div>
            <div className="field">
              <label>Concentration column</label>
              <select value={concCol} onChange={(e) => setConcCol(Number(e.target.value))}>
                {table.headers.map((h, i) => <option key={i} value={i}>{h}</option>)}
              </select>
            </div>
            <div className="field">
              <label>Concentration unit</label>
              <select value={unit} onChange={(e) => setUnit(e.target.value)}>
                <option value="µmol/l">µmol/l (molar)</option>
                <option value="µg/l">µg/l (mass)</option>
                <option value="mg/l">mg/l (mass)</option>
              </select>
            </div>

            <div className="field">
              <label>Study id</label>
              <input value={studyId} onChange={(e) => setStudyId(e.target.value)} placeholder="e.g. iv-250mg" />
            </div>
            <div className="field">
              <label>Route</label>
              <select value={route} onChange={(e) => setRoute(e.target.value)}>
                <option value="iv_infusion">IV infusion</option>
                <option value="iv_bolus">IV bolus</option>
                <option value="oral">Oral</option>
              </select>
            </div>
            <div className="field">
              <label>Dose (mg)</label>
              <input value={dose} onChange={(e) => setDose(e.target.value)} />
            </div>
            {route.startsWith("iv") && (
              <div className="field">
                <label>Infusion time (min)</label>
                <input value={infusion} onChange={(e) => setInfusion(e.target.value)} />
              </div>
            )}

            <div className="banner ok" style={{ marginBottom: 12 }}>
              Nothing is inferred silently — the mapping you confirm here is what enters the model. The backend
              runs deterministic NCA (AUC, Cmax, tmax, t½) on this profile to derive the observed PK the
              acceptance gate uses.
            </div>
            <button className="btn primary" disabled={!ready || busy} onClick={save}>
              {busy ? "Saving…" : "Confirm mapping & save study"}
            </button>
            {!ready && <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>Needs a study id, a dose, and at least two numeric rows.</p>}
          </>
        )}
        {result && (
          <div className={`banner ${result.kind === "ok" ? "ok" : "err"}`} style={{ marginTop: 12 }}>
            {result.message}{" "}
            {result.kind === "ok" && <a href={`/projects/${projectId}`}>Back to the project →</a>}
          </div>
        )}
      </Card>
    </div>
  );
}
