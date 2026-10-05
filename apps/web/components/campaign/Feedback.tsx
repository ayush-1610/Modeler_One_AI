// External-validation feedback (plan §12.3 N4, T-55): the S5 failure's diagnosis, and the cycles decided so far.
import type { FeedbackDecision, FeedbackDiagnosis } from "@/lib/types";

const num = (v: number | null | undefined) => (typeof v === "number" ? v.toPrecision(3) : "—");

export function FeedbackDiagnosisView({ diagnosis }: { diagnosis: FeedbackDiagnosis }) {
  return (
    <div data-testid="feedback-diagnosis" style={{ marginBottom: 12 }}>
      <table>
        <thead>
          <tr><th>Failing study</th><th>Class</th><th>Failed</th><th>Predicted / observed</th><th>Differs from training</th>
            <th>Parameters acting on it</th></tr>
        </thead>
        <tbody>
          {diagnosis.failing.map((f) => (
            <tr key={f.study_id}>
              <td><code>{f.study_id}</code></td>
              <td style={{ whiteSpace: "nowrap" }}>{f.class}</td>
              <td>{f.failed.join(", ")} <span className="muted">{f.direction}</span></td>
              <td className="num">{Object.entries(f.ratio).map(([q, r]) => `${q} ${r.toFixed(2)}`).join(" · ") || "—"}</td>
              <td className="muted">{f.differences.join("; ") || "no documented difference"}</td>
              <td>
                {f.influences.length === 0 ? <span className="muted">—</span> : (
                  <ul className="plain">
                    {f.influences.map((i) => (
                      <li key={i.parameter}><code>{i.parameter}</code>
                        {i.auc != null || i.cmax != null
                          ? <span className="muted"> AUC {num(i.auc)} · Cmax {num(i.cmax)}</span> : null}</li>
                    ))}
                  </ul>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="plain" style={{ marginTop: 8, fontSize: 13 }}>
        {Object.entries(diagnosis.classes).map(([name, c]) => (
          <li key={name}>
            <strong>{name}</strong>: external studies left {c.unspent.join(", ") || "none"}; learn cycles {c.cycles}.{" "}
            <span className={c.learn.possible ? "muted" : ""} style={c.learn.possible ? undefined : { color: "var(--fail)" }}>
              {c.learn.reason}</span>
          </li>
        ))}
      </ul>
      {(diagnosis.notes ?? []).map((n, i) => <p key={i} className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{n}</p>)}
    </div>
  );
}

const LABEL: Record<FeedbackDecision["action"], string> = {
  limitation: "limitation", learn: "learn", new_evidence: "new evidence", stop: "stop",
};

export function FeedbackTimeline({ decisions }: { decisions: FeedbackDecision[] }) {
  return (
    <ol className="cycles" data-testid="feedback-timeline">
      {decisions.map((d, i) => (
        <li key={i}>
          <span className="chip neutral">cycle {d.cycle}</span> <strong>{LABEL[d.action]}</strong>{" "}
          {d.action === "learn" && d.stages
            ? <>— {Object.entries(d.stages).map(([s, k]) => `${s} → ${k}`).join(", ")} (MAP deviation)</>
            : d.action === "new_evidence"
              ? <>— <code>{d.parameter}</code> = {d.value}{d.unit ? ` ${d.unit}` : ""} <span className="muted">({d.reference})</span></>
              : d.failing?.length ? <>— {d.failing.join(", ")}</> : null}
          {d.signature_id && <span className="muted" style={{ fontSize: 12 }}> · signed {d.signature_id}</span>}
          {d.note && <div className="muted" style={{ fontSize: 12 }}>{d.note}</div>}
        </li>
      ))}
    </ol>
  );
}
