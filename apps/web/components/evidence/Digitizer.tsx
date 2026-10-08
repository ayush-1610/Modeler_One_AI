"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { DocumentView } from "@/lib/brief";
import { BROWSER_TOKEN, apiFile, send, type Schema } from "@/lib/api";
import { useMutation } from "@/lib/hooks";

type Mode = "x1" | "x2" | "y1" | "y2" | "points";
type Axis = { p1: number | null; v1: string; p2: number | null; v2: string; log: boolean };
type Study = { study_id: string; reference: string; n: string; route: string; dose_mg: string; infusion_time_min: string;
               formulation: string; food_state: string; statistic: string };

const EMPTY_AXIS: Axis = { p1: null, v1: "", p2: null, v2: "", log: false };

/** T-19: a person calibrates the axes of a published figure and picks the points; the server maps them to data.
 *  Nothing is detected automatically: which marker is a point, and of which series, is the person's call. */
export function Digitizer({ projectId, documents, onSaved }: {
  projectId: string;
  documents: DocumentView[];
  onSaved: (datasetId: string) => void;
}) {
  const figures = documents.filter((d) => d.kind === "pdf" || d.kind === "image");
  const [sha, setSha] = useState(figures[0]?.sha256 ?? "");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [mode, setMode] = useState<Mode>("x1");
  const [x, setX] = useState<Axis>(EMPTY_AXIS);
  const [y, setY] = useState<Axis>(EMPTY_AXIS);
  const [series, setSeries] = useState("mean");
  const [points, setPoints] = useState<Record<string, [number, number][]>>({ mean: [] });
  const [study, setStudy] = useState<Study>({ study_id: "", reference: "", n: "", route: "oral", dose_mg: "", infusion_time_min: "",
                                              formulation: "ir_tablet", food_state: "fasted", statistic: "mean_sd" });
  const [units, setUnits] = useState({ time: "h", conc: "ng/ml", locator: "Figure " });
  const [error, setError] = useState<string | null>(null);
  const { run } = useMutation();
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const doc = figures.find((d) => d.sha256 === sha);

  const render = useCallback(async () => {
    if (!doc || !canvas.current) return;
    const url = `/api/v1/projects/${projectId}/documents/${doc.sha256}/raw`;
    const ctx = canvas.current.getContext("2d");
    if (!ctx) return;
    try {
      if (doc.kind === "pdf") {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
        const pdf = await pdfjs.getDocument({ url, httpHeaders: { Authorization: `Bearer ${BROWSER_TOKEN}` } }).promise;
        const p = await pdf.getPage(Math.min(page, pdf.numPages));
        const viewport = p.getViewport({ scale: 2 });
        canvas.current.width = viewport.width;
        canvas.current.height = viewport.height;
        await p.render({ canvasContext: ctx, viewport }).promise;
        setSize({ w: viewport.width, h: viewport.height });
      } else {
        const { file, problem } = await apiFile(url);
        if (!file) throw new Error(problem ?? "not readable");
        const img = await createImageBitmap(file);
        canvas.current.width = img.width;
        canvas.current.height = img.height;
        ctx.drawImage(img, 0, 0);
        setSize({ w: img.width, h: img.height });
      }
      setError(null);
    } catch (e) {
      setError(`The figure could not be drawn: ${(e as Error).message}`);
    }
  }, [doc, page, projectId]);
  useEffect(() => { void render(); }, [render]);

  function click(e: React.MouseEvent<HTMLDivElement>) {
    if (!canvas.current) return;
    const rect = canvas.current.getBoundingClientRect();
    const px = ((e.clientX - rect.left) * canvas.current.width) / rect.width;
    const py = ((e.clientY - rect.top) * canvas.current.height) / rect.height;
    if (mode === "x1") { setX({ ...x, p1: px }); setMode("x2"); }
    else if (mode === "x2") { setX({ ...x, p2: px }); setMode("y1"); }
    else if (mode === "y1") { setY({ ...y, p1: py }); setMode("y2"); }
    else if (mode === "y2") { setY({ ...y, p2: py }); setMode("points"); }
    else setPoints({ ...points, [series]: [...(points[series] ?? []), [Math.round(px * 10) / 10, Math.round(py * 10) / 10]] });
  }

  const calibrated = x.p1 !== null && x.p2 !== null && y.p1 !== null && y.p2 !== null && x.v1 && x.v2 && y.v1 && y.v2;
  const total = Object.values(points).reduce((n, p) => n + p.length, 0);

  async function save() {
    const n = Number(study.n);
    const body: Schema<"DigitizeBody"> = {
      study: { study_id: study.study_id, reference: study.reference, n, route: study.route, dose_mg: Number(study.dose_mg),
               formulation: study.formulation, food_state: study.food_state, statistic: study.statistic,
               ...(study.infusion_time_min ? { infusion_time_min: Number(study.infusion_time_min) } : {}) },
      doc_sha256: sha, page, locator: units.locator, time_unit: units.time, unit: units.conc, n,
      calibration: {
        x: { p1: x.p1, v1: Number(x.v1), p2: x.p2, v2: Number(x.v2), scale: x.log ? "log" : "linear" },
        y: { p1: y.p1, v1: Number(y.v1), p2: y.p2, v2: Number(y.v2), scale: y.log ? "log" : "linear" },
      },
      pixels: Object.fromEntries(Object.entries(points).filter(([, p]) => p.length > 0)),
    };
    const { data, problem } = await run(() => send("post", "/api/v1/projects/{project_id}/datasets:digitize", { project_id: projectId }, body));
    if (problem || !data) setError(problem ?? "not saved");
    else onSaved((data as { id: string }).id);   // the stored dataset (an open object); only its id is read here
  }

  if (!figures.length) return <p className="muted">Upload the paper (PDF) or a figure image first.</p>;
  const set = (k: keyof Study) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setStudy({ ...study, [k]: e.target.value });

  return (
    <div className="digitizer" data-testid="digitizer">
      <div className="row">
        <select value={sha} onChange={(e) => { setSha(e.target.value); setPage(1); }}>
          {figures.map((d) => <option key={d.sha256} value={d.sha256}>{d.name}</option>)}
        </select>
        {doc?.kind === "pdf" && (
          <label className="row" style={{ gap: 4 }}>page <input type="number" min={1} max={doc.n_pages} value={page}
                 onChange={(e) => setPage(Number(e.target.value))} style={{ width: 64 }} /></label>
        )}
        <span className="muted">{mode === "points" ? `click the points of “${series}”` : `click the ${mode.toUpperCase()} reference`}</span>
      </div>
      <div className="row" style={{ alignItems: "flex-start", marginTop: 8 }}>
        <div className="figure" onClick={click} style={{ cursor: "crosshair" }}>
          <canvas ref={canvas} />
          {size && (
            <svg viewBox={`0 0 ${size.w} ${size.h}`} className="overlay" aria-hidden>
              {x.p1 !== null && <line x1={x.p1} x2={x.p1} y1={0} y2={size.h} className="ref" />}
              {x.p2 !== null && <line x1={x.p2} x2={x.p2} y1={0} y2={size.h} className="ref" />}
              {y.p1 !== null && <line y1={y.p1} y2={y.p1} x1={0} x2={size.w} className="ref" />}
              {y.p2 !== null && <line y1={y.p2} y2={y.p2} x1={0} x2={size.w} className="ref" />}
              {Object.entries(points).flatMap(([name, list]) => list.map(([px, py], i) => (
                <circle key={`${name}-${i}`} cx={px} cy={py} r={size.w / 160} className={name === series ? "pt" : "pt other"} />
              )))}
            </svg>
          )}
        </div>
        <div style={{ minWidth: 260 }}>
          <fieldset>
            <legend>Axes</legend>
            {(["x", "y"] as const).map((a) => {
              const axis = a === "x" ? x : y;
              const setAxis = a === "x" ? setX : setY;
              return (
                <div key={a} style={{ marginBottom: 6 }}>
                  <div className="row" style={{ gap: 4 }}>
                    <button className="btn" onClick={() => setMode(`${a}1` as Mode)}>{a.toUpperCase()}1</button>
                    <input placeholder="value" value={axis.v1} onChange={(e) => setAxis({ ...axis, v1: e.target.value })} style={{ width: 70 }} />
                    <button className="btn" onClick={() => setMode(`${a}2` as Mode)}>{a.toUpperCase()}2</button>
                    <input placeholder="value" value={axis.v2} onChange={(e) => setAxis({ ...axis, v2: e.target.value })} style={{ width: 70 }} />
                    <label style={{ fontSize: 12 }}><input type="checkbox" checked={axis.log} onChange={(e) => setAxis({ ...axis, log: e.target.checked })} /> log</label>
                  </div>
                </div>
              );
            })}
          </fieldset>
          <fieldset>
            <legend>Series and points ({total})</legend>
            <div className="row" style={{ gap: 4 }}>
              <input value={series} onChange={(e) => { setSeries(e.target.value); setPoints({ ...points, [e.target.value]: points[e.target.value] ?? [] }); }} style={{ width: 120 }} />
              <button className="btn" onClick={() => setMode("points")}>Pick points</button>
              <button className="btn" onClick={() => setPoints({ ...points, [series]: (points[series] ?? []).slice(0, -1) })}>Undo</button>
            </div>
          </fieldset>
          <fieldset>
            <legend>Study</legend>
            <input placeholder="study id (author-year-route-dose)" value={study.study_id} onChange={set("study_id")} />
            <input placeholder="reference" value={study.reference} onChange={set("reference")} />
            <div className="row" style={{ gap: 4 }}>
              <input placeholder="n" value={study.n} onChange={set("n")} style={{ width: 50 }} />
              <input placeholder="dose mg" value={study.dose_mg} onChange={set("dose_mg")} style={{ width: 70 }} />
              <select value={study.route} onChange={set("route")}>
                {["oral", "iv_infusion", "iv_bolus"].map((r) => <option key={r}>{r}</option>)}
              </select>
            </div>
            <div className="row" style={{ gap: 4 }}>
              <select value={study.formulation} onChange={set("formulation")}>
                {["solution", "suspension", "ir_tablet", "ir_capsule", "mr", "other"].map((f) => <option key={f}>{f}</option>)}
              </select>
              <select value={study.food_state} onChange={set("food_state")}>
                <option>fasted</option><option>fed</option>
              </select>
              {study.route === "iv_infusion" && <input placeholder="infusion min" value={study.infusion_time_min} onChange={set("infusion_time_min")} style={{ width: 90 }} />}
            </div>
            <div className="row" style={{ gap: 4 }}>
              <input placeholder="time unit" value={units.time} onChange={(e) => setUnits({ ...units, time: e.target.value })} style={{ width: 70 }} />
              <input placeholder="conc. unit" value={units.conc} onChange={(e) => setUnits({ ...units, conc: e.target.value })} style={{ width: 90 }} />
              <input placeholder="Figure 2" value={units.locator} onChange={(e) => setUnits({ ...units, locator: e.target.value })} style={{ width: 90 }} />
            </div>
          </fieldset>
          {error && <div className="banner err">{error}</div>}
          <button className="btn primary" disabled={!calibrated || total === 0 || !study.study_id || !study.n || !study.dose_mg}
                  onClick={save} data-testid="digitize-save">Save the digitized dataset</button>
        </div>
      </div>
    </div>
  );
}
