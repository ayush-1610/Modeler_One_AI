import { Card } from "@/components/ui";
import type { Vbe } from "@/lib/types";

const pct = (v: number) => `${Math.round(v * 100)} %`;

// S6 virtual bioequivalence (T-31): what the virtual trials say, and whether the model was validated against an
// observed BE study (F-304). A result that is not validated says so before any number.
export function VbeCard({ vbe }: { vbe: Vbe }) {
  const name = `${vbe.template} ${vbe.template_version}`;
  const validated = vbe.validation.status === "PASSED";
  return (
    <Card title="Virtual bioequivalence (S6)" action={
      <span className={`chip ${validated ? "low" : "high"}`} data-testid="vbe-validation">
        {vbe.status === "RUN" ? vbe.validation.status.replace("_", " ").toLowerCase() : "not run"}
      </span>}>
      {vbe.status !== "RUN" ? (
        <div className="banner warn" data-testid="vbe-not-run">{name} did not run: {vbe.reason}</div>
      ) : (
        <>
          {!validated && (
            <div className="banner warn" data-testid="vbe-not-validated">
              Not validated against an observed BE study ({vbe.validation.status}): {vbe.validation.reason}. This result
              does not support a bioequivalence decision on its own.
            </div>
          )}
          <p className="muted">
            {vbe.formulations?.test} against {vbe.formulations?.reference} · {name} · {vbe.n_trials_run} of{" "}
            {vbe.n_trials_planned} trials × {vbe.n_subjects} subjects · limits {vbe.limits?.[0]}–{vbe.limits?.[1]}
            {vbe.limits_verified ? "" : " (not verified)"}
          </p>
          <table>
            <thead><tr><th>Metric</th><th className="num">Probability of success</th><th className="num">GMR median</th>
              <th className="num">GMR 5–95 %</th><th className="num">Between-subject CV</th></tr></thead>
            <tbody>
              {Object.entries(vbe.metrics ?? {}).map(([metric, m]) => (
                <tr key={metric}>
                  <td>{metric}</td><td className="num">{pct(m.probability_of_success)}</td>
                  <td className="num">{m.gmr_median.toFixed(3)}</td>
                  <td className="num">{m.gmr_p05.toFixed(3)}–{m.gmr_p95.toFixed(3)}</td>
                  <td className="num">{m.between_subject_cv_percent.toFixed(1)} %</td>
                </tr>
              ))}
              <tr>
                <td><strong>Joint</strong></td>
                <td className="num" data-testid="vbe-joint"><strong>{pct(vbe.joint_probability_of_success ?? 0)}</strong></td>
                <td colSpan={3} className="muted">
                  {vbe.meets_threshold ? "meets" : "does not meet"} the threshold {pct(vbe.pos_threshold ?? 0)}
                </td>
              </tr>
            </tbody>
          </table>
        </>
      )}
    </Card>
  );
}
