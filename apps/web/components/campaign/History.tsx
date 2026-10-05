// The change ledger and the influence map (plan §12.3 N5, N6; T-54): which parameter change moved which verdict,
// and which parameters each study's simulation contains and responds to.
import type { InfluenceMap, LedgerEntry } from "@/lib/types";

const num = (v: number | string | null | undefined) =>
  typeof v === "number" ? (Math.abs(v) >= 1000 || v === 0 ? String(v) : v.toPrecision(3)) : v ?? "—";

export function LedgerTable({ entries }: { entries: LedgerEntry[] }) {
  return (
    <table data-testid="ledger">
      <thead>
        <tr><th className="num">#</th><th>Stage</th><th>Cause</th><th>Parameters changed</th><th>Study verdicts moved</th></tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr key={e.seq}>
            <td className="num">{e.seq}</td>
            <td>{e.stage}{(e.cycle ?? 1) > 1 ? <span className="muted"> · cycle {e.cycle}</span> : null}</td>
            <td><span className="chip neutral">{e.kind}</span> <span className="muted">{e.reason}</span></td>
            <td>
              {e.changes.length === 0 ? <span className="muted">{e.event ? "no parameter change" : e.note ?? "none"}</span> : (
                <ul className="plain">
                  {e.changes.map((c) => (
                    <li key={c.parameter}><code>{c.parameter}</code> {num(c.before)} → <strong>{num(c.after)}</strong>
                      {c.unit ? <span className="muted"> {c.unit}</span> : null}</li>
                  ))}
                </ul>
              )}
            </td>
            <td>
              {e.verdicts.length === 0 ? <span className="muted">none</span> : (
                <ul className="plain">
                  {e.verdicts.map((v, i) => (
                    <li key={`${v.study_id}-${i}`}>
                      <code>{v.study_id}</code> <span className="muted">({v.stage})</span>{" "}
                      {v.before} → <span className={`chip ${v.after === "pass" ? "low" : v.after === "fail" ? "high" : "neutral"}`}>{v.after}</span>
                    </li>
                  ))}
                </ul>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function InfluenceHeatMap({ map }: { map: InfluenceMap }) {
  const strength = (c?: { auc: number | null; cmax: number | null }) =>
    Math.max(Math.abs(c?.auc ?? 0), Math.abs(c?.cmax ?? 0));
  return (
    <>
      <div className="table-scroll">
        <table className="heat" data-testid="influence-map">
          <thead>
            <tr><th>Parameter</th>{map.studies.map((s) => <th key={s} className="rot" title={s}><span>{s}</span></th>)}</tr>
          </thead>
          <tbody>
            {map.parameters.map((p) => (
              <tr key={p}>
                <td><code>{p}</code> <span className="muted">{map.status?.[p]?.toLowerCase()}
                  {map.fitted_at_stage?.[p] ? ` at ${map.fitted_at_stage[p]}` : ""}</span></td>
                {map.studies.map((s) => {
                  const cell = map.cells[p]?.[s];
                  const v = strength(cell);
                  const title = !cell?.structural ? "not in this study's simulation"
                    : v ? `sensitivity: AUC ${num(cell.auc)}, Cmax ${num(cell.cmax)}` : "in the simulation; no sensitivity ranked";
                  return (
                    <td key={s} className={`num heat-cell ${cell?.structural ? "in" : "out"}`} title={title}
                        style={v ? { background: `color-mix(in srgb, var(--sim) ${Math.round(Math.min(1, v) * 70) + 10}%, transparent)` } : undefined}>
                      {!cell?.structural ? "" : v ? num(cell.auc ?? cell.cmax) : "·"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        {map.quantitative
          ? "Shaded: the engine's normalized local sensitivity (AUC, else Cmax; hover for both) from S6. · = in the study's simulation, not among its most influential. Blank = not in the simulation."
          : "Structural only (· = the parameter is in the study's simulation; blank = not). The engine's sensitivities appear once S6 has run."}
        {" "}Parameter set <code>{map.cpf_sha256.slice(0, 12)}</code>.
      </p>
    </>
  );
}
