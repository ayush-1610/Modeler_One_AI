/**
 * How a PBPK modeller actually reads a model: not "is this bar long" but "where does the predicted/observed
 * ratio sit against the fold limit we committed to?".
 *
 * The scale is logarithmic and centred on 1.0, so a 2-fold over-prediction and a 2-fold under-prediction sit
 * the same distance either side of unity. The shaded band is the acceptance tier the question was rated at
 * (ICH M15: 1.25-fold at high model risk, 1.5-fold at medium, 2-fold at low), so "inside the band" means
 * exactly what it means in the report. The number is always shown too — the position never carries the
 * verdict on its own.
 */
export function FoldError({ ratio, limit = 1.5, label }: { ratio: number | null; limit?: number; label?: string }) {
  if (ratio === null || !Number.isFinite(ratio) || ratio <= 0) {
    return <span className="muted">—</span>;
  }
  const span = Math.log(4); // the track covers 4-fold either way
  const pos = (value: number) => {
    const clamped = Math.max(-span, Math.min(span, Math.log(value)));
    return ((clamped + span) / (2 * span)) * 100;
  };
  const inside = ratio >= 1 / limit && ratio <= limit;
  const bandLeft = pos(1 / limit);
  const bandRight = pos(limit);
  const title = `${label ? label + ": " : ""}${ratio.toFixed(2)}-fold ` +
    `(${inside ? "within" : "outside"} the ${limit}-fold acceptance limit)`;

  return (
    <span className="fold" title={title}>
      <span className="fold-track" role="img" aria-label={title}>
        <span className="fold-band" style={{ left: `${bandLeft}%`, width: `${bandRight - bandLeft}%` }} />
        <span className="fold-unity" style={{ left: `${pos(1)}%` }} />
        <span className={`fold-mark${inside ? "" : " out"}`} style={{ left: `${pos(ratio)}%` }} />
      </span>
      <span className={`fold-value${inside ? "" : " out"}`}>{ratio.toFixed(2)}</span>
    </span>
  );
}
